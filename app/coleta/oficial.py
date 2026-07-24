"""Coleta via API OFICIAL do Brawl Stars (developer.brawlstars.com).

Substitui o scraping do brawlace para o CORE (perfil, battlelog, clube, eventos).
Mapeia o JSON da API para o MESMO formato de dicts que o resto do app já consome
(ver brawlace.parsear_perfil), então db.py/indicadores/templates funcionam sem mudança.

Requer a variável de ambiente BRAWL_API_TOKEN (developer.brawlstars.com), com o IP
de saída registrado na key. Em host de IP fixo (VM), registra-se o IP da VM — sem proxy.

Diferenças-chave da API vs brawlace:
- NÃO há hash de batalha → sintetizamos uma chave global estável a partir de
  battleTime + tags de todos os jogadores (mesma batalha = mesma chave em qualquer
  perfil, preservando o design de batalhas globais).
- `battle.trophyChange` dá o delta direto → tipo TROFÉU se houver delta; senão Ranked.
- Times completos, star player, elo ranked numérico e acessórios (SP/gadget/gear/
  hypercharge) vêm nativos.
"""
from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

import httpx

BASE_URL = "https://api.brawlstars.com/v1"
_RAIZ = Path(__file__).resolve().parents[2]


class ErroColeta(Exception):
    """Falha de rede/HTTP ao falar com a API oficial."""


class TagInvalida(Exception):
    """Tag mal formada ou inexistente (404)."""


# ---------------------------------------------------------------------------
# Token / cliente HTTP (IPv4 forçado para bater com o IP registrado na key)
# ---------------------------------------------------------------------------

def _carregar_token() -> str:
    token = os.environ.get("BRAWL_API_TOKEN", "").strip()
    if not token:
        # fallback: lê do .env local (dev). Em produção use variável de ambiente.
        env = _RAIZ / ".env"
        if env.exists():
            for linha in env.read_text(encoding="utf-8").splitlines():
                if linha.strip().startswith("#") or "=" not in linha:
                    continue
                k, _, v = linha.partition("=")
                if k.strip() == "BRAWL_API_TOKEN":
                    token = v.strip()
                    break
    if not token:
        raise ErroColeta("BRAWL_API_TOKEN não configurado (.env ou variável de ambiente)")
    return token


def _cliente() -> httpx.Client:
    # local_address 0.0.0.0 → conexão sai por IPv4 (previsível para o IP registrado)
    return httpx.Client(
        base_url=BASE_URL,
        transport=httpx.HTTPTransport(local_address="0.0.0.0"),
        headers={"Authorization": f"Bearer {_carregar_token()}"},
        timeout=20.0,
    )


def _get(cliente: httpx.Client, caminho: str) -> dict | list:
    try:
        r = cliente.get(caminho)
    except httpx.HTTPError as e:
        raise ErroColeta(f"erro de rede em {caminho}: {e!r}") from e
    if r.status_code == 404:
        raise TagInvalida(f"não encontrado: {caminho}")
    if r.status_code == 403:
        raise ErroColeta("403 — IP não autorizado na key da API (conferir IPs registrados)")
    if r.status_code != 200:
        raise ErroColeta(f"HTTP {r.status_code} em {caminho}: {r.text[:200]}")
    return r.json()


# ---------------------------------------------------------------------------
# Normalização
# ---------------------------------------------------------------------------

_RE_TAG = re.compile(r"^#?[0289PYLQGRJCUV]+$", re.IGNORECASE)

def normalizar_tag(tag: str) -> str:
    """'299pgglql' / '#299PGGLQL ' → '#299PGGLQL'. Levanta TagInvalida se inválida."""
    t = tag.strip().upper().replace("O", "0")
    if not t.startswith("#"):
        t = "#" + t
    if not _RE_TAG.match(t) or len(t) < 4:
        raise TagInvalida(f"tag inválida: {tag!r}")
    return t


# modos camelCase → formato de exibição (igual ao que o brawlace/DB já usam)
_MODOS_EXPLICITOS = {
    "brawlBall5V5": "BRAWL BALL 5V5", "knockout5V5": "KNOCKOUT 5V5",
    "wipeout5V5": "WIPEOUT 5V5",
}

def _modo_exibicao(modo_camel: str | None) -> str | None:
    if not modo_camel:
        return None
    if modo_camel in _MODOS_EXPLICITOS:
        return _MODOS_EXPLICITOS[modo_camel]
    s = re.sub(r"([a-z])([A-Z])", r"\1 \2", modo_camel)  # brawlBall → brawl Ball
    return s.upper()


def _iso(battle_time: str) -> str | None:
    """'20260724T133607.000Z' → '2026-07-24T13:36:07Z'."""
    m = re.match(r"^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})", battle_time or "")
    if not m:
        return None
    a, mes, d, h, mi, s = m.groups()
    return f"{a}-{mes}-{d}T{h}:{mi}:{s}Z"


def _hash_batalha(battle_time: str, tags: list[str]) -> str:
    """Chave global estável: a mesma partida física tem o mesmo battleTime e os
    mesmos jogadores em qualquer perfil consultado."""
    base = f"{battle_time}|{'|'.join(sorted(tags))}"
    return hashlib.sha1(base.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Mapeamento: JSON da API → dicts do app
# ---------------------------------------------------------------------------

def _mapear_brawler(b: dict) -> dict:
    return {
        "nome": b.get("name"),
        "power": b.get("power"),
        "trofeus": b.get("trophies"),
        "trofeus_max": b.get("highestTrophies"),
        "skin": (b.get("skin") or {}).get("name"),
        "star_powers_nomes": [x["name"] for x in b.get("starPowers", [])],
        "gadgets_nomes": [x["name"] for x in b.get("gadgets", [])],
        "gears_nomes": [x["name"] for x in b.get("gears", [])],
        "hypercharge": bool(b.get("hyperCharges")),
    }


def _mapear_jogadores(battle: dict, tag_dono: str) -> tuple[list[dict], str | None, bool]:
    """Extrai os participantes (formato de batalha_jogadores) + brawler e
    star_player do dono. Suporta `teams` (3v3/duo) e `players` (solo showdown)."""
    dono_tag = tag_dono.upper()
    star_tag = ((battle.get("starPlayer") or {}).get("tag") or "").upper()
    jogadores: list[dict] = []
    meu_brawler: str | None = None
    meu_star: bool = False

    def _add(p: dict, time_idx: int) -> None:
        nonlocal meu_brawler, meu_star
        tag_p = (p.get("tag") or "").upper()
        brw = (p.get("brawler") or {})
        eu = tag_p == dono_tag
        star = tag_p == star_tag and bool(star_tag)
        if eu:
            meu_brawler = brw.get("name")
            meu_star = star
        jogadores.append({
            "tag_jogador": tag_p, "nick": p.get("name"),
            "brawler": brw.get("name"), "power": brw.get("power"),
            "trofeus": brw.get("trophies"), "time": time_idx,
            "eu": eu, "star_player": star,
        })

    if "teams" in battle and battle["teams"]:
        for i, time in enumerate(battle["teams"]):
            for p in time:
                _add(p, i)
    elif "players" in battle and battle["players"]:  # solo showdown
        for i, p in enumerate(battle["players"]):
            _add(p, i)
    return jogadores, meu_brawler, meu_star


def _mapear_batalha(item: dict, tag_dono: str) -> dict:
    battle = item.get("battle", {})
    evento = item.get("event", {})
    battle_time = item.get("battleTime", "")
    jogadores, meu_brawler, meu_star = _mapear_jogadores(battle, tag_dono)
    tags = [j["tag_jogador"] for j in jogadores] or [tag_dono.upper()]

    delta = battle.get("trophyChange")
    rank_sd = battle.get("rank")  # showdown: colocação 1..N
    res_bruto = (battle.get("result") or "").capitalize()  # victory→Victory
    resultado = res_bruto if res_bruto in ("Victory", "Defeat", "Draw") else None
    if resultado is None and rank_sd is not None and delta is not None:
        resultado = "Victory" if delta > 0 else ("Defeat" if delta < 0 else "Draw")
    if resultado is None:
        resultado = "Draw"

    # tipo: quem move troféu é a ladder de TROFÉU; delta presente → TROPHIES
    tipo = "TROPHIES" if delta not in (None,) else "RANKED"

    return {
        "hash": _hash_batalha(battle_time, tags),
        "ocorrida_em": _iso(battle_time),
        "tipo": tipo,
        "modo": _modo_exibicao(battle.get("mode") or evento.get("mode")),
        "resultado": resultado,
        "mapa": evento.get("map"),
        "duracao_seg": battle.get("duration"),
        "trofeus_delta": delta,
        "brawler": meu_brawler,
        "star_player": meu_star,
        "rank_showdown": rank_sd,
        "jogadores": jogadores,
    }


def _mapear_stats(p: dict) -> dict:
    def _ranked(nome_key: str, elo_key: str) -> str | None:
        nome = p.get(nome_key)
        elo = p.get(elo_key)
        if nome and elo is not None:
            return f"{nome} ({elo})"
        return nome or None
    return {
        "trofeus": p.get("trophies"),
        "trofeus_max": p.get("highestTrophies"),
        "level": p.get("expLevel"),
        "vitorias_3v3": p.get("3vs3Victories"),
        "vitorias_solo": p.get("soloVictories"),
        "vitorias_duo": p.get("duoVictories"),
        "ranked_atual": _ranked("rankedRankName", "rankedElo"),
        "ranked_max": _ranked("highestAllTimeRankedRankName", "highestAllTimeRankedElo"),
        # a API não expõe win streak 3v3 do jogador; aproxima pelo maior dos brawlers
        "win_streak_max": max((b.get("maxWinStreak") or 0)
                              for b in p.get("brawlers", [])) if p.get("brawlers") else None,
    }


# ---------------------------------------------------------------------------
# API pública do módulo
# ---------------------------------------------------------------------------

def coletar_perfil(tag: str) -> dict:
    """Perfil + battlelog no formato do app (compatível com db.salvar_consulta)."""
    tag = normalizar_tag(tag)
    enc = tag.replace("#", "%23")
    with _cliente() as c:
        p = _get(c, f"/players/{enc}")
        try:
            bl = _get(c, f"/players/{enc}/battlelog")
        except (ErroColeta, TagInvalida):
            bl = {"items": []}  # perfil novo pode não ter battlelog ainda
    if not isinstance(p, dict):
        raise ErroColeta("resposta de perfil inesperada")
    club = p.get("club") or {}
    batalhas = [_mapear_batalha(it, tag) for it in bl.get("items", [])]
    return {
        "tag": tag,
        "nick": p.get("name"),
        "clube": club.get("name"),
        "clube_tag": club.get("tag"),
        "stats": _mapear_stats(p),
        "brawlers": [_mapear_brawler(b) for b in p.get("brawlers", [])],
        "batalhas": batalhas,
        "grafico_trofeus": [],  # a API oficial não fornece; usamos snapshots
    }


def coletar_clube(clube_tag: str) -> dict:
    enc = clube_tag.replace("#", "%23")
    with _cliente() as c:
        d = _get(c, f"/clubs/{enc}")
    return {
        "clube_tag": clube_tag,
        "nome": d.get("name"),
        "membros": [{"tag": m.get("tag"), "nick": m.get("name")}
                    for m in d.get("members", [])],
    }


def coletar_eventos() -> list[dict]:
    """Rotação de eventos ativos → [{modo, mapa, inicio, fim}]."""
    with _cliente() as c:
        rot = _get(c, "/events/rotation")
    out: list[dict] = []
    for e in rot if isinstance(rot, list) else []:
        ev = e.get("event", {})
        out.append({
            "modo": _modo_exibicao(ev.get("mode")),
            "mapa": ev.get("map"),
            "inicio": _iso(e.get("startTime", "")),
            "fim": _iso(e.get("endTime", "")),
        })
    return out
