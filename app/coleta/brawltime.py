"""Fonte complementar: brawltime.ninja — só dados extras de carreira
(ano de criação da conta, recordes). API JSON pública (tRPC), sem HTML.
Falha aqui NUNCA derruba a consulta principal — retorna None.
"""
import json
import re
import urllib.parse

import httpx

from app.coleta import cache
from app.coleta.brawlace import USER_AGENT, normalizar_tag

TTL_EXTRA_SEG: int = 24 * 3600  # dados quase estáticos


def coletar_extra(tag: str) -> dict | None:
    """{'conta_criada_em': 2018, 'record_level': 6, 'record_points': 22310} ou None."""
    tag_sem_hash: str = normalizar_tag(tag).lstrip("#")
    entrada: str = urllib.parse.quote(json.dumps({"json": tag_sem_hash}))
    url: str = f"https://brawltime.ninja/api/player.byTagExtra?input={entrada}"

    corpo: str | None = cache.obter(url, TTL_EXTRA_SEG)
    if corpo is None:
        try:
            resposta = httpx.get(url, headers={"User-Agent": USER_AGENT}, timeout=10.0)
            if resposta.status_code != 200:
                return None
            corpo = resposta.text
            cache.salvar(url, corpo)
        except httpx.HTTPError:
            return None

    try:
        dados: dict = json.loads(corpo)["result"]["data"]["json"]
        return {
            "conta_criada_em": dados.get("accountCreationYear"),
            "record_level": dados.get("recordLevel"),
            "record_points": dados.get("recordPoints"),
        }
    except (KeyError, TypeError, json.JSONDecodeError):
        return None


# ---------------------------------------------------------------------------
# Meta por MAPA — página SSR de tier list do brawltime (validada 17/07/2026)
# https://brawltime.ninja/tier-list/mode/{modo-slug}/map/{Mapa-Com-Hifens}
# Amostras enormes (centenas de milhares de batalhas), winrate AJUSTADO por
# brawler no mapa + melhores TIMES do mapa. Falha NUNCA derruba nada → None.
# ---------------------------------------------------------------------------

from bs4 import BeautifulSoup

TTL_MAPA_SEG: int = 6 * 3600


def _slug_modo(modo: str) -> str:
    """'GEM GRAB' → 'gem-grab'; 'BRAWL BALL 5V5' → 'brawl-ball-5v5'."""
    return modo.strip().lower().replace(" ", "-")


def _slug_mapa(mapa: str) -> str:
    """'Gem Fort' → 'Gem-Fort' (o site usa hífens no lugar de espaços)."""
    return urllib.parse.quote(mapa.strip().replace(" ", "-"))


def parsear_meta_mapa(html: str) -> dict | None:
    """{'brawlers': {'NORI': 81.9, ...}, 'times': [{'brawlers': ['EDGAR',...],
    'vitorias': 350}, ...]} — None se as tabelas não existirem."""
    soup = BeautifulSoup(html, "lxml")
    brawlers: dict[str, float] = {}
    times: list[dict] = []
    for tabela in soup.find_all("table"):
        cabecalho = tabela.get_text(" ", strip=True)[:200]
        corpo = tabela.find("tbody")
        if corpo is None:
            continue
        if "Adjusted Win Rate" in cabecalho:
            for tr in corpo.find_all("tr"):
                nome_el = tr.find("figcaption")
                tds = tr.find_all("td")
                if nome_el is None or len(tds) < 2:
                    continue
                try:
                    wr = float(tds[1].get_text(strip=True).replace("%", ""))
                except ValueError:
                    continue
                brawlers[nome_el.get_text(strip=True).upper()] = wr
        elif "Wins Recorded" in cabecalho:
            for tr in corpo.find_all("tr"):
                nome_el = tr.find("figcaption")
                tds = tr.find_all("td")
                if nome_el is None or len(tds) < 2:
                    continue
                nomes = [n.strip().upper() for n in nome_el.get_text(strip=True).split(",")]
                try:
                    vitorias = int(tds[-1].get_text(strip=True))
                except ValueError:
                    continue
                times.append({"brawlers": nomes, "vitorias": vitorias})
    if not brawlers:
        return None
    return {"brawlers": brawlers, "times": times}


def coletar_meta_mapa(modo: str, mapa: str) -> dict | None:
    """Meta do MAPA no brawltime (cache 6 h). None em qualquer falha."""
    url: str = (f"https://brawltime.ninja/tier-list/mode/{_slug_modo(modo)}"
                f"/map/{_slug_mapa(mapa)}")
    corpo: str | None = cache.obter(url, TTL_MAPA_SEG)
    if corpo is None:
        try:
            resposta = httpx.get(url, headers={"User-Agent": USER_AGENT},
                                 timeout=15.0, follow_redirects=True)
            if resposta.status_code != 200:
                return None
            corpo = resposta.text
            cache.salvar(url, corpo)
        except httpx.HTTPError:
            return None
    try:
        return parsear_meta_mapa(corpo)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Melhores acessórios por brawler (global) — página SSR do brawler no brawltime
# https://brawltime.ninja/tier-list/brawler/{slug}. Tabelas transpostas:
# linha 1 = nomes (em <a title>), linha "Win Rate" = winrate por coluna.
# Global (não por mapa), mas é o "melhor acessório do brawler". Falha → None.
# ---------------------------------------------------------------------------

TTL_ACESSORIOS_SEG: int = 24 * 3600


def _slug_brawler(nome: str) -> str:
    """'MR. P' → 'mr-p'; '8-BIT' → '8-bit'; 'LARRY & LAWRIE' → 'larry-lawrie'."""
    s = nome.strip().lower()
    s = s.replace("&", " ").replace(".", " ").replace("'", "")
    s = re.sub(r"\s+", "-", s.strip())
    return re.sub(r"-+", "-", s)


def _melhor_de_tabela_transposta(tabela) -> dict | None:
    """Tabela [nomes | Win Rate | ...] → {'melhor': nome, 'winrate': float,
    'ranking': [(nome, wr), ...]}."""
    linhas = tabela.find_all("tr")
    if len(linhas) < 2:
        return None
    nomes = [a.get("title") for a in linhas[0].find_all("a") if a.get("title")]
    linha_wr = next(
        (tr for tr in linhas if "Win Rate" in tr.find("th").get_text() and "No " not in tr.find("th").get_text()),
        None,
    ) if linhas[0].find("th") else None
    if linha_wr is None or not nomes:
        return None
    wrs = []
    for td in linha_wr.find_all("td"):
        try:
            wrs.append(float(td.get_text(strip=True).replace("%", "")))
        except ValueError:
            wrs.append(None)
    pares = [(n, w) for n, w in zip(nomes, wrs) if w is not None]
    if not pares:
        return None
    pares.sort(key=lambda x: -x[1])
    return {"melhor": pares[0][0], "winrate": pares[0][1], "ranking": pares}


def parsear_acessorios_brawler(html: str) -> dict | None:
    """{'star_power': {...}, 'gadget': {...}, 'gear': {...}} — None se vazio."""
    soup = BeautifulSoup(html, "lxml")
    res: dict = {}
    for tabela in soup.find_all("table"):
        primeira = tabela.find("tr")
        if primeira is None:
            continue
        rotulo_el = primeira.find("th")
        rotulo = rotulo_el.get_text(strip=True) if rotulo_el else ""
        if rotulo == "Gadget":
            m = _melhor_de_tabela_transposta(tabela)
            if m:
                res["gadget"] = m
        elif rotulo == "Star Power":
            m = _melhor_de_tabela_transposta(tabela)
            if m:
                res["star_power"] = m
        elif "Gear" in (tabela.find("thead").get_text() if tabela.find("thead") else ""):
            corpo = tabela.find("tbody")
            linha = corpo.find("tr") if corpo else None
            if linha:
                nome_el = linha.find("span")
                tds = linha.find_all("td")
                if nome_el and len(tds) >= 2:
                    try:
                        res["gear"] = {"melhor": nome_el.get_text(strip=True),
                                       "winrate": float(tds[1].get_text(strip=True).replace("%", ""))}
                    except ValueError:
                        pass
    return res or None


def coletar_acessorios_brawler(nome: str) -> dict | None:
    """Melhores acessórios do brawler no brawltime (cache 24 h). None em QUALQUER
    falha (fonte complementar — nunca derruba a página)."""
    try:
        url: str = f"https://brawltime.ninja/tier-list/brawler/{_slug_brawler(nome)}"
    except Exception:
        return None
    corpo: str | None = cache.obter(url, TTL_ACESSORIOS_SEG)
    if corpo is None:
        try:
            resposta = httpx.get(url, headers={"User-Agent": USER_AGENT},
                                 timeout=15.0, follow_redirects=True)
            if resposta.status_code != 200:
                return None
            corpo = resposta.text
            cache.salvar(url, corpo)
        except httpx.HTTPError:
            return None
    try:
        return parsear_acessorios_brawler(corpo)
    except Exception:
        return None
