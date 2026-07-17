"""Correlação jogador × meta (parte 3 do projeto — CLAUDE.md §5).

- Score vs meta (0–100): o quanto os brawlers que o jogador joga estão bem
  posicionados no meta dos modos em que ele os joga. Percentil por posição no
  ranking de Star Player %, ponderado pelo número de partidas do jogador.
- Sugestões de pick: para cada evento ativo, os melhores brawlers do meta do
  modo que o jogador tem em power alto.
"""

POWER_MINIMO_SUGESTAO: int = 9
MAX_PICKS_POR_EVENTO: int = 3


def _percentil(posicao: int, total: int) -> float:
    """1º de N → 1.0; último → próximo de 0."""
    if total <= 1:
        return 1.0
    return 1.0 - (posicao - 1) / total


def score_vs_meta(meta: dict, batalhas: list[dict]) -> dict | None:
    """Média ponderada (por partidas) do percentil de cada dupla modo+brawler
    que o jogador jogou. Retorna score 0–100 + detalhamento."""
    modos_meta: dict = meta.get("modos", {})
    pesos: dict[tuple[str, str], int] = {}
    for b in batalhas:
        modo, brawler = b.get("modo"), b.get("brawler")
        if not modo or not brawler or modo not in modos_meta:
            continue
        pesos[(modo, brawler)] = pesos.get((modo, brawler), 0) + 1
    if not pesos:
        return None

    detalhes: list[dict] = []
    soma: float = 0.0
    peso_total: int = 0
    for (modo, brawler), partidas in pesos.items():
        ranking = modos_meta[modo]
        total = len(ranking)
        entrada = next((r for r in ranking if r["brawler"] == brawler), None)
        posicao = entrada["posicao"] if entrada else total  # fora do ranking = último
        pct = _percentil(posicao, total)
        soma += pct * partidas
        peso_total += partidas
        detalhes.append({
            "modo": modo, "brawler": brawler, "partidas": partidas,
            "posicao_meta": posicao if entrada else None,
            "total_ranking": total,
            "percentil": round(pct * 100, 1),
        })
    detalhes.sort(key=lambda d: d["partidas"], reverse=True)
    return {
        "score": round(soma / peso_total * 100, 1),
        "detalhes": detalhes[:10],
    }


def _fator_meta_v2(posicao: int, total: int, wr_mapa: float | None) -> float:
    """Meta do MAPA (brawltime, winrate ajustado) quando disponível: 60% mapa
    + 40% modo. Sem dados do mapa: só o percentil do modo."""
    base_modo: float = _percentil(posicao, total)  # já 0–1 (1º lugar = 1.0)
    if wr_mapa is None:
        return base_modo
    # winrates ajustados reais ficam ~40-85% → normaliza para 0-1
    base_mapa: float = min(1.0, max(0.0, (wr_mapa - 40.0) / 45.0))
    return 0.6 * base_mapa + 0.4 * base_modo


def _bonus_kit(info: dict | None) -> float:
    """Kit liberado do brawler DESTE jogador: star power/gadget/hypercharge.
    Até +0.10 no score — um 9 completo pode superar um 11 pelado."""
    if not info:
        return 0.0
    return (0.03 * (1 if info.get("star_powers") else 0)
            + 0.03 * (1 if info.get("gadgets") else 0)
            + 0.04 * (1 if info.get("hypercharge") else 0))


def _stats_por_brawler(batalhas: list[dict],
                       historico_lp: list[dict] | None,
                       modo: str | None = None,
                       historico_modo: list[dict] | None = None) -> dict[str, dict]:
    """Vitórias/jogos do JOGADOR por brawler.

    Sem `modo`: total (batalhas acumuladas + longo prazo).
    Com `modo`: só aquele modo (batalhas do modo + historico_brawler_modo).
    """
    stats: dict[str, dict] = {}
    for b in batalhas:
        if b.get("resultado") not in ("Victory", "Defeat") or not b.get("brawler"):
            continue
        if modo is not None and b.get("modo") != modo:
            continue
        s = stats.setdefault(b["brawler"], {"jogos": 0, "vitorias": 0})
        s["jogos"] += 1
        s["vitorias"] += int(b["resultado"] == "Victory")
    if modo is None:
        for lp in historico_lp or []:
            s = stats.setdefault(lp["brawler"], {"jogos": 0, "vitorias": 0})
            s["jogos"] += (lp.get("vitorias") or 0) + (lp.get("derrotas") or 0)
            s["vitorias"] += lp.get("vitorias") or 0
    else:
        for hm in historico_modo or []:
            if hm.get("modo") != modo:
                continue
            s = stats.setdefault(hm["brawler"], {"jogos": 0, "vitorias": 0})
            s["jogos"] += (hm.get("vitorias") or 0) + (hm.get("derrotas") or 0)
            s["vitorias"] += hm.get("vitorias") or 0
    return stats


def sugestoes_por_evento(
    meta: dict, eventos: list[dict], brawlers_jogador: list[dict],
    batalhas: list[dict] | None = None,
    historico_lp: list[dict] | None = None,
    historico_modo: list[dict] | None = None,
    stats_mapas: dict | None = None,
) -> list[dict]:
    """Para cada evento ativo: melhores picks PERSONALIZADOS (Score v2).

    Score = 50% meta + 50% desempenho do jogador + bônus de kit (SP/gadget/
    hyper liberados). Meta usa o WINRATE DO MAPA (brawltime) quando
    `stats_mapas[(modo, mapa)]` existir; senão o percentil do modo.
    Desempenho prioriza o winrate NAQUELE modo (70/30 sobre o geral).
    """
    from app.indicadores.performance import wilson

    do_jogador: dict[str, dict] = {b["nome"]: b for b in brawlers_jogador}
    stats: dict[str, dict] = _stats_por_brawler(batalhas or [], historico_lp)
    modos_meta: dict = meta.get("modos", {})

    sugestoes: list[dict] = []
    vistos: set[tuple[str, str]] = set()
    for evento in eventos:
        modo, mapa = evento["modo"], evento["mapa"]
        if (modo, mapa) in vistos or modo not in modos_meta:
            continue
        vistos.add((modo, mapa))
        total: int = len(modos_meta[modo])
        mapa_info: dict | None = (stats_mapas or {}).get((modo, mapa))
        wr_mapa_por_brawler: dict = (mapa_info or {}).get("brawlers", {})
        stats_modo: dict[str, dict] = _stats_por_brawler(
            batalhas or [], None, modo, historico_modo
        )
        candidatos: list[dict] = []
        for linha in modos_meta[modo]:
            meu = do_jogador.get(linha["brawler"])
            if meu is None or meu["power"] < POWER_MINIMO_SUGESTAO:
                continue
            st = stats.get(linha["brawler"], {"jogos": 0, "vitorias": 0})
            st_m = stats_modo.get(linha["brawler"], {"jogos": 0, "vitorias": 0})
            wr_mapa: float | None = wr_mapa_por_brawler.get(linha["brawler"])
            fator_meta: float = _fator_meta_v2(linha["posicao"], total, wr_mapa)
            fator_seu: float = (
                0.7 * wilson(st_m["vitorias"], st_m["jogos"])
                + 0.3 * wilson(st["vitorias"], st["jogos"])
            )
            candidatos.append({
                "brawler": linha["brawler"],
                "posicao_meta": linha["posicao"],
                "star_player_pct": linha["star_player_pct"],
                "power": meu["power"],
                "trofeus": meu["trofeus"],
                "jogos_seus": st["jogos"],
                "winrate_seu": (round(st["vitorias"] / st["jogos"] * 100, 1)
                                if st["jogos"] else None),
                "jogos_no_modo": st_m["jogos"],
                "winrate_no_modo": (round(st_m["vitorias"] / st_m["jogos"] * 100, 1)
                                    if st_m["jogos"] else None),
                "wr_mapa_global": wr_mapa,
                "score_pick": round(
                    (0.5 * fator_meta + 0.5 * fator_seu + _bonus_kit(meu)) * 100, 1
                ),
            })
        candidatos.sort(key=lambda c: -c["score_pick"])
        sugestoes.append({"modo": modo, "mapa": mapa,
                          "picks": candidatos[:MAX_PICKS_POR_EVENTO]})
    return sugestoes


def calcular_meta_jogador(
    meta: dict, eventos: list[dict], batalhas: list[dict],
    brawlers_jogador: list[dict],
    historico_lp: list[dict] | None = None,
    historico_modo: list[dict] | None = None,
) -> dict:
    return {
        "data_meta": meta.get("data"),
        "score": score_vs_meta(meta, batalhas),
        "sugestoes": sugestoes_por_evento(meta, eventos, brawlers_jogador,
                                          batalhas, historico_lp, historico_modo),
    }


# ---------------------------------------------------------------------------
# Tendências do meta — compara meta_snapshots entre a data mais antiga e a atual
# ---------------------------------------------------------------------------

def tendencias_meta(conexao) -> dict | None:
    """Quem subiu/caiu no meta entre o snapshot mais antigo e o mais recente.

    Retorna None enquanto só houver 1 data coletada (precisa de histórico).
    """
    datas = [
        linha[0] for linha in conexao.execute(
            "SELECT DISTINCT data FROM meta_snapshots ORDER BY data"
        ).fetchall()
    ]
    if len(datas) < 2:
        return None
    antiga, recente = datas[0], datas[-1]

    linhas = conexao.execute(
        """SELECT a.modo, a.brawler, a.posicao AS pos_antes, r.posicao AS pos_agora
           FROM meta_snapshots a
           JOIN meta_snapshots r ON r.modo = a.modo AND r.brawler = a.brawler
           WHERE a.data = ? AND r.data = ? AND a.posicao != r.posicao""",
        (antiga, recente),
    ).fetchall()

    movimentos = [
        {
            "modo": l["modo"], "brawler": l["brawler"],
            "pos_antes": l["pos_antes"], "pos_agora": l["pos_agora"],
            "delta": l["pos_antes"] - l["pos_agora"],  # positivo = subiu
        }
        for l in linhas
    ]
    subindo = sorted((m for m in movimentos if m["delta"] > 0),
                     key=lambda m: -m["delta"])[:10]
    caindo = sorted((m for m in movimentos if m["delta"] < 0),
                    key=lambda m: m["delta"])[:10]
    if not subindo and not caindo:
        return None
    return {"de": antiga, "ate": recente, "subindo": subindo, "caindo": caindo}


# ---------------------------------------------------------------------------
# Quem pega o quê — distribuir os brawlers do meta entre os jogadores do time
# ---------------------------------------------------------------------------

MAX_CANDIDATOS_DISTRIBUICAO: int = 8


def tamanho_time_do_modo(modo: str) -> int:
    """Quantos jogadores do grupo entram juntos numa partida desse modo."""
    m = modo.upper()
    if "SOLO SHOWDOWN" in m or "DUELS" in m:
        return 1
    if "DUO SHOWDOWN" in m:
        return 2
    return 3  # 3v3 (e 5v5: só temos até 3 do grupo)


def distribuir_brawlers(meta: dict, modo: str, jogadores: list[dict],
                        stats_mapa: dict | None = None) -> dict | None:
    """Melhor atribuição de brawlers para um grupo jogando junto, respeitando
    o TAMANHO DO TIME do modo: solo = cada um por si (pode repetir brawler);
    duo = melhor dupla entre os selecionados (informa quem fica de fora);
    3v3 = trio completo.

    Score v2 (jogador, brawler) = 50% meta (mapa quando disponível) + 50%
    desempenho (70% no modo/30% geral, Wilson) + bônus de kit. Na escolha do
    time: penaliza brawlers com TROFÉUS muito distantes entre si (matchmaking)
    e bonifica combinações que aparecem nos melhores times do MAPA (brawltime).
    Requer power >= POWER_MINIMO_SUGESTAO.
    """
    from itertools import combinations as _comb, permutations
    from app.indicadores.performance import wilson

    ranking = meta.get("modos", {}).get(modo)
    if not ranking or len(jogadores) < 2:
        return None
    tamanho: int = min(tamanho_time_do_modo(modo), len(jogadores))
    wr_mapa_por_brawler: dict = (stats_mapa or {}).get("brawlers", {})
    times_do_mapa: list[set] = [
        set(t["brawlers"]) for t in (stats_mapa or {}).get("times", [])[:10]
    ]
    total: int = len(ranking)
    candidatos = ranking[:MAX_CANDIDATOS_DISTRIBUICAO]

    # score de cada (jogador, brawler)
    scores: list[dict[str, dict]] = []
    for j in jogadores:
        stats_total = _stats_por_brawler(j["batalhas"], j.get("historico_lp"))
        stats_modo = _stats_por_brawler(j["batalhas"], None, modo, j.get("historico_modo"))
        linha: dict[str, dict] = {}
        for c in candidatos:
            b = c["brawler"]
            if j["powers"].get(b, 0) < POWER_MINIMO_SUGESTAO:
                continue
            st = stats_total.get(b, {"jogos": 0, "vitorias": 0})
            st_m = stats_modo.get(b, {"jogos": 0, "vitorias": 0})
            fator_meta = _fator_meta_v2(c["posicao"], total,
                                        wr_mapa_por_brawler.get(b))
            fator_seu = (0.7 * wilson(st_m["vitorias"], st_m["jogos"])
                         + 0.3 * wilson(st["vitorias"], st["jogos"]))
            info_kit = (j.get("kits") or {}).get(b)
            linha[b] = {
                "score": 0.5 * fator_meta + 0.5 * fator_seu + _bonus_kit(info_kit),
                "trofeus_brawler": (j.get("trofeus_brawler") or {}).get(b),
                "posicao_meta": c["posicao"],
                "jogos_modo": st_m["jogos"],
                "winrate_modo": (round(st_m["vitorias"] / st_m["jogos"] * 100, 1)
                                 if st_m["jogos"] else None),
                "jogos_geral": st["jogos"],
                "winrate_geral": (round(st["vitorias"] / st["jogos"] * 100, 1)
                                  if st["jogos"] else None),
            }
        scores.append(linha)

    nomes_brawlers = [c["brawler"] for c in candidatos]

    def _info(i: int, b: str) -> dict:
        s = scores[i][b]
        return {
            "nick": jogadores[i]["nick"], "brawler": b,
            "posicao_meta": s["posicao_meta"],
            "winrate_modo": s["winrate_modo"], "jogos_modo": s["jogos_modo"],
            "winrate_geral": s["winrate_geral"], "jogos_geral": s["jogos_geral"],
        }

    if tamanho == 1:
        # solo: cada um escolhe o próprio melhor — repetição permitida
        individuais = []
        for i in range(len(jogadores)):
            if not scores[i]:
                continue
            b = max(scores[i], key=lambda k: scores[i][k]["score"])
            individuais.append(_info(i, b))
        if not individuais:
            return None
        return {"individuais": individuais, "atribuicao": [], "de_fora": [],
                "por_brawler": _donos(candidatos, scores, jogadores)}

    melhor: tuple | None = None
    for indices in _comb(range(len(jogadores)), tamanho):
        for combo in permutations(nomes_brawlers, tamanho):
            soma = 0.0
            valido = True
            trofeus_combo: list[int] = []
            for pos, i in enumerate(indices):
                b = combo[pos]
                if b not in scores[i]:
                    valido = False
                    break
                soma += scores[i][b]["score"]
                t = scores[i][b].get("trofeus_brawler")
                if t is not None:
                    trofeus_combo.append(t)
            if not valido:
                continue
            # proximidade de troféus: brawlers muito díspares desequilibram o
            # matchmaking do grupo — até -0.09 de penalidade
            if len(trofeus_combo) >= 2:
                soma -= min(0.09, 0.0003 * (max(trofeus_combo) - min(trofeus_combo)))
            # sinergia: a combinação aparece nos melhores times do MAPA? +0.06
            if times_do_mapa and any(set(combo) <= t for t in times_do_mapa):
                soma += 0.06
            if melhor is None or soma > melhor[0]:
                melhor = (soma, indices, combo)
    if melhor is None:
        return None

    _, indices, combo = melhor
    atribuicao = [_info(i, combo[pos]) for pos, i in enumerate(indices)]
    de_fora = [jogadores[i]["nick"] for i in range(len(jogadores)) if i not in indices]

    return {"atribuicao": atribuicao, "de_fora": de_fora, "individuais": [],
            "por_brawler": _donos(candidatos, scores, jogadores)}


def _donos(candidatos: list[dict], scores: list[dict], jogadores: list[dict]) -> list[dict]:
    """Quem do grupo é o melhor com cada brawler do topo do meta."""
    por_brawler = []
    for c in candidatos[:5]:
        b = c["brawler"]
        donos = [(i, scores[i][b]) for i in range(len(jogadores)) if b in scores[i]]
        if not donos:
            continue
        i, s = max(donos, key=lambda ds: ds[1]["score"])
        por_brawler.append({
            "brawler": b, "posicao_meta": c["posicao"],
            "melhor": jogadores[i]["nick"],
            "winrate_modo": s["winrate_modo"], "jogos_modo": s["jogos_modo"],
            "winrate_geral": s["winrate_geral"], "jogos_geral": s["jogos_geral"],
        })
    return por_brawler


# ---------------------------------------------------------------------------
# Acessórios: cruzar o que o jogador POSSUI × o melhor do meta (brawltime)
# ---------------------------------------------------------------------------

def _norm_acess(nome: str) -> str:
    return "".join(c for c in nome.upper() if c.isalnum())


def cruzar_acessorios(brawler_jogador: dict | None, acess_meta: dict | None) -> dict | None:
    """Para um brawler: o que equipar. Junta o melhor do meta (brawltime) com o
    que o jogador possui, sinalizando se ele tem o recomendado.
    """
    if brawler_jogador is None:
        return None
    out: dict = {}
    for tipo, chave in (("star_power", "star_powers_nomes"),
                        ("gadget", "gadgets_nomes"),
                        ("gear", "gears_nomes")):
        rec = (acess_meta or {}).get(tipo)
        possui = brawler_jogador.get(chave) or []
        if rec:
            tem = _norm_acess(rec["melhor"]) in [_norm_acess(x) for x in possui]
            out[tipo] = {
                "recomendado": rec["melhor"], "winrate": rec.get("winrate"),
                "possui_recomendado": tem, "seus": possui,
                # o que de fato equipar: o recomendado se tiver, senão o que tem
                "equipar": rec["melhor"] if tem else (possui[0] if possui else None),
            }
        elif possui:
            out[tipo] = {"recomendado": None, "seus": possui, "equipar": possui[0],
                         "possui_recomendado": None}
    out["hypercharge"] = bool(brawler_jogador.get("hypercharge"))
    return out
