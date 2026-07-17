"""5ª fonte: brawlytix.com — dados de CONTA que ninguém mais tem (validada
17/07/2026): horas jogadas, skill score, valor estimado da conta, Elo ranked
numérico (atual e recorde), XP, prestige, skins por raridade, progressão
(o que falta para maxar), fama. Server-rendered → raspável com httpx.
Falha NUNCA derruba nada → None.
"""
import re

import httpx
from bs4 import BeautifulSoup

from app.coleta import cache
from app.coleta.brawlace import USER_AGENT, normalizar_tag

TTL_CONTA_SEG: int = 6 * 3600

_RE_SKILL = re.compile(r"SKILL SCORE\s*([\d.]+)\s*/\s*10\s*(\w+)", re.I)
_RE_VALOR = re.compile(r"ACCOUNT VALUE\s*([\d,.]+)", re.I)


def _numero(texto: str):
    """'73,162' → 73162; '14.5' → 14.5; '104/105' e textos ficam como estão."""
    limpo = texto.strip()
    if re.fullmatch(r"[\d,]+", limpo):
        return int(limpo.replace(",", ""))
    if re.fullmatch(r"\d+\.\d+", limpo):
        return float(limpo)
    return limpo


def parsear_conta(html: str) -> dict | None:
    """Todos os pares valor/label dos .stat-box + skill score + account value."""
    soup = BeautifulSoup(html, "lxml")
    stats: dict = {}
    for caixa in soup.select(".stat-box .stat"):
        rotulo = caixa.find("label")
        if rotulo is None:
            continue
        nome: str = rotulo.get_text(strip=True)
        valor: str = caixa.get_text(" ", strip=True).replace(
            rotulo.get_text(strip=True), ""
        ).strip()
        if nome and valor:
            stats[nome] = _numero(valor)
    if not stats:
        return None

    texto = soup.get_text(" ", strip=True)
    m_skill = _RE_SKILL.search(texto)
    m_valor = _RE_VALOR.search(texto)
    return {
        "skill_score": float(m_skill.group(1)) if m_skill else None,
        "skill_rotulo": m_skill.group(2) if m_skill else None,
        "valor_conta": int(m_valor.group(1).replace(",", "")) if m_valor else None,
        "stats": stats,
        # atalhos dos destaques
        "horas_jogadas": stats.get("Hours Spent"),
        "elo_ranked": stats.get("Ranked Elo"),
        "elo_ranked_recorde": stats.get("Highest Ranked Elo"),
        "wins_por_hora": stats.get("Wins per Hour"),
        "prestige": stats.get("Total Prestige"),
        "fama": stats.get("Fame Rank"),
    }


def coletar_conta(tag: str) -> dict | None:
    """Página de conta do Brawlytix (cache 6 h). None em qualquer falha."""
    tag_sem_hash: str = normalizar_tag(tag).lstrip("#")
    url: str = f"https://brawlytix.com/player/{tag_sem_hash}"
    corpo: str | None = cache.obter(url, TTL_CONTA_SEG)
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
        return parsear_conta(corpo)
    except Exception:
        return None
