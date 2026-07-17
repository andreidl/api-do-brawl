"""Testes do parser de cards diários do Brawlify (app/importar_brawlify.py)."""
from app.importar_brawlify import (
    parsear_card, parsear_card_brawler, _reconstruir_trofeus_fim,
)


CARD_COMPLETO = (
    "YESTERDAY|2026-07-16|24 battles|+11W|-13L|-4|Battle Summary|11|Wins|13|Losses|"
    "46%|Win Rate|8|Brawlers|Brawlers Played|PIERCE|1x|-4|EMZ|10x|0|SQUEAK|1x|0|"
    "JACKY|4x|0|BO|2x|0|BROCK|4x|0|GROM|1x|0|EDGAR|1x|0|"
)

CARD_SEM_DERROTA = (
    "JUL 5, 2026|2026-07-05|7 battles|+7W|+76|Battle Summary|7|Wins|0|Losses|"
    "100%|Win Rate|2|Brawlers|Brawlers Played|STARR NOVA|2x|+19|BOLT|5x|+57|"
)

CARD_SEM_DELTA = (
    "NOV 15, 2025|2025-11-15|2 battles|+2W|Battle Summary|2|Wins|0|Losses|"
    "100%|Win Rate|1|Brawlers|Brawlers Played|BERRY|2x|0|"
)


def test_card_completo():
    dia = parsear_card("2026-07-16", CARD_COMPLETO)
    assert dia["batalhas"] == 24
    assert dia["vitorias"] == 11
    assert dia["derrotas"] == 13
    assert dia["trofeus_delta"] == -4
    assert len(dia["brawlers"]) == 8
    emz = next(b for b in dia["brawlers"] if b["brawler"] == "EMZ")
    assert emz["jogos"] == 10


def test_card_sem_derrota_com_delta_positivo():
    dia = parsear_card("2026-07-05", CARD_SEM_DELTA if False else CARD_SEM_DERROTA)
    assert dia["vitorias"] == 7
    assert dia["derrotas"] == 0
    assert dia["trofeus_delta"] == 76
    nomes = [b["brawler"] for b in dia["brawlers"]]
    assert "STARR NOVA" in nomes and "BOLT" in nomes


def test_card_sem_delta_assume_zero():
    dia = parsear_card("2025-11-15", CARD_SEM_DELTA)
    assert dia["batalhas"] == 2
    assert dia["trofeus_delta"] == 0


CARD_BRAWLER = (
    "BROCK|P11|RARE|·|PRESTIGE 1|1.1K|WIN STREAK|0 /5|LAST: 1|-1|BATTLES|52W|42L|"
    "KNOCKOUT|+197|34|23|BOUNTY|+29|12|12|HOT ZONE|+11|2|2|HEIST|-9|1|3|"
    "LAST PLAYED|TODAY|VIEW DETAILS"
)

CARD_BRAWLER_COM_EMPATE = (
    "JACKY|P11|SUPER RARE|·|PRESTIGE 1|1.1K|WIN STREAK|0 /13|LAST: 5|-5|BATTLES|"
    "22W|13L|1D|BRAWL BALL|+22|22|12|1|HOT ZONE|0|0|1|LAST PLAYED|TODAY|VIEW DETAILS"
)

CARD_BRAWLER_SEM_BATALHAS = (
    "GALE|P11|EPIC|·|GOLD|751|WIN STREAK|2 /6|LAST: 1|+1|VIEW DETAILS"
)


def test_card_brawler_completo():
    card = parsear_card_brawler(CARD_BRAWLER)
    assert card["brawler"] == "BROCK"
    assert card["vitorias"] == 52
    assert card["derrotas"] == 42
    assert card["trofeus_delta"] == 197 + 29 + 11 - 9
    assert len(card["modos"]) == 4
    knockout = card["modos"][0]
    assert knockout == {"modo": "KNOCKOUT", "trofeus_delta": 197,
                        "vitorias": 34, "derrotas": 23, "empates": 0}


def test_card_brawler_com_empate():
    card = parsear_card_brawler(CARD_BRAWLER_COM_EMPATE)
    assert card["empates"] == 1
    brawl_ball = card["modos"][0]
    assert brawl_ball["vitorias"] == 22
    assert brawl_ball["derrotas"] == 12
    assert brawl_ball["empates"] == 1


def test_card_brawler_sem_batalhas_retorna_none():
    assert parsear_card_brawler(CARD_BRAWLER_SEM_BATALHAS) is None


def test_reconstrucao_de_trofeus():
    dias = [
        {"data": "2026-07-15", "trofeus_delta": 100},
        {"data": "2026-07-16", "trofeus_delta": -4},
        {"data": "2026-07-17", "trofeus_delta": 0},
    ]
    _reconstruir_trofeus_fim(dias)
    # âncora: 73118 no fim de 2026-07-17
    assert dias[2]["trofeus_fim"] == 73118
    assert dias[1]["trofeus_fim"] == 73118          # 73118 - 0
    assert dias[0]["trofeus_fim"] == 73122          # 73118 - (-4)
