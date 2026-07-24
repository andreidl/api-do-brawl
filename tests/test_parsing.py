"""Testes de parsing offline com fixture HTML real (perfil de 17/07/2026).

Se o brawlace.com mudar de layout, estes testes continuam passando (fixture é
estática) — mas servem de rede de segurança contra regressões nos parsers.
Para detectar mudança de layout do site, baixar fixture nova e rodar de novo.
"""
import re
from pathlib import Path

import pytest

from app.coleta import brawlace

FIXTURE: Path = Path(__file__).parent / "fixtures" / "perfil_299PGGLQL_2026-07-17.html"
TAG: str = "#299PGGLQL"


@pytest.fixture(scope="module")
def perfil() -> dict:
    html: str = FIXTURE.read_text(encoding="utf-8")
    return brawlace.parsear_perfil(html, TAG)


# --- normalizar_tag ---------------------------------------------------------

def test_normalizar_tag_minuscula_sem_hash():
    assert brawlace.normalizar_tag("299pgglql") == "#299PGGLQL"


def test_normalizar_tag_com_hash_e_espacos():
    assert brawlace.normalizar_tag("  #299PGGLQL ") == "#299PGGLQL"


def test_normalizar_tag_invalida():
    with pytest.raises(brawlace.TagInvalida):
        brawlace.normalizar_tag("tag com espaço!")


def test_pagina_404_levanta_tag_invalida():
    with pytest.raises(brawlace.TagInvalida):
        brawlace.parsear_perfil("<html><title>404 Page Not Found | Brawl Ace</title></html>", "#X")


# --- stats gerais ------------------------------------------------------------

def test_nick_e_clube(perfil: dict):
    assert perfil["nick"] == "SNK | andreidl"
    assert perfil["clube"] == "clan Snake"


def test_stats_gerais(perfil: dict):
    stats = perfil["stats"]
    assert stats["level"] == 199
    assert stats["trofeus"] == 73118
    assert stats["trofeus_max"] == 73122
    assert stats["vitorias_3v3"] == 11413
    assert stats["win_streak_atual"] == 12
    assert stats["win_streak_max"] == 17
    assert stats["ranked_atual"] == "SILVER I (750)"
    assert stats["ranked_max"] == "MYTHIC I (6331)"


# --- brawlers ----------------------------------------------------------------

def test_quantidade_de_brawlers(perfil: dict):
    assert len(perfil["brawlers"]) == 104  # "Brawlers (104/106)" na fixture


def test_campos_do_brawler(perfil: dict):
    shelly = next(b for b in perfil["brawlers"] if b["nome"] == "SHELLY")
    assert shelly["power"] == 11
    assert shelly["trofeus"] > 0
    assert shelly["trofeus_max"] >= shelly["trofeus"]


def test_todo_brawler_tem_nome_e_power(perfil: dict):
    for b in perfil["brawlers"]:
        assert b["nome"], b
        assert 1 <= b["power"] <= 11, b


# --- battle log --------------------------------------------------------------

def test_quantidade_de_batalhas(perfil: dict):
    assert len(perfil["batalhas"]) == 25


def test_hashes_unicos_e_validos(perfil: dict):
    hashes = [b["hash"] for b in perfil["batalhas"]]
    assert len(set(hashes)) == 25
    assert all(re.fullmatch(r"[0-9a-f]{40}", h) for h in hashes)


def test_campos_da_batalha(perfil: dict):
    primeira = perfil["batalhas"][0]
    assert primeira["tipo"] == "RANKED"
    assert primeira["modo"] == "HOT ZONE"
    assert primeira["resultado"] == "Defeat"
    assert primeira["mapa"] == "Controller Chaos"
    assert primeira["ocorrida_em"] == "2026-07-17T03:11:36Z"
    assert primeira["duracao_seg"] == 76  # 01:16
    assert primeira["brawler"] == "EMZ"


def test_todas_batalhas_completas(perfil: dict):
    for b in perfil["batalhas"]:
        assert b["resultado"] in ("Victory", "Defeat", "Draw") or b["resultado"].startswith("Rank"), b
        assert b["modo"], b
        assert b["mapa"], b
        assert b["ocorrida_em"], b
        assert b["brawler"], b


def test_resumo_bate_com_site(perfil: dict):
    """A fixture mostra 'Victory : 11 (44%)' e 'Defeat : 14' no resumo do site."""
    vitorias = sum(1 for b in perfil["batalhas"] if b["resultado"] == "Victory")
    derrotas = sum(1 for b in perfil["batalhas"] if b["resultado"] == "Defeat")
    assert vitorias == 11
    assert derrotas == 14


def test_delta_de_trofeus_quando_presente(perfil: dict):
    """Uma batalha da fixture tem '| -4 |' no header (KNOCKOUT de 16/07 21:43)."""
    com_delta = [b for b in perfil["batalhas"] if b["trofeus_delta"] is not None]
    assert any(b["trofeus_delta"] == -4 for b in com_delta)


def test_tipo_trofeu_quando_ha_delta(perfil: dict):
    """Batalha com trophyChange (delta) é de TROFÉU, mesmo o brawlace rotulando
    'RANKED - MODO' (type='ranked' da API = ladder normal de troféus)."""
    com_delta = [b for b in perfil["batalhas"] if b["trofeus_delta"] is not None]
    assert com_delta, "fixture deveria ter ao menos uma batalha com delta"
    for b in com_delta:
        assert b["tipo"] == "TROPHIES", b


def test_tipo_ranked_sem_delta_permanece_ranked(perfil: dict):
    """Sem delta de troféu = modo competitivo Ranked (não move troféu)."""
    primeira = perfil["batalhas"][0]  # HOT ZONE 17/07, header sem '±'
    assert primeira["trofeus_delta"] is None
    assert primeira["tipo"] == "RANKED"


# --- gráfico de troféus (passado registrado pelo brawlace) -------------------

def test_grafico_trofeus(perfil: dict):
    grafico = perfil["grafico_trofeus"]
    assert len(grafico) == 26            # fixture: "Past 25 Matches" = 26 pontos
    assert grafico[0] == 73122
    assert grafico[-1] == 73118
    assert all(isinstance(v, int) for v in grafico)


def test_grafico_ausente_retorna_vazio():
    from app.coleta.brawlace import _parsear_grafico_trofeus
    assert _parsear_grafico_trofeus("<html>sem grafico</html>") == []


# --- banco -------------------------------------------------------------------

def test_salvar_consulta_deduplica(perfil: dict, tmp_path: Path):
    from app import db
    conexao = db.conectar(tmp_path / "teste.db")
    primeira = db.salvar_consulta(conexao, perfil)
    assert primeira["batalhas_novas"] == 25
    assert primeira["total_batalhas"] == 25
    segunda = db.salvar_consulta(conexao, perfil)
    assert segunda["batalhas_novas"] == 0     # dedupe por hash
    assert segunda["total_batalhas"] == 25
    assert len(db.snapshots_do_jogador(conexao, TAG)) == 2
    conexao.close()
