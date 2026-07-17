"""Testes das novidades: jogadores por batalha, matchups/parceiros,
star player e tendências do meta."""
import sqlite3
from pathlib import Path

import pytest

from app import db
from app.coleta import brawlace
from app.indicadores import performance
from app.indicadores.meta import tendencias_meta

FIXTURE_PERFIL = Path(__file__).parent / "fixtures" / "perfil_299PGGLQL_2026-07-17.html"
TAG = "#299PGGLQL"


@pytest.fixture(scope="module")
def perfil() -> dict:
    html = FIXTURE_PERFIL.read_text(encoding="utf-8")
    return brawlace.parsear_perfil(html, TAG)


# ---------------------------------------------------------------------------
# Parsing dos jogadores de cada batalha
# ---------------------------------------------------------------------------

def test_batalhas_tem_jogadores(perfil):
    com_jogadores = [b for b in perfil["batalhas"] if b["jogadores"]]
    assert com_jogadores, "nenhuma batalha veio com a lista de jogadores"
    primeira = com_jogadores[0]
    # 3v3 → 6 jogadores; showdown pode variar
    assert len(primeira["jogadores"]) >= 2


def test_jogadores_campos_e_eu(perfil):
    batalha = next(b for b in perfil["batalhas"] if b["jogadores"])
    eus = [j for j in batalha["jogadores"] if j["eu"]]
    assert len(eus) == 1
    eu = eus[0]
    assert eu["tag_jogador"] == TAG
    assert eu["aliado"] is True
    assert eu["brawler"]  # brawler identificado
    assert isinstance(eu["power"], int)
    assert isinstance(eu["trofeus"], int)


def test_jogadores_tem_aliados_e_inimigos(perfil):
    batalha = next(
        b for b in perfil["batalhas"]
        if b["jogadores"] and b["resultado"] in ("Victory", "Defeat")
    )
    aliados = [j for j in batalha["jogadores"] if j["aliado"]]
    inimigos = [j for j in batalha["jogadores"] if not j["aliado"]]
    assert aliados and inimigos


def test_star_player_da_batalha_consistente(perfil):
    """O star_player da batalha (parser antigo) bate com o do jogador 'eu'."""
    for batalha in perfil["batalhas"]:
        if not batalha["jogadores"]:
            continue
        eu = next(j for j in batalha["jogadores"] if j["eu"])
        assert eu["star_player"] == batalha["star_player"]


# ---------------------------------------------------------------------------
# Banco: batalha_jogadores
# ---------------------------------------------------------------------------

@pytest.fixture()
def conexao(tmp_path) -> sqlite3.Connection:
    con = db.conectar(tmp_path / "teste.db")
    yield con
    con.close()


def test_salvar_e_ler_jogadores(conexao, perfil):
    db.salvar_consulta(conexao, perfil)
    linhas = db.jogadores_das_batalhas(conexao, TAG)
    assert linhas
    assert {"tag_jogador", "brawler", "aliado", "eu", "resultado", "modo"} <= set(linhas[0])
    # dedupe: salvar de novo não duplica
    db.salvar_consulta(conexao, perfil)
    assert len(db.jogadores_das_batalhas(conexao, TAG)) == len(linhas)


# ---------------------------------------------------------------------------
# Indicadores: social (matchups + parceiros) e star player
# ---------------------------------------------------------------------------

def _linha(hash_, resultado, aliado, eu, brawler, tag_j, nick="X"):
    return {
        "hash": hash_, "resultado": resultado, "aliado": aliado, "eu": eu,
        "brawler": brawler, "tag_jogador": tag_j, "nick": nick,
        "power": 11, "trofeus": 1000, "star_player": 0, "modo": "GEM GRAB",
        "tipo": "TROPHIES",
    }


def test_social_matchups_e_parceiros():
    linhas = [
        # 2 batalhas contra SHELLY: 1 vitória, 1 derrota → 50%
        _linha("b1", "Victory", 0, 0, "SHELLY", "#E1"),
        _linha("b2", "Defeat", 0, 0, "SHELLY", "#E2"),
        # parceiro #A juntos nas 2, com 1 vitória
        _linha("b1", "Victory", 1, 0, "JACKY", "#A", "Amigo"),
        _linha("b2", "Defeat", 1, 0, "JACKY", "#A", "Amigo"),
        # eu (deve ficar fora de parceiros)
        _linha("b1", "Victory", 1, 1, "EMZ", TAG),
        _linha("b2", "Defeat", 1, 1, "EMZ", TAG),
    ]
    resultado = performance.social(linhas)
    assert resultado["batalhas_cobertas"] == 2
    shelly = next(m for m in resultado["matchups"] if m["brawler"] == "SHELLY")
    assert shelly["jogos"] == 2 and shelly["winrate"] == 50.0
    assert len(resultado["parceiros"]) == 1
    amigo = resultado["parceiros"][0]
    assert amigo["tag"] == "#A" and amigo["jogos"] == 2 and amigo["winrate"] == 50.0


def test_social_vazio():
    assert performance.social([]) == {
        "matchups": [], "parceiros": [], "batalhas_cobertas": 0
    }


def test_star_player_taxas(perfil):
    resultado = performance.star_player(perfil["batalhas"])
    assert resultado is not None
    assert 0 <= resultado["taxa_geral"] <= 100
    assert resultado["stars"] <= resultado["total"]


# ---------------------------------------------------------------------------
# Tendências do meta
# ---------------------------------------------------------------------------

def test_tendencias_precisa_de_duas_datas(conexao):
    conexao.execute(
        "INSERT INTO meta_snapshots (data, modo, brawler, star_player_pct, posicao)"
        " VALUES ('2026-07-16', 'GEM GRAB', 'EMZ', 10.0, 3)"
    )
    conexao.commit()
    assert tendencias_meta(conexao) is None


def test_tendencias_sobe_e_desce(conexao):
    dados = [
        ("2026-07-16", "GEM GRAB", "EMZ", 10.0, 5),
        ("2026-07-16", "GEM GRAB", "BO", 9.0, 2),
        ("2026-07-17", "GEM GRAB", "EMZ", 12.0, 1),   # subiu 4
        ("2026-07-17", "GEM GRAB", "BO", 5.0, 8),     # caiu 6
    ]
    conexao.executemany(
        "INSERT INTO meta_snapshots (data, modo, brawler, star_player_pct, posicao)"
        " VALUES (?, ?, ?, ?, ?)", dados
    )
    conexao.commit()
    t = tendencias_meta(conexao)
    assert t is not None
    assert t["subindo"][0]["brawler"] == "EMZ" and t["subindo"][0]["delta"] == 4
    assert t["caindo"][0]["brawler"] == "BO" and t["caindo"][0]["delta"] == -6


# ---------------------------------------------------------------------------
# Unificação: batalhas globais + migração do schema antigo
# ---------------------------------------------------------------------------

def test_consulta_alimenta_historico_dos_parceiros(conexao, perfil):
    """Salvar as batalhas do dono deve criar histórico com resultado para a
    camila (aliada) e para inimigos de 3v3."""
    db.salvar_consulta(conexao, perfil)
    camila = db.batalhas_do_jogador(conexao, "#2QLLLGV0R0")
    assert camila, "camila participou de batalhas do fixture e deveria ter histórico"
    decididas = [b for b in camila if b["resultado"] in ("Victory", "Defeat")]
    assert decididas, "resultado da camila deveria ser derivado do time vencedor"
    # ela é aliada: resultado dela = resultado do dono nas mesmas batalhas
    minhas = {b["hash"]: b["resultado"] for b in db.batalhas_do_jogador(conexao, TAG)}
    for b in decididas:
        assert b["resultado"] == minhas[b["hash"]]


def test_mesma_batalha_nao_duplica_entre_donos(conexao, perfil):
    db.salvar_consulta(conexao, perfil)
    total_fisico = conexao.execute("SELECT COUNT(*) FROM batalhas").fetchone()[0]
    # "consulta da camila": mesmas batalhas vistas do perfil dela (hash global)
    db.salvar_batalhas(conexao, "#2QLLLGV0R0", [
        {**b, "jogadores": [
            {**j, "eu": j["tag_jogador"] == "#2QLLLGV0R0"} for j in b["jogadores"]
        ]}
        for b in perfil["batalhas"]
    ])
    conexao.commit()
    assert conexao.execute("SELECT COUNT(*) FROM batalhas").fetchone()[0] == total_fisico
    # e a camila não perde nada: continua com o histórico dela
    assert db.contar_batalhas(conexao, "#2QLLLGV0R0") > 0


def test_migracao_do_schema_antigo(tmp_path):
    import sqlite3 as s3
    caminho = tmp_path / "antigo.db"
    con = s3.connect(caminho)
    con.executescript("""
        CREATE TABLE jogadores (tag TEXT PRIMARY KEY, nick TEXT,
                                primeiro_visto TEXT, ultimo_visto TEXT);
        CREATE TABLE batalhas (
          hash TEXT PRIMARY KEY, tag TEXT, ocorrida_em TEXT, modo TEXT,
          tipo TEXT, mapa TEXT, brawler TEXT, resultado TEXT,
          duracao_seg INTEGER, trofeus_delta INTEGER, star_player INTEGER);
        CREATE TABLE batalha_jogadores (
          hash TEXT, tag_jogador TEXT, nick TEXT, brawler TEXT, power INTEGER,
          trofeus INTEGER, aliado INTEGER, eu INTEGER, star_player INTEGER,
          PRIMARY KEY (hash, tag_jogador));
        INSERT INTO batalhas VALUES
          ('a'||substr('0000000000000000000000000000000000000000',1,39),
           '#DONO', '2026-07-01T00:00:00Z', 'GEM GRAB', 'TROPHIES', 'Mapa X',
           'EMZ', 'Victory', 120, 8, 1);
        INSERT INTO batalha_jogadores VALUES
          ('a'||substr('0000000000000000000000000000000000000000',1,39),
           '#DONO', 'Dono', 'EMZ', 11, 1000, 1, 1, 1),
          ('a'||substr('0000000000000000000000000000000000000000',1,39),
           '#AMIGO', 'Amigo', 'BO', 11, 900, 1, 0, 0),
          ('a'||substr('0000000000000000000000000000000000000000',1,39),
           '#RIVAL', 'Rival', 'SHELLY', 10, 800, 0, 0, 0);
    """)
    con.commit(); con.close()

    conexao = db.conectar(caminho)
    assert "tag" not in [c[1] for c in conexao.execute("PRAGMA table_info(batalhas)")]
    dono = db.batalhas_do_jogador(conexao, "#DONO")
    assert dono[0]["resultado"] == "Victory" and dono[0]["brawler"] == "EMZ"
    amigo = db.batalhas_do_jogador(conexao, "#AMIGO")
    assert amigo[0]["resultado"] == "Victory"      # mesmo time do dono
    rival = db.batalhas_do_jogador(conexao, "#RIVAL")
    assert rival[0]["resultado"] == "Defeat"       # time perdedor
    # reconectar não migra de novo nem quebra
    conexao.close()
    conexao2 = db.conectar(caminho)
    assert db.contar_batalhas(conexao2, "#DONO") == 1
    conexao2.close()


def test_ranking_jogadores(conexao, perfil):
    db.salvar_consulta(conexao, perfil)
    ranking = db.ranking_jogadores(conexao, minimo_jogos=5)
    assert ranking, "dono e parceiros frequentes deveriam ranquear"
    tags = [r["tag"] for r in ranking]
    assert TAG in tags
    for r in ranking:
        assert r["jogos"] >= 5
        assert 0 <= r["winrate"] <= 100
    # ordenado por confiança (wilson) desc
    from app.indicadores.performance import wilson
    scores = [wilson(r["vitorias"], r["jogos"]) for r in ranking]
    assert scores == sorted(scores, reverse=True)


# ---------------------------------------------------------------------------
# Página instantânea (serve do banco) + refresh em segundo plano
# ---------------------------------------------------------------------------

def test_perfil_do_banco(conexao, perfil):
    assert db.perfil_do_banco(conexao, "#NUNCAVISTO") is None
    db.salvar_consulta(conexao, perfil)
    rapido = db.perfil_do_banco(conexao, TAG)
    assert rapido is not None
    assert rapido["nick"] == perfil["nick"]
    assert rapido["stats"]["trofeus"] == perfil["stats"]["trofeus"]
    assert len(rapido["brawlers"]) == len(perfil["brawlers"])
    assert rapido["batalhas"] and rapido["grafico_trofeus"] == []
    assert rapido["_snapshot_em"]


# ---------------------------------------------------------------------------
# Clube: parsing do roster + filtro do ranking
# ---------------------------------------------------------------------------

HTML_CLUBE = """<html><head><title>clan Snake Brawl Stars Club Stats | Brawl Ace</title></head>
<body><table>
<tr><td><a data-bs-player-tag="#299PGGLQL" href="#">SNK | andreidl</a></td></tr>
<tr><td><a data-bs-player-tag="#299PGGLQL" href="#">SNK | andreidl</a></td></tr>
<tr><td><a data-bs-player-tag="#2QLLLGV0R0" href="#">SNK |camilacgs</a></td></tr>
<tr><td><a data-bs-player-tag="#89R22LV2Y" href="#">LoganKL</a></td></tr>
</table></body></html>"""


def test_parsear_clube_pagina():
    clube = brawlace.parsear_clube_pagina(HTML_CLUBE, "#8LG0QGLC")
    assert clube["nome"] == "clan Snake"
    assert clube["clube_tag"] == "#8LG0QGLC"
    tags = [m["tag"] for m in clube["membros"]]
    assert tags == ["#299PGGLQL", "#2QLLLGV0R0", "#89R22LV2Y"]  # dedupe do 1º


def test_perfil_extrai_clube_tag(perfil):
    assert perfil["clube_tag"] == "#8LG0QGLC"


def test_salvar_clube_e_clube_principal(conexao):
    clube = brawlace.parsear_clube_pagina(HTML_CLUBE, "#8LG0QGLC")
    db.salvar_clube(conexao, clube)
    principal = db.clube_principal(conexao)
    assert principal["nome"] == "clan Snake"
    assert principal["membros"] == {"#299PGGLQL", "#2QLLLGV0R0", "#89R22LV2Y"}
    # atualizar substitui o roster (membro que saiu do clã some)
    clube["membros"] = clube["membros"][:2]
    db.salvar_clube(conexao, clube)
    assert db.clube_principal(conexao)["membros"] == {"#299PGGLQL", "#2QLLLGV0R0"}


# ---------------------------------------------------------------------------
# Showdown de troféus: header 'RANKED | RANK n - MODO' + reparo do banco
# ---------------------------------------------------------------------------

HTML_SHOWDOWN = """<html><body>
<div id="ab34567890123456789012345678901234567890">
  <div class="card-header">RANKED | RANK 2 - DUO SHOWDOWN | Victory |  +10 |
    <time datetime="2026-07-17T13:52:43Z">4 minutes ago</time>
    <img data-map-name="Truth" src="x.png">
  </div>
  <div class="card-body"><div class="row"><div class="col-md-6"><div class="shadow m-1 p-3">
    <img class="icon-medium" title="SIRIUS" src="s.png">
    <img class="icon-tiny" title="Power Level" src="p.png">11
    <img class="icon-tiny" title="Trophies" src="t.png">1500
    <a data-bs-player-tag="#2QLLLGV0R0" href="#">SNK |camilacgs</a><hr>
  </div></div></div></div>
</div></body></html>"""


def test_parsear_showdown_de_trofeus():
    batalhas = brawlace.parsear_batalhas_html(HTML_SHOWDOWN, "#2QLLLGV0R0")
    b = batalhas[0]
    assert b["tipo"] == "TROPHIES"
    assert b["modo"] == "DUO SHOWDOWN"
    assert b["resultado"] == "Victory"
    assert b["trofeus_delta"] == 10
    assert b["mapa"] == "Truth"


def test_reparo_showdown_mal_parseado(tmp_path):
    con = db.conectar(tmp_path / "reparo.db")
    h = "cd34567890123456789012345678901234567890"
    con.execute("INSERT INTO batalhas (hash, ocorrida_em, modo, tipo, mapa) VALUES (?,?,?,?,?)",
                (h, "2026-07-17T00:00:00Z", "RANKED", "TROPHIES", "Truth"))
    con.execute("""INSERT INTO batalha_jogadores (hash, tag_jogador, resultado, trofeus_delta, star_player)
                   VALUES (?, '#X', 'RANK 2 - SOLO SHOWDOWN', 8, 0)""", (h,))
    con.commit(); con.close()
    con = db.conectar(tmp_path / "reparo.db")  # reconectar dispara o reparo
    b = con.execute("SELECT modo, tipo FROM batalhas WHERE hash=?", (h,)).fetchone()
    assert b["modo"] == "SOLO SHOWDOWN" and b["tipo"] == "TROPHIES"
    j = con.execute("SELECT resultado FROM batalha_jogadores WHERE hash=?", (h,)).fetchone()
    assert j["resultado"] == "Victory"  # delta +8
    con.close()


# ---------------------------------------------------------------------------
# Composições de time
# ---------------------------------------------------------------------------

def _linha_comp(hash_, resultado, aliado, eu, brawler, tag_j, nick="X"):
    return {**_linha(hash_, resultado, aliado, eu, brawler, tag_j, nick)}


def test_composicoes_do_jogador():
    linhas = []
    # 2 batalhas: eu (EMZ) + camila (JACKY) + bigboss (BROCK); 1V 1D
    for h, res in (("c1", "Victory"), ("c2", "Defeat")):
        linhas += [
            _linha_comp(h, res, 1, 1, "EMZ", TAG),
            _linha_comp(h, res, 1, 0, "JACKY", "#CAM", "camila"),
            _linha_comp(h, res, 1, 0, "BROCK", "#BIG", "bigboss"),
        ]
    comp = performance.composicoes_do_jogador(linhas, minimo=2)
    dupla = next(d for d in comp["duplas_brawlers"] if d["brawler_aliado"] == "JACKY")
    assert dupla["meu_brawler"] == "EMZ" and dupla["jogos"] == 2 and dupla["winrate"] == 50.0
    assert len(comp["trios_jogadores"]) == 1
    trio = comp["trios_jogadores"][0]
    assert trio["jogos"] == 2 and "camila" in trio["parceiros"] and "bigboss" in trio["parceiros"]


def test_composicoes_clube():
    linhas = []
    # time (hash t1, time 0): A+B vencem; (t2, time 0): A+B perdem; (t2, time 1): C+D vencem
    for h, time_, tags, res in (
        ("t1", 0, ("#A", "#B"), "Victory"),
        ("t2", 0, ("#A", "#B"), "Defeat"),
        ("t3", 0, ("#A", "#B"), "Victory"),
        ("t3", 1, ("#C", "#FORA"), "Defeat"),
    ):
        for tg in tags:
            linhas.append({"hash": h, "time": time_, "tag_jogador": tg,
                           "nick": tg.strip("#").lower(), "resultado": res})
    comp = performance.composicoes_clube(linhas, membros={"#A", "#B", "#C"}, minimo=2)
    assert len(comp["duplas"]) == 1                      # só A+B (C+FORA tem não-membro)
    ab = comp["duplas"][0]
    assert ab["jogos"] == 3 and ab["vitorias"] == 2 and ab["winrate"] == 66.7
    assert comp["trios"] == []


def test_wilson_premia_consistencia():
    from app.indicadores.performance import wilson
    assert wilson(30, 46) > wilson(3, 3)     # 65% em 46 > 100% em 3
    assert wilson(0, 0) == 0.0
    assert 0 <= wilson(5, 10) <= 0.5


# ---------------------------------------------------------------------------
# Picks personalizados (meta × desempenho do jogador)
# ---------------------------------------------------------------------------

def test_picks_personalizados_pesam_desempenho():
    from app.indicadores.meta import sugestoes_por_evento
    meta = {"modos": {"GEM GRAB": [
        {"posicao": 1, "brawler": "TOP_META", "star_player": 10, "star_player_pct": 12.0},
        {"posicao": 2, "brawler": "MEU_MAIN", "star_player": 8, "star_player_pct": 10.0},
        {"posicao": 3, "brawler": "NUNCA_JOGUEI", "star_player": 6, "star_player_pct": 8.0},
    ]}}
    eventos = [{"modo": "GEM GRAB", "mapa": "Gem Fort", "inicio": None, "fim": None}]
    brawlers = [
        {"nome": "TOP_META", "power": 11, "trofeus": 900},
        {"nome": "MEU_MAIN", "power": 11, "trofeus": 1100},
        {"nome": "NUNCA_JOGUEI", "power": 11, "trofeus": 500},
    ]
    # jogador domina MEU_MAIN (28V/32j) e vai mal de TOP_META (2V/10j) NO MODO
    batalhas = (
        [{"brawler": "MEU_MAIN", "resultado": "Victory", "modo": "GEM GRAB"}] * 28
        + [{"brawler": "MEU_MAIN", "resultado": "Defeat", "modo": "GEM GRAB"}] * 4
        + [{"brawler": "TOP_META", "resultado": "Victory", "modo": "GEM GRAB"}] * 2
        + [{"brawler": "TOP_META", "resultado": "Defeat", "modo": "GEM GRAB"}] * 8
    )
    sug = sugestoes_por_evento(meta, eventos, brawlers, batalhas)
    picks = sug[0]["picks"]
    assert picks[0]["brawler"] == "MEU_MAIN"        # desempenho vence o meta puro
    assert picks[0]["winrate_seu"] == 87.5
    nunca = next(p for p in picks if p["brawler"] == "NUNCA_JOGUEI")
    assert nunca["winrate_seu"] is None
    # longo prazo também é contado no desempenho do jogador
    lp = [{"brawler": "NUNCA_JOGUEI", "vitorias": 40, "derrotas": 10}]
    sug2 = sugestoes_por_evento(meta, eventos, brawlers, [], lp)
    nunca2 = next(p for p in sug2[0]["picks"] if p["brawler"] == "NUNCA_JOGUEI")
    assert nunca2["jogos_seus"] == 50 and nunca2["winrate_seu"] == 80.0
    # e um brawler com 80% de histórico pontua acima de outro sem histórico de mesma posição
    assert nunca2["score_pick"] > sugestoes_por_evento(
        meta, eventos, [{"nome": "NUNCA_JOGUEI", "power": 11, "trofeus": 500}], [], []
    )[0]["picks"][0]["score_pick"]


def test_distribuir_brawlers_sem_repetir():
    from app.indicadores.meta import distribuir_brawlers
    meta = {"modos": {"GEM GRAB": [
        {"posicao": 1, "brawler": "NORI", "star_player": 9, "star_player_pct": 11.0},
        {"posicao": 2, "brawler": "SURGE", "star_player": 8, "star_player_pct": 10.0},
        {"posicao": 3, "brawler": "EDGAR", "star_player": 7, "star_player_pct": 9.0},
    ]}}
    def jogador(nick, wr_nori, jogos=20):
        v = round(wr_nori * jogos)
        return {
            "tag": f"#{nick}", "nick": nick,
            "batalhas": ([{"brawler": "NORI", "resultado": "Victory", "modo": "GEM GRAB"}] * v
                         + [{"brawler": "NORI", "resultado": "Defeat", "modo": "GEM GRAB"}] * (jogos - v)),
            "historico_lp": [], "historico_modo": [],
            "powers": {"NORI": 11, "SURGE": 11, "EDGAR": 11},
        }
    # gustavo é o melhor de NORI (90%), eu 60%, camila 30%
    time_ = [jogador("eu", 0.6), jogador("gustavo", 0.9), jogador("camila", 0.3)]
    r = distribuir_brawlers(meta, "GEM GRAB", time_)
    assert r is not None
    brawlers = [a["brawler"] for a in r["atribuicao"]]
    assert len(set(brawlers)) == 3                       # sem repetição
    dono_nori = next(a for a in r["atribuicao"] if a["brawler"] == "NORI")
    assert dono_nori["nick"] == "gustavo"                # o melhor fica com ele
    pb = next(p for p in r["por_brawler"] if p["brawler"] == "NORI")
    assert pb["melhor"] == "gustavo" and pb["winrate_modo"] == 90.0


def test_distribuicao_respeita_tamanho_do_time():
    from app.indicadores.meta import distribuir_brawlers, tamanho_time_do_modo
    assert tamanho_time_do_modo("SOLO SHOWDOWN") == 1
    assert tamanho_time_do_modo("DUO SHOWDOWN") == 2
    assert tamanho_time_do_modo("GEM GRAB") == 3

    def jogador(nick, wr, modo, jogos=10):
        v = round(wr * jogos)
        return {"tag": f"#{nick}", "nick": nick,
                "batalhas": ([{"brawler": "NORI", "resultado": "Victory", "modo": modo}] * v
                             + [{"brawler": "NORI", "resultado": "Defeat", "modo": modo}] * (jogos - v)),
                "historico_lp": [], "historico_modo": [],
                "powers": {"NORI": 11, "SURGE": 11, "EDGAR": 11}}

    meta_duo = {"modos": {"DUO SHOWDOWN": [
        {"posicao": 1, "brawler": "NORI", "star_player": 9, "star_player_pct": 11.0},
        {"posicao": 2, "brawler": "SURGE", "star_player": 8, "star_player_pct": 10.0},
        {"posicao": 3, "brawler": "EDGAR", "star_player": 7, "star_player_pct": 9.0},
    ]}}
    time_ = [jogador("eu", 0.9, "DUO SHOWDOWN"), jogador("camila", 0.7, "DUO SHOWDOWN"),
             jogador("gustavo", 0.1, "DUO SHOWDOWN")]
    r = distribuir_brawlers(meta_duo, "DUO SHOWDOWN", time_)
    assert len(r["atribuicao"]) == 2                     # duo = 2 entram
    assert r["de_fora"] == ["gustavo"]                   # o pior fica de fora
    assert not r["individuais"]

    meta_solo = {"modos": {"SOLO SHOWDOWN": meta_duo["modos"]["DUO SHOWDOWN"]}}
    time_solo = [jogador("eu", 0.9, "SOLO SHOWDOWN"), jogador("camila", 0.8, "SOLO SHOWDOWN")]
    r2 = distribuir_brawlers(meta_solo, "SOLO SHOWDOWN", time_solo)
    assert len(r2["individuais"]) == 2
    # solo pode repetir: os dois podem pegar NORI
    assert {a["brawler"] for a in r2["individuais"]} == {"NORI"}


# ---------------------------------------------------------------------------
# Score v2: meta do mapa (brawltime), kit e proximidade de troféus
# ---------------------------------------------------------------------------

FIXTURE_MAPA = Path(__file__).parent / "fixtures" / "brawltime_mapa_gem_fort_2026-07-17.html"


def test_parsear_meta_mapa_brawltime():
    from app.coleta.brawltime import parsear_meta_mapa
    r = parsear_meta_mapa(FIXTURE_MAPA.read_text(encoding="utf-8"))
    assert r["brawlers"]["NORI"] == 81.9
    assert r["brawlers"]["R-T"] == 73.0
    assert len(r["brawlers"]) == 10
    assert r["times"][0] == {"brawlers": ["EDGAR", "GRIFF", "KENJI"], "vitorias": 350}
    assert len(r["times"]) == 10


def test_parser_brawlers_kit(perfil):
    shelly = next(b for b in perfil["brawlers"] if b["nome"] == "SHELLY")
    assert shelly["hypercharge"] == 1 and shelly["star_powers"] == 2
    assert shelly["gadgets"] == 2 and shelly["gears"] == 2


def test_score_v2_usa_mapa_e_kit():
    from app.indicadores.meta import sugestoes_por_evento
    meta = {"modos": {"GEM GRAB": [
        {"posicao": 1, "brawler": "FORTE_NO_MODO", "star_player": 9, "star_player_pct": 11.0},
        {"posicao": 2, "brawler": "FORTE_NO_MAPA", "star_player": 8, "star_player_pct": 10.0},
    ]}}
    eventos = [{"modo": "GEM GRAB", "mapa": "Gem Fort", "inicio": None, "fim": None}]
    brawlers = [
        {"nome": "FORTE_NO_MODO", "power": 11, "trofeus": 800,
         "star_powers": 0, "gadgets": 0, "hypercharge": 0},
        {"nome": "FORTE_NO_MAPA", "power": 11, "trofeus": 800,
         "star_powers": 2, "gadgets": 2, "hypercharge": 1},
    ]
    stats_mapas = {("GEM GRAB", "Gem Fort"): {
        "brawlers": {"FORTE_NO_MAPA": 82.0, "FORTE_NO_MODO": 45.0}, "times": []}}
    sug = sugestoes_por_evento(meta, eventos, brawlers, [], None, None, stats_mapas)
    picks = sug[0]["picks"]
    # mapa (82% vs 45%) + kit completo devem virar o jogo contra a posição do modo
    assert picks[0]["brawler"] == "FORTE_NO_MAPA"
    assert picks[0]["wr_mapa_global"] == 82.0


def test_distribuicao_penaliza_trofeus_distantes():
    from app.indicadores.meta import distribuir_brawlers
    meta = {"modos": {"DUO SHOWDOWN": [
        {"posicao": 1, "brawler": "A", "star_player": 9, "star_player_pct": 10.0},
        {"posicao": 1, "brawler": "B", "star_player": 9, "star_player_pct": 10.0},
        {"posicao": 1, "brawler": "C", "star_player": 9, "star_player_pct": 10.0},
    ]}}
    def jog(nick, trofeus_b):
        return {"tag": f"#{nick}", "nick": nick, "batalhas": [],
                "historico_lp": [], "historico_modo": [],
                "powers": {"A": 11, "B": 11, "C": 11},
                "kits": {}, "trofeus_brawler": trofeus_b}
    # sem histórico e mesmo meta: decide a proximidade de troféus
    time_ = [jog("eu", {"A": 1000, "B": 500, "C": 980}),
             jog("par", {"A": 990, "B": 1000, "C": 400})]
    r = distribuir_brawlers(meta, "DUO SHOWDOWN", time_)
    pares = {a["nick"]: a["brawler"] for a in r["atribuicao"]}
    # melhor par próximo: eu=A(1000)+par=B(1000) ou eu=C(980)+par=A(990) etc — nunca B(500) do eu com A(990)
    trof = {"eu": time_[0]["trofeus_brawler"][pares["eu"]],
            "par": time_[1]["trofeus_brawler"][pares["par"]]}
    assert abs(trof["eu"] - trof["par"]) <= 100


def test_rank_showdown_gravado_e_exibido(tmp_path):
    batalhas = brawlace.parsear_batalhas_html(HTML_SHOWDOWN, "#2QLLLGV0R0")
    assert batalhas[0]["rank_showdown"] == 2
    con = db.conectar(tmp_path / "rank.db")
    db.salvar_batalhas(con, "#2QLLLGV0R0", batalhas)
    con.commit()
    b = db.batalhas_do_jogador(con, "#2QLLLGV0R0")[0]
    assert b["rank"] == 2 and b["resultado"] == "Victory"
    con.close()


# ---------------------------------------------------------------------------
# 5ª fonte: brawlytix (conta)
# ---------------------------------------------------------------------------

def test_parsear_conta_brawlytix():
    from app.coleta.brawlytix import parsear_conta
    html = (Path(__file__).parent / "fixtures" / "brawlytix_299PGGLQL_2026-07-17.html").read_text(encoding="utf-8")
    c = parsear_conta(html)
    assert c["skill_score"] == 4.3 and c["skill_rotulo"] == "Average"
    assert c["valor_conta"] == 408626
    assert c["horas_jogadas"] == 924
    assert c["elo_ranked"] == 750 and c["elo_ranked_recorde"] == 6331
    assert c["stats"]["Coins to Maxed"] == 588765
    assert c["stats"]["Fame Rank"] == "Alien 1"
    assert c["stats"]["Brawlers Unlocked"] == "104/105"
    assert len(c["stats"]) == 42


def test_parsear_conta_vazia():
    from app.coleta.brawlytix import parsear_conta
    assert parsear_conta("<html><body>nada</body></html>") is None


# ---------------------------------------------------------------------------
# Reset de temporada + pendências de histórico externo
# ---------------------------------------------------------------------------

def test_detectar_reset_de_temporada():
    from app.indicadores.performance import detectar_resets
    snaps = [
        {"criado_em": "2026-07-10T00:00:00", "trofeus": 70000},
        {"criado_em": "2026-07-11T00:00:00", "trofeus": 67200},  # caiu 2800
        {"criado_em": "2026-07-12T00:00:00", "trofeus": 67300},  # subiu 100 normal
    ]
    batalhas = [
        {"ocorrida_em": "2026-07-10T12:00:00", "trofeus_delta": -8},
        {"ocorrida_em": "2026-07-10T13:00:00", "trofeus_delta": -12},
        {"ocorrida_em": "2026-07-11T12:00:00", "trofeus_delta": 100},
    ]
    resets = detectar_resets(snaps, batalhas)
    assert len(resets) == 1
    r = resets[0]
    assert r["entre"] == "2026-07-10" and r["queda"] == 2780
    # sem queda inexplicada → nada
    assert detectar_resets(snaps[1:], batalhas) == []


def test_tags_sem_historico_externo(conexao, perfil):
    db.salvar_consulta(conexao, perfil)  # dono consultado, SEM historico_diario
    pend = db.tags_sem_historico_externo(conexao)
    assert TAG in [p["tag"] for p in pend]
    # após importar histórico, sai da lista
    conexao.execute(
        "INSERT INTO historico_diario (tag, data, batalhas, vitorias, derrotas,"
        " trofeus_delta, trofeus_fim, brawlers_json) VALUES (?, '2026-07-01', 5, 3, 2, 10, 1000, '[]')",
        (TAG,),
    )
    conexao.commit()
    assert TAG not in [p["tag"] for p in db.tags_sem_historico_externo(conexao)]


# ---------------------------------------------------------------------------
# Acessórios: parser do brawltime + posse do brawlace + cruzamento
# ---------------------------------------------------------------------------

def test_parsear_acessorios_brawler():
    from app.coleta.brawltime import parsear_acessorios_brawler
    html = (Path(__file__).parent / "fixtures" / "brawltime_brawler_emz_2026-07-17.html").read_text(encoding="utf-8")
    a = parsear_acessorios_brawler(html)
    assert a["star_power"]["melhor"] == "Hype" and a["star_power"]["winrate"] == 64.0
    assert a["gadget"]["melhor"] == "Friendzoner" and a["gadget"]["winrate"] == 63.4
    assert a["gear"]["melhor"] == "Shield"


def test_brawlace_extrai_nomes_acessorios(perfil):
    shelly = next(b for b in perfil["brawlers"] if b["nome"] == "SHELLY")
    assert "SHELL SHOCK" in shelly["star_powers_nomes"]
    assert "FAST FORWARD" in shelly["gadgets_nomes"]
    assert "DAMAGE" in shelly["gears_nomes"]


def test_cruzar_acessorios():
    from app.indicadores.meta import cruzar_acessorios
    brawler = {"nome": "EMZ", "hypercharge": 1,
               "star_powers_nomes": ["BAD KARMA", "HYPE"],
               "gadgets_nomes": ["FRIENDZONER"], "gears_nomes": ["SHIELD"]}
    meta = {"star_power": {"melhor": "Hype", "winrate": 64.0},
            "gadget": {"melhor": "Acid Spray", "winrate": 62.0},
            "gear": {"melhor": "Shield", "winrate": 63.4}}
    r = cruzar_acessorios(brawler, meta)
    assert r["star_power"]["possui_recomendado"] is True    # tem Hype
    assert r["star_power"]["equipar"] == "Hype"
    assert r["gadget"]["possui_recomendado"] is False       # não tem Acid Spray
    assert r["gadget"]["equipar"] == "FRIENDZONER"          # equipa o que tem
    assert r["hypercharge"] is True
    assert cruzar_acessorios(None, meta) is None


# ---------------------------------------------------------------------------
# Correções da revisão holística (17/07/2026)
# ---------------------------------------------------------------------------

def test_fator_meta_v2_escala_correta():
    from app.indicadores.meta import _fator_meta_v2
    # 1º lugar sem mapa deve valer ~1.0 (não 0.01); 8º de 10 ~0.3
    assert _fator_meta_v2(1, 10, None) == 1.0
    assert 0.25 < _fator_meta_v2(8, 10, None) < 0.35
    # com mapa: mistura 60/40, valor razoável (não saturado em 0.6)
    v = _fator_meta_v2(1, 10, 82.0)
    assert 0.7 < v <= 1.0


def test_coletar_acessorios_nao_quebra():
    # antes faltava import re → NameError; agora slug funciona e falha vira None
    from app.coleta import brawltime
    assert brawltime._slug_brawler("MR. P") == "mr-p"
    assert brawltime._slug_brawler("8-BIT") == "8-bit"
    assert brawltime._slug_brawler("LARRY & LAWRIE") == "larry-lawrie"


def test_migracao_resumivel(tmp_path):
    """Se a migração for interrompida (tabelas *_antigas órfãs), a reconexão
    completa a cópia sem perder dados."""
    import sqlite3 as s3
    caminho = tmp_path / "interrompida.db"
    con = s3.connect(caminho)
    con.row_factory = s3.Row
    # simula estado pós-crash: schema novo + batalhas_antigas órfã (não copiada)
    con.executescript(db._SCHEMA)
    con.executescript("""
        CREATE TABLE batalhas_antigas (
          hash TEXT PRIMARY KEY, tag TEXT, ocorrida_em TEXT, modo TEXT, tipo TEXT,
          mapa TEXT, brawler TEXT, resultado TEXT, duracao_seg INTEGER,
          trofeus_delta INTEGER, star_player INTEGER);
        INSERT INTO batalhas_antigas VALUES
          ('f'||substr('0000000000000000000000000000000000000000',1,39),
           '#Z', '2026-07-01T00:00:00Z', 'GEM GRAB', 'TROPHIES', 'M', 'EMZ',
           'Victory', 100, 8, 1);
    """)
    con.commit(); con.close()
    con = db.conectar(caminho)  # deve RESUMIR a migração
    assert not db._tabela_existe(con, "batalhas_antigas")  # concluída
    b = db.batalhas_do_jogador(con, "#Z")
    assert len(b) == 1 and b[0]["resultado"] == "Victory"
    con.close()


def test_showdown_solo_sem_victory_infere_pelo_delta():
    html = """<html><body>
    <div id="ef34567890123456789012345678901234567890">
      <div class="card-header">RANKED | RANK 2 - SOLO SHOWDOWN |  +8 | 01:20 |
        <time datetime="2026-07-17T13:00:00Z">now</time></div>
      <div class="card-body"><div class="row"><div class="col-md-6"><div class="shadow m-1 p-3">
        <img class="icon-medium" title="EMZ"><a data-bs-player-tag="#S1" href="#">eu</a><hr>
      </div></div></div></div>
    </div></body></html>"""
    b = brawlace.parsear_batalhas_html(html, "#S1")[0]
    assert b["modo"] == "SOLO SHOWDOWN" and b["rank_showdown"] == 2
    assert b["resultado"] == "Victory"      # inferido do +8
    assert b["trofeus_delta"] == 8 and b["duracao_seg"] == 80
