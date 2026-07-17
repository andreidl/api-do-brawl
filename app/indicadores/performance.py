"""Indicadores de performance (parte 2) — calculados sobre o histórico
ACUMULADO de batalhas do SQLite, não só as 25 do site (CLAUDE.md §4).

Winrate = vitórias / (vitórias + derrotas). Draws e resultados de showdown
('Rank N') ficam fora do denominador.
"""
import pandas as pd

LIMIAR_AMOSTRA_PEQUENA: int = 20


def calcular_indicadores(
    batalhas: list[dict],
    brawlers: list[dict],
    snapshots: list[dict],
    historico_diario: list[dict] | None = None,
) -> dict:
    """Recebe o histórico do banco e devolve todos os KPIs prontos para exibir."""
    df = pd.DataFrame(batalhas)
    decididas = (
        df[df["resultado"].isin(["Victory", "Defeat"])]
        if not df.empty else pd.DataFrame()
    )
    return {
        "partidas": int(len(df)),
        "partidas_decididas": int(len(decididas)),
        "amostra_pequena": len(decididas) < LIMIAR_AMOSTRA_PEQUENA,
        "winrate_geral": _winrate(decididas),
        "por_modo": _agrupado(decididas, "modo"),
        "por_brawler": _agrupado(decididas, "brawler"),
        "queda_trofeus": _queda_trofeus(brawlers),
        "evolucao": _evolucao(snapshots),
        "resets_temporada": detectar_resets(snapshots, batalhas),
        "longo_prazo": _longo_prazo(historico_diario or []),
    }


def _longo_prazo(historico: list[dict]) -> dict | None:
    """Agregados do histórico diário importado do Brawlify (245 dias)."""
    if not historico:
        return None
    vitorias: int = sum(d["vitorias"] for d in historico)
    derrotas: int = sum(d["derrotas"] for d in historico)
    decididas: int = vitorias + derrotas
    return {
        "dias_jogados": len(historico),
        "batalhas": sum(d["batalhas"] for d in historico),
        "vitorias": vitorias,
        "derrotas": derrotas,
        "winrate": round(vitorias / decididas * 100, 1) if decididas else None,
        "trofeus_delta": sum(d["trofeus_delta"] for d in historico),
        "inicio": historico[0]["data"],
        "fim": historico[-1]["data"],
        "evolucao": [
            {"dia": d["data"], "trofeus": d["trofeus_fim"]}
            for d in historico if d.get("trofeus_fim")
        ],
    }


def _winrate(decididas: pd.DataFrame) -> float | None:
    if decididas.empty:
        return None
    return round(float((decididas["resultado"] == "Victory").mean()) * 100, 1)


def _agrupado(decididas: pd.DataFrame, coluna: str) -> list[dict]:
    """Winrate e uso agrupados por modo ou por brawler, mais jogados primeiro."""
    if decididas.empty:
        return []
    grupos = decididas.groupby(coluna)["resultado"].agg(
        partidas="count", vitorias=lambda r: int((r == "Victory").sum())
    ).reset_index()
    grupos["winrate"] = (grupos["vitorias"] / grupos["partidas"] * 100).round(1)
    grupos["uso_pct"] = (grupos["partidas"] / len(decididas) * 100).round(1)
    grupos = grupos.sort_values(["partidas", "winrate"], ascending=False)
    return grupos.rename(columns={coluna: "nome"}).to_dict("records")


def _queda_trofeus(brawlers: list[dict], minimo_max: int = 100) -> list[dict]:
    """Brawlers mais distantes do próprio pico — candidatos a recuperar troféus."""
    quedas: list[dict] = []
    for b in brawlers:
        if b["trofeus_max"] < minimo_max:
            continue
        queda: int = b["trofeus_max"] - b["trofeus"]
        if queda <= 0:
            continue
        quedas.append({
            "nome": b["nome"],
            "trofeus": b["trofeus"],
            "trofeus_max": b["trofeus_max"],
            "queda": queda,
            "queda_pct": round(queda / b["trofeus_max"] * 100, 1),
        })
    quedas.sort(key=lambda q: q["queda"], reverse=True)
    return quedas[:10]


def _evolucao(snapshots: list[dict]) -> list[dict]:
    """Série temporal de troféus (1 ponto por dia — o último snapshot do dia)."""
    if not snapshots:
        return []
    df = pd.DataFrame(snapshots)[["criado_em", "trofeus"]].dropna()
    df["dia"] = df["criado_em"].str[:10]
    diario = df.groupby("dia").last().reset_index()
    return diario[["dia", "trofeus"]].to_dict("records")


# ---------------------------------------------------------------------------
# Social: matchups (inimigos) e parceiros (aliados) — usa batalha_jogadores
# ---------------------------------------------------------------------------

MINIMO_JOGOS_MATCHUP: int = 2


def social(jogadores: list[dict]) -> dict:
    """Matchups contra brawlers inimigos e winrate com cada parceiro.

    `jogadores`: linhas de db.jogadores_das_batalhas (participante + resultado
    da batalha do ponto de vista do dono da consulta).
    """
    df = pd.DataFrame(jogadores)
    if df.empty:
        return {"matchups": [], "parceiros": [], "batalhas_cobertas": 0}
    df = df[df["resultado"].isin(["Victory", "Defeat"])]
    if df.empty:
        return {"matchups": [], "parceiros": [], "batalhas_cobertas": 0}
    df["vitoria"] = (df["resultado"] == "Victory").astype(int)

    inimigos = df[(df["aliado"] == 0) & df["brawler"].notna()]
    matchups: list[dict] = []
    if not inimigos.empty:
        grupo = inimigos.groupby("brawler").agg(
            jogos=("hash", "nunique"),
            vitorias=("vitoria", "sum"),
            enfrentados=("hash", "size"),
        )
        # winrate POR BATALHA (uma batalha pode ter o mesmo brawler 2x no time inimigo)
        por_batalha = inimigos.drop_duplicates(["hash", "brawler"])
        g2 = por_batalha.groupby("brawler").agg(
            jogos=("hash", "size"), vitorias=("vitoria", "sum")
        )
        g2 = g2[g2["jogos"] >= MINIMO_JOGOS_MATCHUP]
        for brawler, linha in g2.iterrows():
            matchups.append({
                "brawler": str(brawler),
                "jogos": int(linha["jogos"]),
                "vitorias": int(linha["vitorias"]),
                "winrate": round(linha["vitorias"] / linha["jogos"] * 100, 1),
            })
        matchups.sort(key=lambda m: -wilson(m["jogos"] - m["vitorias"], m["jogos"]))

    aliados = df[(df["aliado"] == 1) & (df["eu"] == 0)]
    parceiros: list[dict] = []
    if not aliados.empty:
        por_batalha = aliados.drop_duplicates(["hash", "tag_jogador"])
        g = por_batalha.groupby("tag_jogador").agg(
            jogos=("hash", "size"), vitorias=("vitoria", "sum"),
            nick=("nick", "last"),
        )
        g = g[g["jogos"] >= MINIMO_JOGOS_MATCHUP]
        for tag_p, linha in g.iterrows():
            parceiros.append({
                "tag": str(tag_p),
                "nick": str(linha["nick"]),
                "jogos": int(linha["jogos"]),
                "vitorias": int(linha["vitorias"]),
                "winrate": round(linha["vitorias"] / linha["jogos"] * 100, 1),
            })
        parceiros.sort(key=lambda p: -wilson(p["vitorias"], p["jogos"]))

    return {
        "matchups": matchups,
        "parceiros": parceiros,
        "batalhas_cobertas": int(df["hash"].nunique()),
    }


def star_player(batalhas: list[dict]) -> dict | None:
    """Taxa de Star Player: geral, por brawler e por modo (3v3 decididas)."""
    df = pd.DataFrame(batalhas)
    if df.empty:
        return None
    df = df[df["resultado"].isin(["Victory", "Defeat"])]  # showdown não tem star
    if df.empty:
        return None
    total: int = len(df)
    stars: int = int(df["star_player"].sum())

    def _taxa(grupo_col: str) -> list[dict]:
        g = df.groupby(grupo_col).agg(jogos=("hash", "size"), stars=("star_player", "sum"))
        g = g[g["jogos"] >= 3]
        linhas = [
            {"nome": str(nome), "jogos": int(l["jogos"]), "stars": int(l["stars"]),
             "taxa": round(l["stars"] / l["jogos"] * 100, 1)}
            for nome, l in g.iterrows()
        ]
        linhas.sort(key=lambda x: -x["taxa"])
        return linhas

    return {
        "total": total,
        "stars": stars,
        "taxa_geral": round(stars / total * 100, 1),
        "por_brawler": _taxa("brawler"),
        "por_modo": _taxa("modo"),
    }


# ---------------------------------------------------------------------------
# Composições de time — duplas/trios de jogadores e combinações de brawlers
# ---------------------------------------------------------------------------

from itertools import combinations
from math import sqrt

MINIMO_JOGOS_COMPOSICAO: int = 3


def wilson(vitorias: int, jogos: int, z: float = 1.96) -> float:
    """Limite inferior do intervalo de Wilson (95%) para a taxa de vitória.

    Ordenar por isso premia consistência: 65% em 30 jogos > 100% em 3 jogos.
    """
    if jogos == 0:
        return 0.0
    p = vitorias / jogos
    denom = 1 + z * z / jogos
    centro = p + z * z / (2 * jogos)
    ajuste = z * sqrt(p * (1 - p) / jogos + z * z / (4 * jogos * jogos))
    return (centro - ajuste) / denom


def composicoes_do_jogador(jogadores: list[dict], minimo: int = 2) -> dict:
    """Combinações de brawlers do jogador com aliados e trios de jogadores.

    `jogadores`: linhas de db.jogadores_das_batalhas (resultado = do ponto de
    vista do dono; aliado/eu relativos a ele).
    """
    por_hash: dict[str, dict] = {}
    for j in jogadores:
        if j["resultado"] not in ("Victory", "Defeat"):
            continue
        h = por_hash.setdefault(j["hash"], {"vitoria": j["resultado"] == "Victory",
                                            "eu": None, "aliados": []})
        if j["eu"]:
            h["eu"] = j
        elif j["aliado"]:
            h["aliados"].append(j)

    duplas_brawlers: dict[tuple, list[int]] = {}
    trios_jogadores: dict[tuple, dict] = {}
    for h in por_hash.values():
        if h["eu"] is None or not h["eu"].get("brawler"):
            continue
        v = int(h["vitoria"])
        for a in h["aliados"]:
            if a.get("brawler"):
                chave = (h["eu"]["brawler"], a["brawler"])
                duplas_brawlers.setdefault(chave, [0, 0])
                duplas_brawlers[chave][0] += 1
                duplas_brawlers[chave][1] += v
        if len(h["aliados"]) >= 2:
            for a1, a2 in combinations(sorted(h["aliados"], key=lambda x: x["tag_jogador"]), 2):
                chave = (a1["tag_jogador"], a2["tag_jogador"])
                t = trios_jogadores.setdefault(chave, {"jogos": 0, "vitorias": 0,
                                                       "nicks": (a1["nick"], a2["nick"])})
                t["jogos"] += 1
                t["vitorias"] += v

    duplas = [
        {"meu_brawler": k[0], "brawler_aliado": k[1], "jogos": c[0], "vitorias": c[1],
         "winrate": round(c[1] / c[0] * 100, 1)}
        for k, c in duplas_brawlers.items() if c[0] >= minimo
    ]
    duplas.sort(key=lambda d: -wilson(d["vitorias"], d["jogos"]))
    trios = [
        {"parceiros": f"{v['nicks'][0]} + {v['nicks'][1]}", "tags": k,
         "jogos": v["jogos"], "vitorias": v["vitorias"],
         "winrate": round(v["vitorias"] / v["jogos"] * 100, 1)}
        for k, v in trios_jogadores.items() if v["jogos"] >= minimo
    ]
    trios.sort(key=lambda t: -wilson(t["vitorias"], t["jogos"]))
    return {"duplas_brawlers": duplas[:15], "trios_jogadores": trios[:10]}


def composicoes_clube(linhas: list[dict], membros: set[str] | None,
                      minimo: int = MINIMO_JOGOS_COMPOSICAO,
                      modo: str | None = None) -> dict:
    """Duplas e trios de JOGADORES (times reais) em todo o banco.

    `linhas`: db.times_das_batalhas — hash, time, tag_jogador, nick, resultado
    (resultado do PRÓPRIO jogador da linha; num mesmo time todos compartilham).
    Se `membros` for dado, só conta composições 100% entre membros do clube.
    """
    times: dict[tuple, dict] = {}
    for l in linhas:
        if l["resultado"] not in ("Victory", "Defeat") or l["time"] is None:
            continue
        if modo is not None and l.get("modo") != modo:
            continue
        t = times.setdefault((l["hash"], l["time"]),
                             {"vitoria": l["resultado"] == "Victory", "jogadores": []})
        t["jogadores"].append(l)

    def _acumular(destino: dict, grupo: tuple, v: int) -> None:
        chave = tuple(j["tag_jogador"] for j in grupo)
        d = destino.setdefault(chave, {
            "jogos": 0, "vitorias": 0,
            "nomes": " + ".join(j["nick"] for j in grupo),
            "combos": {}, "stars": {},
        })
        d["jogos"] += 1
        d["vitorias"] += v
        brawlers = tuple((j.get("brawler") or "?") for j in grupo)
        if all(b != "?" for b in brawlers):
            c = d["combos"].setdefault(brawlers, [0, 0])
            c[0] += 1
            c[1] += v
        for j in grupo:
            if j.get("star_player"):
                d["stars"][j["nick"]] = d["stars"].get(j["nick"], 0) + 1

    duplas: dict[tuple, dict] = {}
    trios: dict[tuple, dict] = {}
    for t in times.values():
        js = t["jogadores"]
        if membros is not None:
            js = [j for j in js if j["tag_jogador"] in membros]
        v = int(t["vitoria"])
        ordenados = sorted(js, key=lambda x: x["tag_jogador"])
        for grupo in combinations(ordenados, 2):
            _acumular(duplas, grupo, v)
        for grupo in combinations(ordenados, 3):
            _acumular(trios, grupo, v)

    def _lista(dados: dict) -> list[dict]:
        out = []
        for k, v in dados.items():
            if v["jogos"] < minimo:
                continue
            melhores_combos = sorted(
                v["combos"].items(), key=lambda kv: (-kv[1][0], -kv[1][1])
            )[:2]
            combos_txt = [
                f"{' + '.join(bs)} ({c[0]}j, {round(c[1] / c[0] * 100)}%)"
                for bs, c in melhores_combos
            ]
            stars_txt = [
                f"{nick} ⭐{n}"
                for nick, n in sorted(v["stars"].items(), key=lambda kv: -kv[1])[:2]
            ]
            out.append({
                "nomes": v["nomes"], "tags": k, "jogos": v["jogos"],
                "vitorias": v["vitorias"],
                "winrate": round(v["vitorias"] / v["jogos"] * 100, 1),
                "brawlers_top": combos_txt,
                "stars": stars_txt,
            })
        out.sort(key=lambda x: -wilson(x["vitorias"], x["jogos"]))
        return out[:10]

    return {"duplas": _lista(duplas), "trios": _lista(trios)}


# ---------------------------------------------------------------------------
# Detecção de reset de temporada — queda de troféus não explicada por partidas
# ---------------------------------------------------------------------------

LIMIAR_RESET_TROFEUS: int = 500


def detectar_resets(snapshots: list[dict], batalhas: list[dict]) -> list[dict]:
    """Compara a variação de troféus entre snapshots consecutivos com a soma
    dos deltas das batalhas no intervalo. Queda >= LIMIAR não explicada por
    derrotas = provável reset de temporada da Supercell.
    """
    if len(snapshots) < 2:
        return []
    ordenados = sorted(snapshots, key=lambda s: s["criado_em"])
    resets: list[dict] = []
    for anterior, atual in zip(ordenados, ordenados[1:]):
        t_a, t_b = anterior.get("trofeus"), atual.get("trofeus")
        if t_a is None or t_b is None:
            continue
        variacao_real: int = t_b - t_a
        delta_partidas: int = sum(
            b["trofeus_delta"] or 0
            for b in batalhas
            if b.get("ocorrida_em")
            and anterior["criado_em"] <= b["ocorrida_em"] <= atual["criado_em"]
            and b.get("trofeus_delta") is not None
        )
        inexplicado: int = variacao_real - delta_partidas
        if inexplicado <= -LIMIAR_RESET_TROFEUS:
            resets.append({
                "entre": anterior["criado_em"][:10],
                "e": atual["criado_em"][:10],
                "queda": -inexplicado,
                "variacao_real": variacao_real,
                "delta_partidas": delta_partidas,
            })
    return resets
