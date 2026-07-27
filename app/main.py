"""API do Brawl — app FastAPI. Rodar: uvicorn app.main:app --reload"""
import contextlib
import os
import threading
import time as time_mod
from pathlib import Path

from fastapi import FastAPI, Form
from fastapi.requests import Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import db, rastrear, imagens
from app.coleta import brawlace, brawltime, brawlytix, oficial
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
    # No modo Postgres, garante o schema UMA vez no boot (não a cada conexão).
    if db._database_url():
        con = db.conectar()
        try:
            db.garantir_schema_pg(con)
        except db.ErrosBanco as erro:
            print(f"[startup] aviso ao garantir schema Postgres: {erro}")
        finally:
            con.close()
    try:  # carrega o mapa nome→id dos brawlers p/ as imagens (best-effort)
        n = imagens.recarregar()
        print(f"[startup] mapa de imagens: {n} brawlers")
    except Exception as erro:
        print(f"[startup] aviso ao carregar mapa de imagens: {erro}")
    if os.environ.get("BRAWL_RASTREIO", "1") == "1":
        threading.Thread(target=_loop_rastreio, daemon=True).start()
    yield


app = FastAPI(title="API do Brawl", lifespan=_ciclo_de_vida)
app.mount("/static", StaticFiles(directory=DIR_APP / "static"), name="static")
templates = Jinja2Templates(directory=DIR_APP / "templates")


def _css_ver() -> str:
    """Versão do estilo.css (mtime) para cache-busting — o navegador refaz o
    download sempre que o arquivo muda, sem depender de hard refresh."""
    try:
        return str(int((DIR_APP / "static" / "estilo.css").stat().st_mtime))
    except OSError:
        return "1"


# global de template chamado por render → lê o mtime na hora (não precisa restart)
templates.env.globals["css_ver"] = _css_ver

# URLs de imagem (CDN brawlify) por nome — carregam no navegador do visitante
templates.env.globals["img_brawler"] = imagens.img_brawler
templates.env.globals["img_star_power"] = imagens.img_star_power
templates.env.globals["img_gadget"] = imagens.img_gadget
templates.env.globals["acessorios_brawler"] = imagens.acessorios_brawler


@app.get("/", response_class=HTMLResponse)
def home(request: Request, erro: str | None = None):
    """Landing enxuta: busca de tag + atalhos (clã, brawlers/meta) + status.
    As estatísticas do clã ficam em /cla; as do meta em /brawler."""
    conexao = db.conectar()
    try:
        recentes = conexao.execute(
            "SELECT tag, nick, ultimo_visto FROM jogadores ORDER BY ultimo_visto DESC LIMIT 10"
        ).fetchall()
        mensagem_erro: str | None = (
            "Tag inválida — use o formato #299PGGLQL (letras e números após o #)."
            if erro == "tag" else None
        )
        clube: dict | None = db.clube_principal(conexao)
        return templates.TemplateResponse(
            request,
            "home.html",
            {
                "recentes": [dict(r) for r in recentes],
                "mensagem_erro": mensagem_erro,
                "clube": clube,
                "tem_meta": db.data_meta_recente(conexao) is not None,
                "estatisticas": db.estatisticas_globais(conexao),
                "meta_proprio": {
                    "por_modo": db.melhor_brawler_por_grupo(conexao, "modo", minimo=5),
                    "por_mapa": db.melhor_brawler_por_grupo(conexao, "mapa", minimo=5, limite=20),
                    "mais_usados": db.brawlers_mais_usados_geral(conexao, 15),
                    "mapas": db.mapas_mais_jogados(conexao, 12),
                    "modos_jogados": db.modos_mais_jogados(conexao),
                },
                "rastreio_status": rastrear.ultima_rodada(),
            },
        )
    finally:
        conexao.close()


def _dados_cla(conexao) -> dict:
    """Ranking dos membros + composições + conhecidos de fora — usado em /cla."""
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
    membros = clube["membros"] if clube else set()
    return {
        "ranking": ranking, "clube": clube,
        "fora_do_clube": fora_do_clube, "composicoes": comp_clube,
        "melhor_por_modo": db.melhor_membro_por_modo(conexao, membros),
        "por_brawler": db.ranking_membros_por_brawler(conexao, membros),
    }


_ultimo_refresh_cla: float = 0.0  # throttle do refresh sob demanda da /cla


@app.get("/cla", response_class=HTMLResponse)
def pagina_cla(request: Request, atualizado: int | None = None):
    conexao = db.conectar()
    try:
        ctx = _dados_cla(conexao)
    finally:
        conexao.close()
    # dispara o refresh dos membros em 2º plano só na 1ª carga (não no reload)
    ctx["refrescar"] = not atualizado
    return templates.TemplateResponse(request, "cla.html", ctx)


@app.post("/api/refrescar-cla")
def api_refrescar_cla():
    """Atualiza os membros do clã pela API oficial (throttle 10 min)."""
    global _ultimo_refresh_cla
    agora = time_mod.time()
    if agora - _ultimo_refresh_cla < 600:
        return {"pulado": True}
    _ultimo_refresh_cla = agora  # marca já, evita refresh concorrente
    try:
        return rastrear.rastrear_membros_cla()
    except Exception as erro:
        return JSONResponse({"erro": str(erro)}, status_code=200)


@app.get("/brawler", response_class=HTMLResponse)
def pagina_brawlers(request: Request, modo: str | None = None):
    """Índice do meta (accordion). Botões: Geral (força média) + eventos ativos.
    Ao escolher um modo, reordena os brawlers pela posição NAQUELE modo."""
    conexao = db.conectar()
    try:
        dados = db.meta_todos_detalhado(conexao)
    finally:
        conexao.close()
    brawlers = dados["brawlers"]
    modos_meta = {m["modo"] for b in brawlers for m in b["modos"]}
    # modos dos eventos ativos que também existem no meta (best-effort)
    eventos = _seguro(lambda: oficial.coletar_eventos()) or []
    modos_ativos: list[str] = []
    for ev in eventos:
        m = (ev.get("modo") or "").upper()
        if m in modos_meta and m not in modos_ativos:
            modos_ativos.append(m)
    modo_sel = modo.upper() if modo else None
    if modo_sel and modo_sel in modos_meta:
        def _pos(b: dict):
            return next((m["posicao"] for m in b["modos"] if m["modo"] == modo_sel), None)
        brawlers = sorted((dict(b, pos_sel=_pos(b)) for b in brawlers if _pos(b) is not None),
                          key=lambda b: b["pos_sel"])
    else:
        modo_sel = None
    return templates.TemplateResponse(request, "brawlers.html", {
        "brawlers": brawlers, "data_meta": dados["data"],
        "modos_ativos": modos_ativos, "modo_sel": modo_sel,
    })


@app.get("/brawler/{nome}", response_class=HTMLResponse)
def pagina_brawler(request: Request, nome: str):
    """Detalhe de um brawler (link direto). O índice /brawler já mostra tudo
    inline; esta rota serve para compartilhar/abrir um brawler específico."""
    brawler = nome.upper()  # nome vem URL-decoded; no meta os nomes são MAIÚSCULOS
    conexao = db.conectar()
    try:
        dados = db.meta_brawler_detalhado(conexao, brawler)
        if not dados["modos"]:
            return templates.TemplateResponse(
                request, "erro.html",
                {"mensagem": f"Sem dados de meta para '{brawler}'."},
                status_code=404,
            )
        return templates.TemplateResponse(
            request, "brawler.html",
            {"brawler": brawler, "dados": dados, "data_meta": dados["data"]},
        )
    finally:
        conexao.close()


def _marco_n(resumo: dict, minimo: int) -> int:
    for m in resumo.get("marcos_trofeus", []):
        if m["min"] == minimo:
            return m["n"]
    return 0


def _sugestoes_melhoria(fraco: dict, forte: dict) -> list[str]:
    """Dicas concretas para o jogador mais fraco, a partir dos gaps vs o mais forte."""
    s: list[str] = []
    def g(campo: str) -> int:
        return (forte.get(campo) or 0) - (fraco.get(campo) or 0)
    def fmt(n: int) -> str:
        return f"{n:,}".replace(",", ".")
    # 1) troféus totais
    if g("trofeus") > 0:
        s.append(f"Suba os troféus totais: você tem {fmt(fraco.get('trofeus') or 0)}, "
                 f"{forte['nick']} tem {fmt(forte.get('trofeus') or 0)} (faltam {fmt(g('trofeus'))}).")
    # 2) marco de troféus mais alto onde ainda fica atrás (evita repetir os cumulativos)
    for marco in (2000, 1000, 750, 500, 250):
        gm = _marco_n(forte, marco) - _marco_n(fraco, marco)
        if gm > 0:
            s.append(f"Leve mais {gm} brawler(s) acima de {fmt(marco)} troféus "
                     f"(você tem {_marco_n(fraco, marco)}, ele tem {_marco_n(forte, marco)}).")
            break
    # vitória rápida: brawlers a <50 troféus de um marco
    if (fraco.get("n_quase_marco") or 0) > 0:
        s.append(f"Vitória rápida: você tem {fraco['n_quase_marco']} brawler(s) a menos de "
                 "50 troféus de bater um marco — empurre eles primeiro.")
    # 3) level e ranked
    if g("level") > 0:
        s.append(f"Suba o level da conta (você {fraco.get('level')}, {forte['nick']} {forte.get('level')}).")
    if (fraco.get("ranked_elo") is not None and forte.get("ranked_elo") is not None
            and forte["ranked_elo"] - fraco["ranked_elo"] >= 50):
        s.append(f"Suba no Ranked: você está em {fraco.get('ranked_atual')}, "
                 f"{forte['nick']} em {forte.get('ranked_atual')}.")
    # 4) coleção
    if g("brawlers_liberados") > 0:
        s.append(f"Desbloqueie mais {g('brawlers_liberados')} brawler(s).")
    if g("power11") > 0:
        s.append(f"Suba {g('power11')} brawler(s) ao poder 11.")
    if g("star_powers") > 0:
        s.append(f"Desbloqueie mais {g('star_powers')} poder(es) estrela.")
    if g("gadgets") > 0:
        s.append(f"Desbloqueie mais {g('gadgets')} gadget(s).")
    if g("gears") > 0:
        s.append(f"Fabrique mais {g('gears')} gear(s).")
    if g("hypercharges") > 0:
        s.append(f"Adquira mais {g('hypercharges')} hypercharge(s).")
    # 4) desempenho
    if (fraco.get("winrate") is not None and forte.get("winrate") is not None
            and forte["winrate"] - fraco["winrate"] >= 3):
        s.append(f"Melhore o winrate ({fraco['winrate']}% vs {forte['winrate']}%) — "
                 "jogue seus melhores brawlers por mapa (veja seu perfil).")
    if (fraco.get("star_pct") is not None and forte.get("star_pct") is not None
            and forte["star_pct"] - fraco["star_pct"] >= 3):
        s.append(f"Aumente a taxa de star player ({fraco['star_pct']}% vs {forte['star_pct']}%).")
    if not s:
        s.append("As contas estão bem parelhas — continue jogando! 🎉")
    return s


@app.get("/comparar", response_class=HTMLResponse)
def pagina_comparar(request: Request, a: str | None = None, b: str | None = None):
    """Compara dois jogadores lado a lado (KPIs do banco) + dicas p/ o mais fraco."""
    dados = {"a": None, "b": None}
    erros = {"a": None, "b": None}
    conexao = db.conectar()
    try:
        for raw, slot in ((a, "a"), (b, "b")):
            if not raw:
                continue
            try:
                tag = brawlace.normalizar_tag(raw)
            except brawlace.TagInvalida:
                erros[slot] = "Tag inválida (use #299PGGLQL)."
                continue
            res = db.resumo_comparacao(conexao, tag)
            if res is None:
                erros[slot] = f"{tag} ainda não foi consultado — busque o jogador primeiro."
            else:
                dados[slot] = res
    finally:
        conexao.close()
    sugestoes = fraco_nick = None
    if dados["a"] and dados["b"]:
        ta, tb = dados["a"].get("trofeus") or 0, dados["b"].get("trofeus") or 0
        if ta != tb:
            fraco, forte = (dados["a"], dados["b"]) if ta < tb else (dados["b"], dados["a"])
            fraco_nick = fraco["nick"]
            sugestoes = _sugestoes_melhoria(fraco, forte)
    return templates.TemplateResponse(request, "comparar.html", {
        "a": dados["a"], "b": dados["b"], "tag_a": a or "", "tag_b": b or "",
        "erro_a": erros["a"], "erro_b": erros["b"],
        "totais": imagens.totais_colecao(),
        "sugestoes": sugestoes, "fraco_nick": fraco_nick,
    })


@app.post("/buscar")
def buscar(tag: str = Form(...)):
    try:
        tag_norm: str = brawlace.normalizar_tag(tag)
    except brawlace.TagInvalida:
        return RedirectResponse("/?erro=tag", status_code=303)
    return RedirectResponse(f"/jogador/{tag_norm.lstrip('#')}", status_code=303)


def _seguro(fn):
    """Executa `fn` e devolve None se der qualquer erro — para enriquecimentos
    opcionais (brawltime/brawlytix) que nunca devem derrubar a página."""
    try:
        return fn()
    except Exception:
        return None


def _filtrar_tipo(batalhas: list[dict], filtro: str | None) -> list[dict]:
    """Filtro das abas: 'ranked' = tipo RANKED; 'trofeus' = todo o resto."""
    if filtro == "ranked":
        return [b for b in batalhas if b.get("tipo") == "RANKED"]
    if filtro == "trofeus":
        return [b for b in batalhas if b.get("tipo") != "RANKED"]
    return batalhas


def _consultar(tag: str, filtro_tipo: str | None = None) -> dict:
    """Coleta o perfil pela API OFICIAL (JSON rápido/estável), grava no banco e
    calcula indicadores sobre o histórico acumulado. As 25 batalhas do battlelog
    já vêm no perfil; o histórico extra vem do que o banco acumulou."""
    perfil: dict = oficial.coletar_perfil(tag)
    conexao = db.conectar()
    try:
        gravacao: dict = db.salvar_consulta(conexao, perfil)
        _atualizar_clube(conexao, perfil.get("clube_tag"))
        historico: list[dict] = db.batalhas_do_jogador(conexao, perfil["tag"])
        snapshots: list[dict] = db.snapshots_do_jogador(conexao, perfil["tag"])
        diario: list[dict] = db.historico_diario_do_jogador(conexao, perfil["tag"])
        brawlers_lp: list[dict] = db.historico_brawler_do_jogador(conexao, perfil["tag"])
        brawlers_modo: list[dict] = db.historico_brawler_modo_do_jogador(conexao, perfil["tag"])
        participantes: list[dict] = db.jogadores_das_batalhas(conexao, perfil["tag"])
        brawlers_usados: list[dict] = db.brawlers_usados_do_jogador(conexao, perfil["tag"])
    finally:
        conexao.close()
    historico = _filtrar_tipo(historico, filtro_tipo)
    participantes = _filtrar_tipo(participantes, filtro_tipo)
    perfil = {**perfil, "batalhas": _filtrar_tipo(perfil["batalhas"], filtro_tipo)}
    indicadores: dict = performance.calcular_indicadores(
        historico, perfil["brawlers"], snapshots, diario
    )
    # brawltime/brawlytix são BLOQUEADOS no IP de datacenter da VM → cada chamada
    # esperava o timeout (10s+15s) e travava a página. Como não funcionam no ar,
    # ficam desligados (seções vazias). Ver plano_online.md §Fase 4.
    extra: dict | None = None
    conta: dict | None = None
    correlacao: dict | None = _correlacao_meta(perfil, historico, brawlers_lp,
                                               brawlers_modo)
    tendencias: dict | None = _tendencias_meta_seguro()
    return {
        "perfil": perfil, "gravacao": gravacao,
        "brawlers_usados": brawlers_usados,
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
        db.salvar_clube(conexao, oficial.coletar_clube(clube_tag))
    except (oficial.ErroColeta, oficial.TagInvalida, *db.ErrosBanco):
        pass


def _tendencias_meta_seguro() -> dict | None:
    conexao = db.conectar()
    try:
        return indicadores_meta.tendencias_meta(conexao)
    except db.ErrosBanco:
        return None  # nunca derrubar a página do jogador por causa das tendências
    finally:
        conexao.close()


def _correlacao_meta(perfil: dict, batalhas: list[dict],
                     historico_lp: list[dict] | None = None,
                     historico_modo: list[dict] | None = None) -> dict | None:
    """Meta (do BANCO — o rastreador é quem raspa em 2º plano) + eventos (API
    oficial) + correlação. NÃO raspa ao vivo (isso travava a página ~25s)."""
    conexao = db.conectar()
    try:
        dados_meta: dict = db.meta_do_banco(conexao)
    finally:
        conexao.close()
    if not dados_meta.get("modos"):
        return None
    eventos: list[dict] = _seguro(lambda: oficial.coletar_eventos()) or []
    try:
        correl: dict = indicadores_meta.calcular_meta_jogador(
            dados_meta, eventos, batalhas, perfil["brawlers"], historico_lp,
            historico_modo,
        )
    except Exception:
        return None
    conexao = db.conectar()
    try:
        if correl.get("score"):
            db.salvar_score_meta(conexao, perfil["tag"], correl["score"]["score"])
        correl["evolucao_score"] = db.historico_score_meta(conexao, perfil["tag"])
    except db.ErrosBanco:
        pass
    finally:
        conexao.close()
    return correl


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
        brawlers_usados: list[dict] = db.brawlers_usados_do_jogador(conexao, tag_norm)
    finally:
        conexao.close()
    historico = _filtrar_tipo(historico, filtro_tipo)
    participantes = _filtrar_tipo(participantes, filtro_tipo)
    perfil["batalhas"] = _filtrar_tipo(perfil["batalhas"], filtro_tipo)
    indicadores: dict = performance.calcular_indicadores(
        historico, perfil["brawlers"], snapshots, diario
    )
    extra: dict | None = None   # brawltime bloqueado na VM (ver _consultar)
    conta: dict | None = None   # brawlytix idem
    correlacao: dict | None = _correlacao_meta(perfil, historico, brawlers_lp,
                                               brawlers_modo)
    return {
        "perfil": perfil,
        "gravacao": {"batalhas_novas": 0, "total_batalhas": len(historico)},
        "brawlers_usados": brawlers_usados,
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
    except (oficial.TagInvalida, brawlace.TagInvalida) as erro:
        return templates.TemplateResponse(
            request, "erro.html", {"mensagem": str(erro)}, status_code=404
        )
    except (oficial.ErroColeta, brawlace.ErroColeta) as erro:
        return templates.TemplateResponse(
            request, "erro.html", {"mensagem": f"Fonte de dados indisponível: {erro}"},
            status_code=502,
        )
    return templates.TemplateResponse(request, "jogador.html", dados)


@app.post("/api/refrescar/{tag}")
def api_refrescar(tag: str):
    """Scraping + gravação em segundo plano (chamado pelo JS da página)."""
    try:
        dados: dict = _consultar(tag)
    except (oficial.TagInvalida, brawlace.TagInvalida) as erro:
        return JSONResponse({"erro": str(erro)}, status_code=404)
    except (oficial.ErroColeta, brawlace.ErroColeta) as erro:
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
    except (oficial.TagInvalida, brawlace.TagInvalida) as erro:
        return JSONResponse({"erro": str(erro)}, status_code=404)
    except (oficial.ErroColeta, brawlace.ErroColeta) as erro:
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
                   GROUP BY bj.tag_jogador HAVING COUNT(*) >= 3
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
            try:
                _cache_acess[brawler_nome] = brawltime.coletar_acessorios_brawler(brawler_nome)
            except Exception:
                _cache_acess[brawler_nome] = None  # nunca derrubar o Jogar agora
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
