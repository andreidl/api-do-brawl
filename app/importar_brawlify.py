"""Importação ÚNICA do histórico do Brawlify (245 dias, coletado manualmente
em 17/07/2026 via navegador — Brawlify é protegido por Cloudflare, então a
coleta foi feita com o usuário passando o security check; ver CLAUDE.md §3.6).

Entrada: JSONs em dados_brawlify/ no formato {"data": "YYYY-MM-DD", "txt": "..."}
onde txt é o innerText do card diário separado por '|'.

Rodar: python -m app.importar_brawlify <pasta_com_jsons> [#TAG] [DATA=TROFEUS]
  ex.: python -m app.importar_brawlify dados_brawlify_camila "#2QLLLGV0R0" 2026-07-17=51673
Sem argumentos extras usa a tag/âncora do dono do projeto (compatível com o import original).
"""
import json
import re
import sys
from pathlib import Path

from app import db

FONTE: str = "brawlify"
TAG_USUARIO: str = "#299PGGLQL"
# Âncora para reconstruir troféus absolutos: troféus no FIM do último dia importado
TROFEUS_FIM_ULTIMO_DIA: dict[str, int] = {"2026-07-17": 73118}

_SCHEMA_HISTORICO: str = """
CREATE TABLE IF NOT EXISTS historico_diario (
  tag TEXT, data TEXT, batalhas INTEGER, vitorias INTEGER, derrotas INTEGER,
  trofeus_delta INTEGER, trofeus_fim INTEGER, brawlers_json TEXT,
  fonte TEXT DEFAULT 'brawlify',
  PRIMARY KEY (tag, data)
);
CREATE TABLE IF NOT EXISTS historico_brawler (
  tag TEXT, brawler TEXT, jogos INTEGER, winrate_pct REAL, trofeus_delta INTEGER,
  fonte TEXT DEFAULT 'brawlify',
  PRIMARY KEY (tag, brawler, fonte)
);
"""

_RE_BATALHAS = re.compile(r"\|(\d+) battles\|")
_RE_WINS = re.compile(r"\|(\d+)\|Wins\|(\d+)\|Losses\|")
_RE_DELTA = re.compile(r"battles(?:\|[+-]?\d+[WL]){0,2}\|([+-]\d+)\|")
_RE_BRAWLER = re.compile(r"\|([A-Z0-9ÁÉÍÓÚÜÑ&.\-' ]+?)\|(\d+)x\|([+-]?\d+)")
_RE_MILESTONE = re.compile(r"Trophy Milestone\|([\d,.]+) Trophies")


def parsear_card(data: str, txt: str) -> dict:
    """Extrai batalhas/vitórias/derrotas/delta e a lista de brawlers do dia."""
    m_bat = _RE_BATALHAS.search(txt)
    m_wl = _RE_WINS.search(txt)
    if not m_bat or not m_wl:
        raise ValueError(f"{data}: card sem batalhas/W-L: {txt[:80]}")
    m_delta = _RE_DELTA.search(txt)

    pos_jogados = txt.find("Brawlers Played")
    brawlers: list[dict] = []
    if pos_jogados >= 0:
        for m in _RE_BRAWLER.finditer(txt[pos_jogados:]):
            brawlers.append({
                "brawler": m.group(1).strip(),
                "jogos": int(m.group(2)),
                "trofeus_delta": int(m.group(3)),
            })
    return {
        "data": data,
        "batalhas": int(m_bat.group(1)),
        "vitorias": int(m_wl.group(1)),
        "derrotas": int(m_wl.group(2)),
        "trofeus_delta": int(m_delta.group(1)) if m_delta else 0,
        "brawlers": brawlers,
        # troféus absolutos no fim do dia, quando o card traz o milestone —
        # âncora intermediária essencial quando há gaps de rastreamento
        "milestone": (
            int(m_mi.group(1).replace(",", "").replace(".", ""))
            if (m_mi := _RE_MILESTONE.search(txt)) else None
        ),
    }


def _reconstruir_trofeus_fim(dias: list[dict], ancora: dict[str, int] | None = None) -> None:
    """Troféus absolutos no fim de cada dia, andando para trás da âncora.

    Além da âncora externa, cada card com "Trophy Milestone" re-ancora o valor
    absoluto naquele dia — crucial quando há gaps de rastreamento (troféus
    ganhos em dias não rastreados não aparecem nos deltas).
    """
    dias.sort(key=lambda d: d["data"])
    ancora_data, ancora_valor = next(iter((ancora or TROFEUS_FIM_ULTIMO_DIA).items()))
    valor: int | None = None
    for dia in reversed(dias):
        if dia["data"] == ancora_data:
            valor = ancora_valor
        elif dia.get("milestone") is not None:
            valor = dia["milestone"]
        if valor is None:
            dia["trofeus_fim"] = None
            continue
        dia["trofeus_fim"] = valor
        valor -= dia["trofeus_delta"]


_RE_WL_TOTAL = re.compile(r"^(\d+)([WLD])$")
_RE_NUMERO = re.compile(r"^[+-]?\d+$")


def parsear_card_brawler(txt: str) -> dict | None:
    """Card da página /player/TAG/brawlers do Brawlify:
    'NOME|P11|RARIDADE|·|TIER|trofeus|...|BATTLES|52W|42L|[1D]|MODO|delta|v|d|[e]|...|LAST PLAYED|...'
    Retorna None para brawler sem batalhas no período rastreado."""
    partes: list[str] = [p.strip() for p in txt.split("|") if p.strip()]
    if not partes or "BATTLES" not in partes:
        return None
    nome: str = partes[0]

    i: int = partes.index("BATTLES") + 1
    vitorias = derrotas = empates = 0
    while i < len(partes):
        m = _RE_WL_TOTAL.match(partes[i])
        if not m:
            break
        valor, tipo = int(m.group(1)), m.group(2)
        if tipo == "W":
            vitorias = valor
        elif tipo == "L":
            derrotas = valor
        else:
            empates = valor
        i += 1

    modos: list[dict] = []
    atual: dict | None = None
    while i < len(partes) and partes[i] != "LAST PLAYED":
        parte: str = partes[i]
        if _RE_NUMERO.match(parte):
            if atual is not None:
                atual["numeros"].append(int(parte))
        else:
            if atual is not None:
                modos.append(atual)
            atual = {"modo": parte, "numeros": []}
        i += 1
    if atual is not None:
        modos.append(atual)

    lista_modos: list[dict] = []
    for m in modos:
        numeros: list[int] = m["numeros"]
        if len(numeros) < 3:
            continue  # linha de modo incompleta — ignora
        lista_modos.append({
            "modo": m["modo"],
            "trofeus_delta": numeros[0],
            "vitorias": numeros[1],
            "derrotas": numeros[2],
            "empates": numeros[3] if len(numeros) > 3 else 0,
        })
    return {
        "brawler": nome,
        "vitorias": vitorias,
        "derrotas": derrotas,
        "empates": empates,
        "trofeus_delta": sum(x["trofeus_delta"] for x in lista_modos),
        "modos": lista_modos,
    }


def _tem_coluna(conexao, tabela: str, coluna: str) -> bool:
    return any(
        linha[1] == coluna
        for linha in conexao.execute(f"PRAGMA table_info({tabela})").fetchall()
    )


def importar_brawlers(conexao, pasta: Path, tag: str = TAG_USUARIO) -> int:
    """Importa brawlers_cards.json → historico_brawler + historico_brawler_modo.

    Rebuild APENAS das linhas da tag importada — dados de outras tags ficam
    intactos (antes fazia DROP TABLE e apagava tudo).
    """
    arquivo = pasta / "brawlers_cards.json"
    if not arquivo.exists():
        return 0
    cards: list[str] = json.loads(arquivo.read_text(encoding="utf-8"))
    conexao.executescript("""
        CREATE TABLE IF NOT EXISTS historico_brawler (
          tag TEXT, brawler TEXT, jogos INTEGER, vitorias INTEGER, derrotas INTEGER,
          empates INTEGER, winrate_pct REAL, trofeus_delta INTEGER,
          fonte TEXT DEFAULT 'brawlify',
          PRIMARY KEY (tag, brawler, fonte)
        );
        CREATE TABLE IF NOT EXISTS historico_brawler_modo (
          tag TEXT, brawler TEXT, modo TEXT, vitorias INTEGER, derrotas INTEGER,
          empates INTEGER, trofeus_delta INTEGER,
          PRIMARY KEY (tag, brawler, modo)
        );
    """)
    # migra schema antigo (sem colunas vitorias/derrotas) — aí sim rebuild total
    if not _tem_coluna(conexao, "historico_brawler", "vitorias"):
        conexao.executescript(
            "DROP TABLE historico_brawler; DROP TABLE IF EXISTS historico_brawler_modo;"
        )
        return importar_brawlers(conexao, pasta, tag)
    conexao.execute("DELETE FROM historico_brawler WHERE tag = ?", (tag,))
    conexao.execute("DELETE FROM historico_brawler_modo WHERE tag = ?", (tag,))
    importados: int = 0
    for txt in cards:
        card = parsear_card_brawler(txt)
        if card is None:
            continue
        decididas: int = card["vitorias"] + card["derrotas"]
        winrate: float | None = (
            round(card["vitorias"] / decididas * 100, 1) if decididas else None
        )
        conexao.execute(
            """INSERT OR REPLACE INTO historico_brawler
               (tag, brawler, jogos, vitorias, derrotas, empates, winrate_pct,
                trofeus_delta, fonte)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (tag, card["brawler"],
             card["vitorias"] + card["derrotas"] + card["empates"],
             card["vitorias"], card["derrotas"], card["empates"],
             winrate, card["trofeus_delta"], FONTE),
        )
        for m in card["modos"]:
            conexao.execute(
                """INSERT OR REPLACE INTO historico_brawler_modo
                   (tag, brawler, modo, vitorias, derrotas, empates, trofeus_delta)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (tag, card["brawler"], m["modo"], m["vitorias"],
                 m["derrotas"], m["empates"], m["trofeus_delta"]),
            )
        importados += 1
    conexao.commit()
    return importados


def importar(pasta: Path, tag: str = TAG_USUARIO,
             ancora: dict[str, int] | None = None) -> None:
    arquivos = sorted(pasta.glob("2*.json"))
    if not arquivos:
        raise SystemExit(f"nenhum JSON 2*.json em {pasta}")

    dias: list[dict] = []
    for arquivo in arquivos:
        for card in json.loads(arquivo.read_text(encoding="utf-8")):
            try:
                dias.append(parsear_card(card["data"], card["txt"]))
            except ValueError:
                print(f"aviso: {card['data']} sem batalhas (so unlocks) - pulado")
    _reconstruir_trofeus_fim(dias, ancora)

    conexao = db.conectar()
    conexao.executescript(_SCHEMA_HISTORICO)
    for dia in dias:
        conexao.execute(
            """INSERT OR REPLACE INTO historico_diario
               (tag, data, batalhas, vitorias, derrotas, trofeus_delta,
                trofeus_fim, brawlers_json, fonte)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (tag, dia["data"], dia["batalhas"], dia["vitorias"],
             dia["derrotas"], dia["trofeus_delta"], dia["trofeus_fim"],
             json.dumps(dia["brawlers"], ensure_ascii=False), FONTE),
        )

    # brawlers_cards.json (todos os brawlers, com V/D por modo) substitui o
    # antigo agregados.json (só top 8)
    n_brawlers: int = importar_brawlers(conexao, pasta, tag)
    if n_brawlers:
        print(f"Brawlers com batalhas no periodo: {n_brawlers}")
    conexao.commit()

    total_b = sum(d["batalhas"] for d in dias)
    total_v = sum(d["vitorias"] for d in dias)
    total_d = sum(d["derrotas"] for d in dias)
    print(f"Importados {len(dias)} dias: {total_b} batalhas, "
          f"{total_v}V/{total_d}D ({total_v / (total_v + total_d) * 100:.0f}%)")
    print(f"Periodo: {dias[0]['data']} -> {dias[-1]['data']}")
    conexao.close()


if __name__ == "__main__":
    pasta_arg = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("dados_brawlify")
    tag_arg: str = sys.argv[2] if len(sys.argv) > 2 else TAG_USUARIO
    ancora_arg: dict[str, int] | None = None
    if len(sys.argv) > 3:
        data_ancora, _, valor_ancora = sys.argv[3].partition("=")
        ancora_arg = {data_ancora: int(valor_ancora)}
    importar(pasta_arg, tag_arg, ancora_arg)
