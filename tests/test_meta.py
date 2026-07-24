"""Testes do P2: parsers de meta/eventos (fixtures reais de 17/07/2026) e
correlação jogador × meta (app/indicadores/meta.py)."""
from pathlib import Path

import pytest

from app.coleta import brawlace
from app.indicadores import meta as ind_meta

FIXTURES: Path = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def meta() -> dict:
    html: str = (FIXTURES / "meta_2026-07-17.html").read_text(encoding="utf-8")
    return brawlace.parsear_meta(html)


@pytest.fixture(scope="module")
def eventos() -> list[dict]:
    html: str = (FIXTURES / "eventos_2026-07-17.html").read_text(encoding="utf-8")
    return brawlace.parsear_eventos(html)


# --- parsear_meta ------------------------------------------------------------

def test_meta_tem_os_modos_principais(meta: dict):
    # o site tem 15 modos, mas um pode vir sem dados no período — tolerar
    assert len(meta["modos"]) >= 12
    for modo in ("HOT ZONE", "BRAWL BALL", "GEM GRAB", "KNOCKOUT", "BOUNTY",
                 "SOLO SHOWDOWN"):
        assert modo in meta["modos"], modo


def test_meta_hot_zone_rank_1(meta: dict):
    hot_zone = meta["modos"]["HOT ZONE"]
    assert hot_zone[0]["posicao"] == 1
    assert hot_zone[0]["brawler"] == "SURGE"
    assert hot_zone[0]["star_player"] == 3089
    assert hot_zone[0]["star_player_pct"] == 8.82


def test_meta_ranking_ordenado_e_completo(meta: dict):
    for modo, ranking in meta["modos"].items():
        assert len(ranking) >= 10, modo
        posicoes = [r["posicao"] for r in ranking]
        assert posicoes == sorted(posicoes), modo


# --- formato NOVO do brawlace (23/07/2026): 5 colunas + seção TEAMS ----------

@pytest.fixture(scope="module")
def meta_novo() -> dict:
    html: str = (FIXTURES / "meta_2026-07-23_teams.html").read_text(encoding="utf-8")
    return brawlace.parsear_meta(html)


def test_meta_novo_pula_secao_teams(meta_novo: dict):
    """A seção 'TEAMS' tem 1º td vazio e NÃO é ranking de brawler — deve ser
    ignorada sem derrubar toda a coleta (bug que quebrou o meta desde 17/07)."""
    assert "TEAMS" not in meta_novo["modos"]
    assert "BRAWL BALL" in meta_novo["modos"]
    assert "HOT ZONE" in meta_novo["modos"]


def test_meta_novo_5_colunas_e_separador_milhar(meta_novo: dict):
    bb = meta_novo["modos"]["BRAWL BALL"]
    assert bb[0]["brawler"] == "SURGE"
    assert bb[0]["star_player"] == 14480   # '14,480' com separador de milhar
    assert bb[0]["star_player_pct"] == 6.67
    assert bb[0]["posicao"] == 1


def test_meta_novo_data(meta_novo: dict):
    assert meta_novo["data"] == "2026-07-23 16:56:55"


# --- parsear_eventos ---------------------------------------------------------

def test_eventos_ativos(eventos: list[dict]):
    assert len(eventos) >= 5
    primeiro = eventos[0]
    assert primeiro["modo"] == "BRAWL BALL"
    assert primeiro["mapa"] == "Backyard Bowl"
    assert primeiro["inicio"] and primeiro["fim"]


def test_todo_evento_tem_modo_e_mapa(eventos: list[dict]):
    for e in eventos:
        assert e["modo"], e
        assert e["mapa"], e


# --- score vs meta -----------------------------------------------------------

META_SINTETICO: dict = {
    "data": "2026-07-17",
    "modos": {
        "HOT ZONE": [
            {"posicao": 1, "brawler": "SURGE", "star_player": 100, "star_player_pct": 10.0},
            {"posicao": 2, "brawler": "EMZ", "star_player": 50, "star_player_pct": 5.0},
            {"posicao": 3, "brawler": "BULL", "star_player": 10, "star_player_pct": 1.0},
            {"posicao": 4, "brawler": "POCO", "star_player": 5, "star_player_pct": 0.5},
        ],
    },
}


def test_score_brawler_no_topo_do_meta():
    batalhas = [{"modo": "HOT ZONE", "brawler": "SURGE"}] * 4
    resultado = ind_meta.score_vs_meta(META_SINTETICO, batalhas)
    assert resultado["score"] == 100.0


def test_score_pondera_por_partidas():
    batalhas = (
        [{"modo": "HOT ZONE", "brawler": "SURGE"}] * 3   # percentil 1.0
        + [{"modo": "HOT ZONE", "brawler": "POCO"}] * 1  # percentil 0.25
    )
    resultado = ind_meta.score_vs_meta(META_SINTETICO, batalhas)
    assert resultado["score"] == pytest.approx(81.2, abs=0.1)  # (3*1 + 1*0.25)/4


def test_score_brawler_fora_do_ranking_conta_como_ultimo():
    batalhas = [{"modo": "HOT ZONE", "brawler": "INEXISTENTE"}]
    resultado = ind_meta.score_vs_meta(META_SINTETICO, batalhas)
    assert resultado["score"] == 25.0
    assert resultado["detalhes"][0]["posicao_meta"] is None


def test_score_sem_batalhas_compatíveis():
    assert ind_meta.score_vs_meta(META_SINTETICO, [{"modo": "HEIST", "brawler": "X"}]) is None


# --- sugestões ---------------------------------------------------------------

BRAWLERS_JOGADOR: list[dict] = [
    {"nome": "EMZ", "power": 11, "trofeus": 1006},
    {"nome": "BULL", "power": 8, "trofeus": 500},    # power baixo, não sugerir
    {"nome": "POCO", "power": 11, "trofeus": 596},
]


def test_sugestoes_respeitam_power_minimo():
    eventos = [{"modo": "HOT ZONE", "mapa": "Controller Chaos", "inicio": None, "fim": None}]
    sugestoes = ind_meta.sugestoes_por_evento(META_SINTETICO, eventos, BRAWLERS_JOGADOR)
    assert len(sugestoes) == 1
    picks = [p["brawler"] for p in sugestoes[0]["picks"]]
    assert picks == ["EMZ", "POCO"]  # SURGE o jogador não tem; BULL power 8 fica fora


def test_sugestoes_deduplicam_eventos_repetidos():
    eventos = [
        {"modo": "HOT ZONE", "mapa": "Controller Chaos", "inicio": None, "fim": None},
        {"modo": "HOT ZONE", "mapa": "Controller Chaos", "inicio": None, "fim": None},
        {"modo": "HEIST", "mapa": "Safe Zone", "inicio": None, "fim": None},  # sem meta
    ]
    sugestoes = ind_meta.sugestoes_por_evento(META_SINTETICO, eventos, BRAWLERS_JOGADOR)
    assert len(sugestoes) == 1
