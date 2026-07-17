"""Testes dos indicadores de performance (app/indicadores/performance.py)."""
from app.indicadores import performance


def _batalha(modo: str, brawler: str, resultado: str) -> dict:
    return {"modo": modo, "brawler": brawler, "resultado": resultado}


BATALHAS: list[dict] = (
    [_batalha("HOT ZONE", "EMZ", "Victory")] * 6
    + [_batalha("HOT ZONE", "EMZ", "Defeat")] * 4
    + [_batalha("BRAWL BALL", "JACKY", "Victory")] * 3
    + [_batalha("BRAWL BALL", "JACKY", "Defeat")] * 7
    + [_batalha("SOLO SHOWDOWN", "LEON", "Rank 3")]  # fora do winrate
    + [_batalha("GEM GRAB", "BO", "Draw")]           # fora do winrate
)

BRAWLERS: list[dict] = [
    {"nome": "EMZ", "trofeus": 900, "trofeus_max": 1000},
    {"nome": "JACKY", "trofeus": 1090, "trofeus_max": 1090},   # sem queda
    {"nome": "NOVATO", "trofeus": 10, "trofeus_max": 50},      # pico < 100, ignora
]

SNAPSHOTS: list[dict] = [
    {"criado_em": "2026-07-17T10:00:00+00:00", "trofeus": 73000},
    {"criado_em": "2026-07-17T22:00:00+00:00", "trofeus": 73118},  # mesmo dia, vale o último
    {"criado_em": "2026-07-18T10:00:00+00:00", "trofeus": 73300},
]


def test_winrate_geral_exclui_draw_e_showdown():
    ind = performance.calcular_indicadores(BATALHAS, [], [])
    assert ind["partidas"] == 22
    assert ind["partidas_decididas"] == 20
    assert ind["winrate_geral"] == 45.0  # 9 vitórias / 20 decididas


def test_winrate_por_modo():
    ind = performance.calcular_indicadores(BATALHAS, [], [])
    modos = {m["nome"]: m for m in ind["por_modo"]}
    assert modos["HOT ZONE"]["winrate"] == 60.0
    assert modos["BRAWL BALL"]["winrate"] == 30.0
    assert "SOLO SHOWDOWN" not in modos  # sem partidas decididas


def test_por_brawler_com_uso():
    ind = performance.calcular_indicadores(BATALHAS, [], [])
    emz = next(b for b in ind["por_brawler"] if b["nome"] == "EMZ")
    assert emz["partidas"] == 10
    assert emz["uso_pct"] == 50.0
    assert emz["winrate"] == 60.0


def test_amostra_pequena():
    poucas = BATALHAS[:5]
    assert performance.calcular_indicadores(poucas, [], [])["amostra_pequena"] is True
    assert performance.calcular_indicadores(BATALHAS, [], [])["amostra_pequena"] is False


def test_queda_trofeus():
    ind = performance.calcular_indicadores([], BRAWLERS, [])
    assert len(ind["queda_trofeus"]) == 1
    queda = ind["queda_trofeus"][0]
    assert queda["nome"] == "EMZ"
    assert queda["queda"] == 100
    assert queda["queda_pct"] == 10.0


def test_evolucao_um_ponto_por_dia():
    ind = performance.calcular_indicadores([], [], SNAPSHOTS)
    assert ind["evolucao"] == [
        {"dia": "2026-07-17", "trofeus": 73118},
        {"dia": "2026-07-18", "trofeus": 73300},
    ]


def test_tudo_vazio_nao_quebra():
    ind = performance.calcular_indicadores([], [], [])
    assert ind["winrate_geral"] is None
    assert ind["por_modo"] == []
    assert ind["evolucao"] == []
    assert ind["amostra_pequena"] is True
