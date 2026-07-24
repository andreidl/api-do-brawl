"""Testes do coletor da API oficial (app/coleta/oficial.py) — offline, com
fixtures de JSON real da API (não precisa de token nem rede)."""
import json
from pathlib import Path

import pytest

from app.coleta import oficial

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def player() -> dict:
    return json.loads((FIX / "oficial_player_299PGGLQL.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def battlelog() -> dict:
    return json.loads((FIX / "oficial_battlelog_299PGGLQL.json").read_text(encoding="utf-8"))


# --- normalizar_tag ---------------------------------------------------------

def test_normalizar_tag():
    assert oficial.normalizar_tag("299pgglql") == "#299PGGLQL"
    assert oficial.normalizar_tag("  #299PGGLQL ") == "#299PGGLQL"
    # O vira 0 (a Supercell não usa a letra O nas tags)
    assert oficial.normalizar_tag("#2O9") == "#209"


def test_normalizar_tag_invalida():
    with pytest.raises(oficial.TagInvalida):
        oficial.normalizar_tag("tag com espaço!")


# --- helpers de formato -----------------------------------------------------

def test_iso():
    assert oficial._iso("20260724T133607.000Z") == "2026-07-24T13:36:07Z"
    assert oficial._iso("") is None


def test_modo_exibicao():
    assert oficial._modo_exibicao("brawlBall") == "BRAWL BALL"
    assert oficial._modo_exibicao("hotZone") == "HOT ZONE"
    assert oficial._modo_exibicao("soloShowdown") == "SOLO SHOWDOWN"
    assert oficial._modo_exibicao("heist") == "HEIST"
    assert oficial._modo_exibicao("brawlBall5V5") == "BRAWL BALL 5V5"
    assert oficial._modo_exibicao(None) is None


def test_hash_batalha_estavel_e_ordem_independente():
    h1 = oficial._hash_batalha("20260724T133607.000Z", ["#A", "#B", "#C"])
    h2 = oficial._hash_batalha("20260724T133607.000Z", ["#C", "#A", "#B"])
    h3 = oficial._hash_batalha("20260724T133608.000Z", ["#A", "#B", "#C"])
    assert h1 == h2          # mesma batalha (ordem dos jogadores não importa)
    assert h1 != h3          # tempo diferente = batalha diferente
    assert len(h1) == 40 and all(c in "0123456789abcdef" for c in h1)


# --- mapear stats/brawler ---------------------------------------------------

def test_mapear_stats(player: dict):
    s = oficial._mapear_stats(player)
    assert s["trofeus"] == player["trophies"]
    assert s["level"] == player["expLevel"]
    assert s["vitorias_3v3"] == player["3vs3Victories"]
    # ranked no formato "NOME (elo)" — o _evolucao_ranked extrai o número dos ()
    if player.get("rankedElo") is not None:
        assert s["ranked_atual"].endswith(f"({player['rankedElo']})")


def test_mapear_brawler_acessorios(player: dict):
    b = oficial._mapear_brawler(player["brawlers"][0])
    assert b["nome"] and 1 <= b["power"] <= 11
    assert isinstance(b["star_powers_nomes"], list)
    assert isinstance(b["gadgets_nomes"], list)
    assert isinstance(b["hypercharge"], bool)


# --- mapear batalha ---------------------------------------------------------

def test_mapear_batalha_campos(battlelog: dict):
    item = battlelog["items"][0]
    b = oficial._mapear_batalha(item, "#299PGGLQL")
    assert b["hash"] and b["ocorrida_em"]
    assert b["modo"]
    assert b["tipo"] in ("TROPHIES", "RANKED")
    assert b["resultado"] in ("Victory", "Defeat", "Draw")
    # o dono tem que estar entre os jogadores e marcado eu=True
    donos = [j for j in b["jogadores"] if j["eu"]]
    assert len(donos) == 1
    assert donos[0]["tag_jogador"] == "#299PGGLQL"
    assert donos[0]["brawler"] == b["brawler"]


def test_tipo_por_trophychange(battlelog: dict):
    """Batalha com trophyChange → TROFÉU (nossa regra de classificação)."""
    for item in battlelog["items"]:
        b = oficial._mapear_batalha(item, "#299PGGLQL")
        if item["battle"].get("trophyChange") is not None:
            assert b["tipo"] == "TROPHIES", item["battle"].get("mode")


def test_star_player_do_dono(battlelog: dict):
    """Se o dono for o starPlayer da batalha, star_player=True."""
    for item in battlelog["items"]:
        b = oficial._mapear_batalha(item, "#299PGGLQL")
        star_tag = ((item["battle"].get("starPlayer") or {}).get("tag") or "").upper()
        esperado = star_tag == "#299PGGLQL"
        assert b["star_player"] == esperado


def test_todas_batalhas_tem_jogadores(battlelog: dict):
    for item in battlelog["items"]:
        b = oficial._mapear_batalha(item, "#299PGGLQL")
        assert len(b["jogadores"]) >= 1
        for j in b["jogadores"]:
            assert j["tag_jogador"]
            assert j["time"] is not None
