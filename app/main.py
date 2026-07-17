"""API do Brawl — app FastAPI. Rodar: uvicorn app.main:app --reload"""
import contextlib
import os
import sqlite3
import threading
import time as time_mod
from pathlib import Path

from fastapi import FastAPI, Form
from fastapi.requests import Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import db, rastrear
from app.coleta import brawlace, brawltime, brawlytix
from app.indicadores import meta as indicadores_meta
from app.indicadores import performance

DIR_APP: Path = Path(__file__).resolve().parent
INTERVALO_RASTREIO_SEG: int = 30 * 60   # rastreio embutido: a cada 30 min
_rastreio_lock = threading.Lock()


def _loop_rastreio() -> None:
    """Rastreio embutido: roda enquanto o app estiver aberto (o PC do usuário
    não fica sempre ligado — tarefa agendada do Windows foi aposentada)."""
    time_mod.sleep(10)  # deixa o servidor subir primeiro
    while True:
        if _rastreio_lock.acquire(blocking=False):
            try:
                rastrear.rastrear_uma_vez()
            except Exception as erro:  # nunca derrubar o app
                rastrear._log(f"loop: ERRO inesperado — {erro}")
            finally:
                _rastreio_lock.release()
        time_mod.sleep(INTERVALO_RASTREIO_SEG)


@contextlib.asynccontextmanager
async def _ciclo_de_vida(app: FastAPI):
    if os.environ.get("BRAWL_RASTREIO", "1") == "1":
        threading.Thread(target=_loop_rastreio, daemon=True).start()
    yield


app = FastAPI(title="API do Brawl", lifespan=_ciclo_de_vida)
app.mount("/static", StaticFiles(directory=DIR_APP / "static"), name="static")
templates = Jinja2Templates(directory=DIR_APP / "templates")


@app.get("/", response_class=HTMLResponse)
def home(request: Request, erro: str | None = None):
    conexao = db.conectar()
    try:
        recentes = conexao.execute(
            "SELECT tag, nick, ultimo_visto FROM jogadores ORDER BY ultimo_visto DESC LIMIT 10"
        ).fetchall()
        mensagem_erro: str | None = (
            "Tag inválida — use o formato #299PGGLQL (letras e números após o #)."
            if erro == "tag" else None
        )
        todos = db.ranking_jogadores(conexao)
        clube: dict | None = db.clube_principal(conexao)
        if clube:
            ranking = [r for r in todos if r["tag"] in clube["membros"]]
            fora_do_clube = [r for r in todos if r["tag"] not in clube["membros"]]
        else:
            ranking, fora_do_clube = todos, []
        comp_clube = performance.composicoes_clube(
            db.times_das_batalhas(conexao),
            clube["membros"] if clube else None,
        )
        return templates.TemplateResponse(
            request,
            "home.html",
            {
                "recentes": [dict(r) for r in recentes],
                "mensagem_erro": mensagem_erro,
                "ranking": ranking,
                "clube": clube,
                "fora_do_clube": fora_do_clube,
                "composicoes": comp_clube,
                "pendencias_externas": db.tags_sem_historico_externo(conexao),
                "rastreio_status": rastrear.ultima_rodada(),
            },
        )
    finally:
        conexao.close()


@app.post("/buscar")
def buscar(tag: str = Form(...)):
    try:
        tag_norm: str = brawlace.normalizar_tag(tag)
    except brawlace.TagInvalida:
        return RedirectResponse("/?erro=tag", status_code=303)
    return RedirectResponse(f"/jogador/{tag_norm.lstrip('#')}", status_code=303)


def _coletar_batalhas_por_modo(tag: str) -> list[dict]:
    """Coleta turbo: battle log filtrado por modo (até 25 batalhas EXTRAS/modo).

    Falha em um modo nunca derruba a consulta — só coleta menos.
    """
    extras: list[dict] = []
    for modo in brawlace.MODOS_BATTLELOG:
        try:
            extras.extend(brawlace.coletar_battlelog_modo(tag, modo))
        except (brawlace.ErroColeta, brawlace.ErroParsing):
            continue
    return extras


def _filtrar_tipo(batalhas: list[dict], filtro: str | None) -> list[dict]:
    """Filtro das abas: 'ranked' = tipo RANKED; 'trofeus' = todo o resto."""
    if filtro == "ranked":
        return [b for b in batalhas if b.get("tipo") == "RANKED"]
    if filtro == "trofeus":
        return [b for b in batalhas if b.get("tipo") != "RANKED"]
    return batalhas


def _consultar(tag: str, filtro_tipo: str | None = None) -> dict:
    """Coleta o perfil, grava no banco, calcula indicadores sobre o histórico."""
    perfil: dict = brawlace.coletar_perfil(tag)
    extras: list[dict] = _coletar_batalhas_por_modo(perfil["tag"])
    conexao = db.conectar()
    try:
        gravacao: dict = db.salvar_consulta(conexao, perfil)
        _atualizar_clube(conexao, perfil.get("clube_tag"))
        if extras:
            gravacao["batalhas_novas"] += db.salvar_batalhas(
                conexao, perfil["tag"], extras
            )
            conexao.commit()
            gravacao["total_batalhas"] = db.contar_batalhas(conexao, perfil["tag"])
        historico: list[dict] = db.batalhas_do_jogador(conexao, perfil["tag"])
        snapshots: list[dict] = db.snapshots_do_jogador(conexao, perfil["tag"])
        diario: list[dict] = db.historico_diario_do_jogador(conexao, perfil["tag"])
        brawlers_lp: list[dict] = db.historico_brawler_do_jogador(conexao, perfil["tag"])
        brawlers_modo: list[dict] = db.historico_brawler_modo_do_jogador(conexao, perfil["tag"])
        participantes: list[dict] = db.jogadores_das_batalhas(conexao, perfil["tag"])
    finally:
        conexao.close()
    historico = _filtrar_tipo(historico, filtro_tipo)
    participantes = _filtrar_tipo(participantes, filtro_tipo)
    perfil = {**perfil, "batalhas": _filtrar_tipo(perfil["batalhas"], filtro_tipo)}
    indicadores: dict = performance.calcular_indicadores(
        historico, perfil["brawlers"], snapshots, diario
    )
    extra: dict | None = brawltime.coletar_extra(perfil["tag"])
    conta: dict | None = brawlytix.coletar_conta(perfil["tag"])
    correlacao: dict | None = _correlacao_meta(perfil, historico, brawlers_lp,
                                               brawlers_modo)
    tendencias: dict | None = _tendencias_meta_seguro()
    return {
        "perfil": perfil, "gravacao": gravacao,
        "indicadores": indicadores, "extra": extra,
        "brawlers_longo_prazo": brawlers_lp,
        "correlacao": correlacao,
        "social": performance.social(participantes),
        "composicoes": performance.composicoes_do_jogador(participantes),
        "star": performance.star_player(historico),
        "tendencias": tendencias,
        "filtro_tipo": filtro_tipo,
        "conta": conta,
        "historico_batalhas": historico,
    }


def _atualizar_clube(conexao, clube_tag: str | None) -> None:
    """Atualiza o roster do clube do jogador consultado (cache 6 h; não-fatal)."""
    if not clube_tag:
        return
    try:
        db.salvar_clube(conexao, brawlace.coletar_clube(clube_tag))
    except (brawlace.ErroColeta, brawlace.ErroParsing, sqlite3.OperationalError):
        pass


def _tendencias_meta_seguro() -> dict | None:
    conexao = db.conectar()
    try:
        return indicadores_meta.tendencias_meta(conexao)
    finally:
        conexao.close()


def _correlacao_meta(perfil: dict, batalhas: list[dict],
                     historico_lp: list[dict] | None = None,
                     historico_modo: list[dict] | None = None) -> dict | None:
    """Meta + eventos + correlação. Falha aqui nunca derruba a página."""
    try:
        dados_meta: dict = brawlace.coletar_meta()
        eventos: list[dict] = brawlace.coletar_eventos()
    except (brawlace.ErroColeta, brawlace.ErroParsing):
        return None
    conexao = db.conectar()
    try:
        db.salvar_meta(conexao, dados_meta)
    except sqlite3.OperationalError:
        pass  # banco ocupado pelo rastreio — snapshot do meta fica p/ próxima
    finally:
        conexao.close()
    return indicadores_meta.calcular_meta_jogador(
        dados_meta, eventos, batalhas, perfil["brawlers"], historico_lp,
        historico_modo,
    )


def _consultar_do_banco(tag_norm: str, filtro_tipo: str | None = None) -> dict | None:
    """Página instantânea: monta tudo a partir do banco, sem scraping do perfil.

    Meta/eventos/brawltime usam cache em disco (rápidos na prática); só o
    scraping do perfil — a parte lenta — fica para o refresh em segundo plano.
    """
    conexao = db.conectar()
    try:
        perfil: dict | None = db.perfil_do_banco(conexao, tag_norm)
        if perfil is None:
            return None
        historico: list[dict] = db.batalhas_do_jogador(conexao, tag_norm)
        snapshots: list[dict] = db.snapshots_do_jogador(conexao, tag_norm)
        diario: list[dict] = db.historico_diario_do_jogador(conexao, tag_norm)
        brawlers_lp: list[dict] = db.historico_brawler_do_jogador(conexao, tag_norm)
        brawlers_modo: list[dict] = db.historico_brawler_modo_do_jogador(conexao, tag_norm)
        participantes: list[dict] = db.jogadores_das_batalhas(conexao, tag_norm)
    finally:
        conexao.close()
    historico = _filtrar_tipo(historico, filtro_tipo)
    participantes = _filtrar_tipo(participantes, filtro_tipo)
    perfil["batalhas"] = _filtrar_tipo(perfil["batalhas"], filtro_tipo)
    indicadores: dict = performance.calcular_indicadores(
        historico, perfil["brawlers"], snapshots, diario
    )
    extra: dict | None = brawltime.coletar_extra(tag_norm)
    conta: dict | None = brawlytix.coletar_conta(tag_norm)
    correlacao: dict | None = _correlacao_meta(perfil, historico, brawlers_lp,
                                               brawlers_modo)
    return {
        "perfil": perfil,
        "gravacao": {"batalhas_novas": 0, "total_batalhas": len(historico)},
        "indicadores": indicadores, "extra": extra,
        "brawlers_longo_prazo": brawlers_lp,
        "correlacao": correlacao,
        "social": performance.social(participantes),
        "composicoes": performance.composicoes_do_jogador(participantes),
        "star": performance.star_player(historico),
        "tendencias": _tendencias_meta_seguro(),
        "modo_instantaneo": True,
        "snapshot_em": perfil.get("_snapshot_em"),
        "filtro_tipo": filtro_tipo,
        "conta": conta,
        "historico_batalhas": historico,
    }


@app.get("/jogador/{tag}", response_class=HTMLResponse)
def pagina_jogador(request: Request, tag: str, atualizado: int = 0,
                   tipo: str | None = None):
    if tipo not in (None, "ranked", "trofeus"):
        tipo = None
    try:
        tag_norm: str = brawlace.normalizar_tag(tag)
    except brawlace.TagInvalida as erro:
        return templates.TemplateResponse(
            request, "erro.html", {"mensagem": str(erro)}, status_code=404
        )

    # jogador conhecido → serve o banco NA HORA; o JS da página dispara o
    # refresh em segundo plano e recarrega uma única vez (?atualizado=1)
    if not atualizado:
        dados_banco: dict | None = _consultar_do_banco(tag_norm, tipo)
        if dados_banco is not None:
            return templates.TemplateResponse(request, "jogador.html", dados_banco)

    try:
        dados: dict = _consultar(tag_norm, tipo)
    except brawlace.TagInvalida as erro:
        return templates.TemplateResponse(
            request, "erro.html", {"mensagem": str(erro)}, status_code=404
        )
    except brawlace.ErroColeta as erro:
        return templates.TemplateResponse(
            request, "erro.html", {"mensagem": f"brawlace.com indisponível: {erro}"},
            status_code=502,
        )
    return templates.TemplateResponse(request, "jogador.html", dados)


@app.post("/api/refrescar/{tag}")
def api_refrescar(tag: str):
    """Scraping + gravação em segundo plano (chamado pelo JS da página)."""
    try:
        dados: dict = _consultar(tag)
    except brawlace.TagInvalida as erro:
        return JSONResponse({"erro": str(erro)}, status_code=404)
    except brawlace.ErroColeta as erro:
        return JSONResponse({"erro": str(erro)}, status_code=502)
    return {"batalhas_novas": dados["gravacao"]["batalhas_novas"]}


@app.get("/api/meta")
def api_meta():
    try:
        dados_meta: dict = brawlace.coletar_meta()
        eventos: list[dict] = brawlace.coletar_eventos()
    except (brawlace.ErroColeta, brawlace.ErroParsing) as erro:
        return JSONResponse({"erro": str(erro)}, status_code=502)
    conexao = db.conectar()
    try:
        db.salvar_meta(conexao, dados_meta)
    finally:
        conexao.close()
    return {"meta": dados_meta, "eventos": eventos}


@app.get("/api/jogador/{tag}")
def api_jogador(tag: str):
    try:
        dados: dict = _consultar(tag)
    except brawlace.TagInvalida as erro:
        return JSONResponse({"erro": str(erro)}, status_code=404)
    except brawlace.ErroColeta as erro:
        return JSONResponse({"erro": str(erro)}, status_code=502)
    return dados


# ---------------------------------------------------------------------------
# Jogar agora — painel pré-jogo: eventos ativos × tudo que sabemos
# ---------------------------------------------------------------------------

def _winrate_de(linhas: list[dict], filtro) -> tuple[float | None, int]:
    decididas = [b for b in linhas if b.get("resultado") in ("Victory", "Defeat") and filtro(b)]
    if not decididas:
        return None, 0
    v = sum(1 for b in decididas if b["resultado"] == "Victory")
    return round(v / len(decididas) * 100, 1), len(decididas)


def _dados_jogador_para_time(conexao, tag: str) -> dict | None:
    """Pacote de dados de um membro do time para a distribuição de brawlers.

    Se o jogador nunca foi consultado (sem snapshot), usa como fallback os
    powers observados nas batalhas em que ele apareceu (batalha_jogadores).
    """
    perfil = db.perfil_do_banco(conexao, tag)
    kits: dict = {}
    trofeus_brawler: dict = {}
    if perfil is not None:
        nick = perfil["nick"]
        powers = {b["nome"]: b["power"] for b in perfil["brawlers"]}
        kits = {b["nome"]: b for b in perfil["brawlers"]}
        trofeus_brawler = {b["nome"]: b.get("trofeus") for b in perfil["brawlers"]}
    else:
        observado = conexao.execute(
            """SELECT brawler, MAX(power) AS power, MAX(nick) AS nick
               FROM batalha_jogadores
               WHERE tag_jogador = ? AND brawler IS NOT NULL AND power IS NOT NULL
               GROUP BY brawler""",
            (tag,),
        ).fetchall()
        if not observado:
            return None
        nick = next((o["nick"] for o in observado if o["nick"]), tag)
        powers = {o["brawler"]: o["power"] for o in observado}
        trofeus_brawler = {o["brawler"]: None for o in observado}
    return {
        "tag": tag,
        "nick": nick,
        "batalhas": db.batalhas_do_jogador(conexao, tag),
        "historico_lp": db.historico_brawler_do_jogador(conexao, tag),
        "historico_modo": db.historico_brawler_modo_do_jogador(conexao, tag),
        "powers": powers,
        "kits": kits,
        "trofeus_brawler": trofeus_brawler,
    }


@app.get("/jogar/{tag}", response_class=HTMLResponse)
def jogar_agora(request: Request, tag: str, time: str | None = None):
    try:
        tag_norm: str = brawlace.normalizar_tag(tag)
    except brawlace.TagInvalida as erro:
        return templates.TemplateResponse(
            request, "erro.html", {"mensagem": str(erro)}, status_code=404
        )
    try:
        eventos: list[dict] = brawlace.coletar_eventos()
        dados_meta: dict = brawlace.coletar_meta()
    except (brawlace.ErroColeta, brawlace.ErroParsing) as erro:
        return templates.TemplateResponse(
            request, "erro.html",
            {"mensagem": f"Não consegui buscar os eventos ativos: {erro}"},
            status_code=502,
        )

    conexao = db.conectar()
    try:
        perfil: dict | None = db.perfil_do_banco(conexao, tag_norm)
        if perfil is None:
            return RedirectResponse(f"/jogador/{tag_norm.lstrip('#')}", status_code=303)
        historico: list[dict] = db.batalhas_do_jogador(conexao, tag_norm)
        lp: list[dict] = db.historico_brawler_do_jogador(conexao, tag_norm)
        lp_modo: list[dict] = db.historico_brawler_modo_do_jogador(conexao, tag_norm)
        clube: dict | None = db.clube_principal(conexao)
        times: list[dict] = db.times_das_batalhas(conexao)

        # time selecionado (?time=TAG2,TAG3) — o dono sempre entra primeiro
        time_dados: list[dict] = []
        # candidatos a parceiro: membros do clube com batalhas no banco
        # (ou, sem clube conhecido, os jogadores já consultados)
        conhecidos = [
            dict(r) for r in conexao.execute(
                """SELECT bj.tag_jogador AS tag, MAX(bj.nick) AS nick,
                          COUNT(*) AS jogos
                   FROM batalha_jogadores bj
                   WHERE bj.tag_jogador != ? AND bj.nick IS NOT NULL
                   GROUP BY bj.tag_jogador HAVING jogos >= 3
                   ORDER BY jogos DESC""", (tag_norm,)
            )
        ]
        if clube:
            no_clube = [c for c in conhecidos if c["tag"] in clube["membros"]]
            conhecidos = no_clube or conhecidos
        conhecidos = conhecidos[:8]
        tags_time: list[str] = []
        if time:
            for t in time.split(","):
                try:
                    tags_time.append(brawlace.normalizar_tag(t))
                except brawlace.TagInvalida:
                    continue
            membros_time = [tag_norm] + [t for t in tags_time if t != tag_norm][:2]
            for t in membros_time:
                d = _dados_jogador_para_time(conexao, t)
                if d:
                    time_dados.append(d)
    finally:
        conexao.close()

    # meta por MAPA (brawltime) — cache 6h; falha vira None e segue sem
    stats_mapas: dict = {}
    vistos_mapa: set = set()
    for ev in eventos:
        chave = (ev["modo"], ev["mapa"])
        if chave in vistos_mapa:
            continue
        vistos_mapa.add(chave)
        stats_mapas[chave] = brawltime.coletar_meta_mapa(ev["modo"], ev["mapa"])

    sugestoes: list[dict] = indicadores_meta.sugestoes_por_evento(
        dados_meta, eventos, perfil["brawlers"], historico, lp, lp_modo,
        stats_mapas,
    )
    picks_por_evento = {(s["modo"], s["mapa"]): s["picks"] for s in sugestoes}
    membros = clube["membros"] if clube else None

    # acessórios: melhor do meta (brawltime, cache 24h) cruzado com o que cada
    # jogador possui. Cache local por brawler para não repetir requests.
    _cache_acess: dict = {}

    def _acess_meta(brawler_nome: str) -> dict | None:
        if brawler_nome not in _cache_acess:
            _cache_acess[brawler_nome] = brawltime.coletar_acessorios_brawler(brawler_nome)
        return _cache_acess[brawler_nome]

    brawler_do_dono = {b["nome"]: b for b in perfil["brawlers"]}
    for picks in picks_por_evento.values():
        for p in picks:
            p["acessorios"] = indicadores_meta.cruzar_acessorios(
                brawler_do_dono.get(p["brawler"]), _acess_meta(p["brawler"])
            )

    cartoes: list[dict] = []
    vistos: set[tuple[str, str]] = set()
    for ev in eventos:
        chave = (ev["modo"], ev["mapa"])
        if chave in vistos:
            continue
        vistos.add(chave)
        modo, mapa = ev["modo"], ev["mapa"]

        wr_modo, jogos_modo = _winrate_de(historico, lambda b: b.get("modo") == modo)
        # longo prazo por modo (soma dos brawlers naquele modo)
        v_lp = sum((h.get("vitorias") or 0) for h in lp_modo if h.get("modo") == modo)
        d_lp = sum((h.get("derrotas") or 0) for h in lp_modo if h.get("modo") == modo)
        if v_lp + d_lp:
            v_tot = v_lp + round((wr_modo or 0) / 100 * jogos_modo)
            n_tot = v_lp + d_lp + jogos_modo
            wr_modo, jogos_modo = round(v_tot / n_tot * 100, 1), n_tot
        wr_mapa, jogos_mapa = _winrate_de(historico, lambda b: b.get("mapa") == mapa)

        comp_modo = performance.composicoes_clube(times, membros, minimo=2, modo=modo)
        melhor_trio = (comp_modo["trios"] or comp_modo["duplas"] or [None])[0]

        meta_top = (dados_meta.get("modos", {}).get(modo) or [])[:3]

        mapa_info: dict | None = stats_mapas.get(chave)
        distribuicao = (
            indicadores_meta.distribuir_brawlers(dados_meta, modo, time_dados,
                                                 mapa_info)
            if len(time_dados) >= 2 else None
        )
        # acessórios de cada atribuição da distribuição (usa o kit do jogador)
        if distribuicao:
            kit_por_jogador = {d["nick"]: d.get("kits", {}) for d in time_dados}
            for grupo in (distribuicao.get("atribuicao", []),
                          distribuicao.get("individuais", [])):
                for a in grupo:
                    kit = kit_por_jogador.get(a["nick"], {})
                    a["acessorios"] = indicadores_meta.cruzar_acessorios(
                        kit.get(a["brawler"]), _acess_meta(a["brawler"])
                    )

        cartoes.append({
            "modo": modo, "mapa": mapa, "fim": ev.get("fim"),
            "wr_modo": wr_modo, "jogos_modo": jogos_modo,
            "wr_mapa": wr_mapa, "jogos_mapa": jogos_mapa,
            "picks": picks_por_evento.get(chave, []),
            "melhor_time": melhor_trio,
            "meta_top": meta_top,
            "distribuicao": distribuicao,
            "mapa_meta": mapa_info,
        })

    # modos em que o jogador vai melhor primeiro (com amostra)
    cartoes.sort(key=lambda c: -(performance.wilson(
        round((c["wr_modo"] or 0) / 100 * c["jogos_modo"]), c["jogos_modo"]
    ) if c["jogos_modo"] else 0))

    return templates.TemplateResponse(request, "jogar.html", {
        "perfil": perfil, "cartoes": cartoes, "clube": clube,
        "data_meta": dados_meta.get("data"),
        "conhecidos": conhecidos,
        "tags_time": tags_time,
    })
