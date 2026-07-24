"""Indicadores de performance (parte 2) — calculados sobre o histórico
ACUMULADO de batalhas do SQLite, não só as 25 do site (CLAUDE.md §4).

Winrate = vitórias / (vitórias + derrotas). Draws e resultados de showdown
('Rank N') ficam fora do denominador.
"""
import re

import pandas as pd

LIMIAR_AMOSTRA_PEQUENA: int = 20
_RE_RANKED_PTS = re.compile(r"\((\d[\d,]*)\)")


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
        "forma_recente": _forma_recente(decididas),
        "por_modo": _agrupado(decididas, "modo"),
        "por_mapa": _agrupado(decididas, "mapa"),
        "por_brawler": _agrupado(decididas, "brawler"),
        "melhor_brawler_por_modo": _melhor_brawler_por_modo(decididas),
        "modo_x_brawler": _cruz_brawler(decididas, "modo"),
        "mapa_x_brawler": _cruz_brawler(decididas, "mapa"),
        "brawler_detalhado": _brawler_detalhado(decididas),
        "trofeus_por_brawler": _trofeus_por_brawler(decididas),
        "por_periodo": _por_periodo(decididas),
        "duracao_x_resultado": _duracao_x_resultado(decididas),
        "queda_trofeus": _queda_trofeus(brawlers),
        "evolucao": _evolucao(snapshots),
        "evolucao_ranked": _evolucao_ranked(snapshots),
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
    """Winrate e uso agrupados por modo ou por brawler, mais jogados primeiro.

    Inclui 'stars' (vezes que o jogador foi Star Player) quando o dado existir —
    só ocorre em 3v3; showdown não tem star player, então soma 0 ali."""
    if decididas.empty or coluna not in decididas.columns:
        return []
    grupo = decididas.groupby(coluna)
    grupos = grupo["resultado"].agg(
        partidas="count", vitorias=lambda r: int((r == "Victory").sum())
    )
    if "star_player" in decididas.columns:
        grupos["stars"] = grupo["star_player"].apply(
            lambda s: int(pd.to_numeric(s, errors="coerce").fillna(0).sum())
        )
    if "duracao_seg" in decididas.columns:
        grupos["duracao_media"] = grupo["duracao_seg"].apply(
            lambda s: (lambda v: int(v.mean()) if not v.empty else None)
            (pd.to_numeric(s, errors="coerce").dropna())
        )
    grupos = grupos.reset_index()
    grupos["winrate"] = (grupos["vitorias"] / grupos["partidas"] * 100).round(1)
    grupos["uso_pct"] = (grupos["partidas"] / len(decididas) * 100).round(1)
    grupos = grupos.sort_values(["partidas", "winrate"], ascending=False)
    registros = grupos.rename(columns={coluna: "nome"}).to_dict("records")
    for r in registros:  # NaN de duração (grupo sem tempo) → None; e vira int
        d = r.get("duracao_media")
        r["duracao_media"] = None if d is None or pd.isna(d) else int(d)
    return registros


def _melhor_brawler_por_modo(decididas: pd.DataFrame, minimo: int = 3) -> list[dict]:
    """Para cada modo, o brawler seu com melhor winrate (Wilson) — ≥ `minimo` jogos.

    Responde de relance 'nesse modo, com o que eu vou melhor?'."""
    if decididas.empty or not {"modo", "brawler"} <= set(decididas.columns):
        return []
    df = decididas[decididas["brawler"].notna()]
    if df.empty:
        return []
    g = df.groupby(["modo", "brawler"]).agg(
        jogos=("resultado", "size"),
        vitorias=("resultado", lambda r: int((r == "Victory").sum())),
    ).reset_index()
    g = g[g["jogos"] >= minimo]
    if g.empty:
        return []
    g["wilson"] = g.apply(lambda r: wilson(int(r["vitorias"]), int(r["jogos"])), axis=1)
    g["winrate"] = (g["vitorias"] / g["jogos"] * 100).round(1)
    melhores = g.sort_values("wilson", ascending=False).groupby("modo").first().reset_index()
    melhores = melhores.sort_values("jogos", ascending=False)
    return [
        {"modo": r["modo"], "brawler": r["brawler"],
         "jogos": int(r["jogos"]), "winrate": float(r["winrate"])}
        for _, r in melhores.iterrows()
    ]


def _cruz_brawler(decididas: pd.DataFrame, chave: str, minimo: int = 2) -> list[dict]:
    """Winrate de CADA brawler dentro de CADA valor de `chave` (modo ou mapa).

    Retorna [{grupo, jogos, brawlers: [{brawler, jogos, winrate, stars}]}],
    grupos mais jogados primeiro; dentro do grupo, brawlers mais jogados primeiro."""
    if decididas.empty or not {chave, "brawler"} <= set(decididas.columns):
        return []
    df = decididas[decididas["brawler"].notna() & decididas[chave].notna()]
    if df.empty:
        return []
    tem_star = "star_player" in df.columns
    agg = {"jogos": ("resultado", "size"),
           "vitorias": ("resultado", lambda r: int((r == "Victory").sum()))}
    if tem_star:
        agg["stars"] = ("star_player", lambda s: int(pd.to_numeric(s, errors="coerce").fillna(0).sum()))
    g = df.groupby([chave, "brawler"]).agg(**agg).reset_index()
    g = g[g["jogos"] >= minimo]
    if g.empty:
        return []
    g["winrate"] = (g["vitorias"] / g["jogos"] * 100).round(1)
    jogos_por_grupo = g.groupby(chave)["jogos"].sum().to_dict()
    grupos: list[dict] = []
    for val in sorted(jogos_por_grupo, key=lambda m: -jogos_por_grupo[m]):
        linhas = g[g[chave] == val].sort_values(["jogos", "winrate"], ascending=False)
        grupos.append({
            "grupo": val,
            "jogos": int(jogos_por_grupo[val]),
            "brawlers": [{
                "brawler": r["brawler"], "jogos": int(r["jogos"]),
                "winrate": float(r["winrate"]),
                "stars": int(r["stars"]) if tem_star else 0,
            } for _, r in linhas.iterrows()],
        })
    return grupos


def _trofeus_por_brawler(decididas: pd.DataFrame) -> list[dict]:
    """Troféus LÍQUIDOS ganhos/perdidos com cada brawler (soma do trophyChange).

    Só conta batalhas de troféu (com delta); ordena do mais lucrativo ao pior."""
    if decididas.empty or not {"brawler", "trofeus_delta"}.issubset(decididas.columns):
        return []
    df = decididas.dropna(subset=["brawler", "trofeus_delta"])
    df = df[pd.to_numeric(df["trofeus_delta"], errors="coerce").notna()]
    if df.empty:
        return []
    df = df.assign(td=pd.to_numeric(df["trofeus_delta"], errors="coerce"))
    g = df.groupby("brawler").agg(
        jogos=("td", "size"), saldo=("td", "sum"),
        ganho=("td", lambda s: int(s[s > 0].sum())),
        perda=("td", lambda s: int(s[s < 0].sum())),
    ).reset_index()
    g = g.sort_values("saldo", ascending=False)
    return [{"brawler": str(r["brawler"]), "jogos": int(r["jogos"]),
             "saldo": int(r["saldo"]), "ganho": int(r["ganho"]),
             "perda": int(r["perda"])} for _, r in g.iterrows()]


def _por_periodo(decididas: pd.DataFrame) -> dict | None:
    """Quando você joga melhor: winrate por dia da semana e por faixa de horário
    (horário de Brasília, UTC-3)."""
    if decididas.empty or "ocorrida_em" not in decididas.columns:
        return None
    d = decididas.dropna(subset=["ocorrida_em"]).copy()
    dt = pd.to_datetime(d["ocorrida_em"], utc=True, errors="coerce") - pd.Timedelta(hours=3)
    d = d[dt.notna()]
    dt = dt.dropna()
    if d.empty:
        return None
    d = d.assign(_h=dt.dt.hour.values, _dow=dt.dt.dayofweek.values)
    d = d.assign(_vit=(d["resultado"] == "Victory").astype(int))

    dias_nome = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
    faixas = [("Madrugada (0-5h)", 0, 5), ("Manhã (6-11h)", 6, 11),
              ("Tarde (12-17h)", 12, 17), ("Noite (18-23h)", 18, 23)]

    def _linha(sub: pd.DataFrame, nome: str) -> dict | None:
        if sub.empty:
            return None
        j = len(sub)
        return {"nome": nome, "jogos": j,
                "winrate": round(float(sub["_vit"].mean()) * 100, 1)}

    por_dia = [x for i in range(7)
               if (x := _linha(d[d["_dow"] == i], dias_nome[i]))]
    por_faixa = [x for nome, a, b in faixas
                 if (x := _linha(d[(d["_h"] >= a) & (d["_h"] <= b)], nome))]
    return {"por_dia": por_dia, "por_faixa": por_faixa}


def _duracao_x_resultado(decididas: pd.DataFrame) -> dict | None:
    """Você ganha mais em partida curta ou longa? Duração média nas vitórias vs
    derrotas (só 3v3/modos com duração; showdown fica fora)."""
    if decididas.empty or "duracao_seg" not in decididas.columns:
        return None
    d = decididas.copy()
    d = d.assign(_dur=pd.to_numeric(d["duracao_seg"], errors="coerce"))
    d = d[d["_dur"].notna() & (d["_dur"] > 0)]
    if d.empty:
        return None
    vit = d[d["resultado"] == "Victory"]["_dur"]
    der = d[d["resultado"] == "Defeat"]["_dur"]
    if vit.empty or der.empty:
        return None
    return {"vitoria_seg": int(vit.mean()), "derrota_seg": int(der.mean()),
            "jogos": int(len(d))}


def _brawler_detalhado(decididas: pd.DataFrame) -> list[dict]:
    """Um bloco por brawler (para cards expansíveis): total + winrate por modo
    e por mapa DAQUELE brawler. Mais jogados primeiro."""
    if decididas.empty or "brawler" not in decididas.columns:
        return []
    df = decididas[decididas["brawler"].notna()]
    if df.empty:
        return []
    total: int = len(decididas)
    tem_star: bool = "star_player" in df.columns

    def _sub(g: pd.DataFrame, col: str) -> list[dict]:
        if col not in g.columns:
            return []
        gg = g.dropna(subset=[col]).groupby(col)["resultado"].agg(
            jogos="size", vit=lambda r: int((r == "Victory").sum())
        ).reset_index()
        if gg.empty:
            return []
        gg["winrate"] = (gg["vit"] / gg["jogos"] * 100).round(1)
        gg = gg.sort_values(["jogos", "winrate"], ascending=False)
        return [{"nome": str(r[col]), "jogos": int(r["jogos"]),
                 "winrate": float(r["winrate"])} for _, r in gg.iterrows()]

    saida: list[dict] = []
    for brawler, g in df.groupby("brawler"):
        jogos: int = len(g)
        vitorias: int = int((g["resultado"] == "Victory").sum())
        stars: int = (int(pd.to_numeric(g["star_player"], errors="coerce").fillna(0).sum())
                      if tem_star else 0)
        saida.append({
            "brawler": str(brawler), "jogos": jogos, "vitorias": vitorias,
            "winrate": round(vitorias / jogos * 100, 1),
            "uso_pct": round(jogos / total * 100, 1), "stars": stars,
            "por_modo": _sub(g, "modo"), "por_mapa": _sub(g, "mapa"),
        })
    saida.sort(key=lambda x: -x["jogos"])
    return saida


def _forma_recente(decididas: pd.DataFrame) -> dict | None:
    """Forma atual: winrate das últimas 20 partidas, dos últimos 7 dias e a
    sequência (streak) de vitórias/derrotas em andamento."""
    if decididas.empty or "ocorrida_em" not in decididas.columns:
        return None
    d = decididas.dropna(subset=["ocorrida_em"]).sort_values("ocorrida_em")
    if d.empty:
        return None
    ult20 = d.tail(20)
    from datetime import datetime, timezone, timedelta
    limite: str = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()[:19]
    ult7 = d[d["ocorrida_em"].str[:19] >= limite]
    seq = list(d["resultado"])[::-1]  # mais recente primeiro
    tipo: str = seq[0]
    streak_n: int = 0
    for r in seq:
        if r == tipo:
            streak_n += 1
        else:
            break

    def _saldo(sub: pd.DataFrame) -> int | None:
        if "trofeus_delta" not in sub.columns:
            return None
        v = pd.to_numeric(sub["trofeus_delta"], errors="coerce").dropna()
        return int(v.sum()) if not v.empty else None

    return {
        "ultimas_20_jogos": int(len(ult20)),
        "ultimas_20_wr": round(float((ult20["resultado"] == "Victory").mean()) * 100, 1),
        "ultimas_20_saldo": _saldo(ult20),
        "dias7_jogos": int(len(ult7)),
        "dias7_wr": (round(float((ult7["resultado"] == "Victory").mean()) * 100, 1)
                     if len(ult7) else None),
        "dias7_saldo": _saldo(ult7),
        "streak_tipo": tipo,
        "streak_n": streak_n,
    }


def _queda_trofeus(brawlers: list[dict], minimo_max: int = 100) -> list[dict]:
    """Brawlers mais distantes do próprio pico — candidatos a recuperar troféus."""
    quedas: list[dict] = []
    for b in brawlers:
        tmax = b.get("trofeus_max")
        tatual = b.get("trofeus")
        if tmax is None or tatual is None or tmax < minimo_max:
            continue
        queda: int = tmax - tatual
        if queda <= 0:
            continue
        quedas.append({
            "nome": b["nome"],
            "trofeus": tatual,
            "trofeus_max": tmax,
            "queda": queda,
            "queda_pct": round(queda / tmax * 100, 1),
        })
    quedas.sort(key=lambda q: q["queda"], reverse=True)
    return quedas[:10]


def _evolucao_ranked(snapshots: list[dict]) -> dict | None:
    """Evolução dos rank points do modo competitivo Ranked ao longo do tempo.

    Extrai o número entre parênteses de `ranked_atual` ('GOLD I (1601)' → 1601)
    e monta a série (1 ponto por dia, o último do dia). Acumula conforme os
    snapshots são gravados a cada consulta/rodada do rastreador."""
    if not snapshots:
        return None
    por_dia: dict[str, dict] = {}
    for s in sorted(snapshots, key=lambda x: x["criado_em"]):
        ra: str | None = s.get("ranked_atual")
        if not ra:
            continue
        m = _RE_RANKED_PTS.search(ra)
        if not m:
            continue
        dia: str = s["criado_em"][:10]
        por_dia[dia] = {"dia": dia, "pontos": int(m.group(1).replace(",", "")),
                        "rotulo": ra}
    if not por_dia:
        return None
    serie: list[dict] = [por_dia[d] for d in sorted(por_dia)]
    return {
        "serie": serie,
        "atual": serie[-1]["pontos"],
        "atual_rotulo": serie[-1]["rotulo"],
        "pico": max(p["pontos"] for p in serie),
        "dias": len(serie),
    }


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
        return {"matchups": [], "melhores_matchups": [], "parceiros": [],
                "batalhas_cobertas": 0}
    df["vitoria"] = (df["resultado"] == "Victory").astype(int)

    # winrate geral do jogador nas batalhas cobertas — base para o "lift" de parceiro
    batalhas_nivel = df.drop_duplicates("hash")[["hash", "vitoria"]]
    wr_geral: float = round(float(batalhas_nivel["vitoria"].mean()) * 100, 1)

    inimigos = df[(df["aliado"] == 0) & df["brawler"].notna()]
    matchups: list[dict] = []
    melhores_matchups: list[dict] = []
    if not inimigos.empty:
        # winrate POR BATALHA (uma batalha pode ter o mesmo brawler 2x no time inimigo)
        por_batalha = inimigos.drop_duplicates(["hash", "brawler"])
        g2 = por_batalha.groupby("brawler").agg(
            jogos=("hash", "size"), vitorias=("vitoria", "sum")
        )
        g2 = g2[g2["jogos"] >= MINIMO_JOGOS_MATCHUP]
        todos: list[dict] = [{
            "brawler": str(brawler),
            "jogos": int(linha["jogos"]),
            "vitorias": int(linha["vitorias"]),
            "winrate": round(linha["vitorias"] / linha["jogos"] * 100, 1),
        } for brawler, linha in g2.iterrows()]
        # sofre mais: menor winrate primeiro (Wilson das DERROTAS no topo)
        matchups = sorted(todos, key=lambda m: -wilson(m["jogos"] - m["vitorias"], m["jogos"]))
        # domina mais: maior winrate primeiro (Wilson das VITÓRIAS no topo)
        melhores_matchups = sorted(todos, key=lambda m: -wilson(m["vitorias"], m["jogos"]))

    # rivais: contra quais JOGADORES (não brawlers) você mais se enfrenta — H2H
    rivais: list[dict] = []
    inimigos_j = df[(df["aliado"] == 0) & df["tag_jogador"].notna()]
    if not inimigos_j.empty:
        pb = inimigos_j.drop_duplicates(["hash", "tag_jogador"])
        gr = pb.groupby("tag_jogador").agg(
            jogos=("hash", "size"), vitorias=("vitoria", "sum"), nick=("nick", "last"))
        gr = gr[gr["jogos"] >= 3]  # só rivais recorrentes
        rivais = [{"tag": str(t), "nick": str(l["nick"]) if l["nick"] else str(t),
                   "jogos": int(l["jogos"]), "vitorias": int(l["vitorias"]),
                   "winrate": round(l["vitorias"] / l["jogos"] * 100, 1)}
                  for t, l in gr.iterrows()]
        rivais.sort(key=lambda r: -r["jogos"])
        rivais = rivais[:12]

    # seu brawler por batalha (para cruzar com parceiros)
    meu_por_hash: dict = (df[df["eu"] == 1].drop_duplicates("hash")
                          .set_index("hash")["brawler"].to_dict())

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
            # lift: sua winrate COM esse parceiro vs. SEM ele (nas batalhas cobertas)
            hashes_com = set(aliados[aliados["tag_jogador"] == tag_p]["hash"])
            sem = batalhas_nivel[~batalhas_nivel["hash"].isin(hashes_com)]
            wr_com: float = round(linha["vitorias"] / linha["jogos"] * 100, 1)
            wr_sem: float | None = (round(float(sem["vitoria"].mean()) * 100, 1)
                                    if len(sem) else None)
            # seu melhor brawler ao lado desse parceiro (Wilson, mín. 2 jogos)
            sub = batalhas_nivel[batalhas_nivel["hash"].isin(hashes_com)].copy()
            sub["b"] = sub["hash"].map(meu_por_hash)
            melhor_b: str | None = None
            sb = sub.dropna(subset=["b"])
            if not sb.empty:
                gb = sb.groupby("b")["vitoria"].agg(j="size", v="sum")
                gb = gb[gb["j"] >= 2]
                if not gb.empty:
                    melhor_b = max(gb.index, key=lambda b: wilson(int(gb.loc[b, "v"]), int(gb.loc[b, "j"])))
                    melhor_b = f"{melhor_b} ({int(gb.loc[melhor_b, 'v'])}/{int(gb.loc[melhor_b, 'j'])})"
            parceiros.append({
                "tag": str(tag_p),
                "nick": str(linha["nick"]),
                "jogos": int(linha["jogos"]),
                "vitorias": int(linha["vitorias"]),
                "winrate": wr_com,
                "winrate_sem": wr_sem,
                "lift": (round(wr_com - wr_sem, 1) if wr_sem is not None else None),
                "melhor_brawler": melhor_b,
            })
        parceiros.sort(key=lambda p: -wilson(p["vitorias"], p["jogos"]))

    return {
        "matchups": matchups,
        "melhores_matchups": melhores_matchups,
        "rivais": rivais,
        "parceiros": parceiros,
        "wr_geral": wr_geral,
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
    # star player mesmo perdendo — você carregou mas o time não acompanhou
    stars_derrota: int = int(df[(df["star_player"] == 1) &
                                (df["resultado"] == "Defeat")].shape[0])

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
        "stars_derrota": stars_derrota,
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
