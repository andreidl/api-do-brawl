"""Rastreamento automático — consulta todos os jogadores já vistos e acumula
batalhas novas no banco. Executado pelo Agendador de Tarefas do Windows a cada
2 h (tarefa 'ApiDoBrawl_Rastreio'). Rodar manual: python -m app.rastrear
"""
from datetime import datetime
from pathlib import Path

from app import db
from app.coleta import brawlace, oficial

ARQUIVO_LOG: Path = Path(__file__).resolve().parents[1] / "data" / "rastreio.log"

# Membros reais do clã Snake que rastreamos SEMPRE — mesmo antes de alguém abrir
# o perfil deles no app. Assim os jogos EM DUPLA com eles são capturados também
# pela janela de 25 partidas DELES, não só pela do dono da consulta (ver §"jogos
# juntos"). Rastrear o roster inteiro (~30) seria crawl em massa e fere a regra
# "só a tag consultada" do CLAUDE.md §3.5 — aqui ficam só os usuários reais.
TAGS_CLA_FIXAS: list[str] = [
    "#299PGGLQL",   # SNK | andreidl (dono)
    "#9029RVG2J",   # SNK | BIGBOSS
    "#28GY9QJVC",   # SNK|gustavo
    "#2QLLLGV0R0",  # SNK |camilacgs
    "#89R22LV2Y",   # LoganKL
]


def _log(mensagem: str) -> None:
    linha: str = f"{datetime.now().isoformat(timespec='seconds')} {mensagem}"
    print(linha)
    ARQUIVO_LOG.parent.mkdir(parents=True, exist_ok=True)
    with ARQUIVO_LOG.open("a", encoding="utf-8") as arquivo:
        arquivo.write(linha + "\n")


def rastrear_uma_vez() -> None:
    """Uma rodada completa de rastreamento — chamada pelo CLI e pela thread
    de rastreio embutida no app (app.main)."""
    conexao = db.conectar()
    try:
        tags_banco: list[str] = [
            linha["tag"] for linha in conexao.execute("SELECT tag FROM jogadores")
        ]
        # união preservando ordem: primeiro os fixos do clã, depois o resto do banco
        tags: list[str] = list(dict.fromkeys(TAGS_CLA_FIXAS + tags_banco))
        if not tags:
            _log("nenhum jogador no banco ainda — nada a rastrear")
            return
        for tag in tags:
            try:
                perfil: dict = oficial.coletar_perfil(tag)
                resultado: dict = db.salvar_consulta(conexao, perfil)
                if perfil.get("clube_tag"):
                    try:
                        db.salvar_clube(conexao, oficial.coletar_clube(perfil["clube_tag"]))
                    except (oficial.ErroColeta, oficial.TagInvalida):
                        pass
                conexao.commit()
                _log(
                    f"{tag} ({perfil['nick']}): +{resultado['batalhas_novas']} batalhas "
                    f"(total {resultado['total_batalhas']})"
                )
            except (oficial.TagInvalida, oficial.ErroColeta) as erro:
                _log(f"{tag}: ERRO — {erro}")

        # snapshot do meta (cache 6 h — barato) para alimentar as tendências
        try:
            novas_meta: int = db.salvar_meta(conexao, brawlace.coletar_meta())
            _log(f"meta: +{novas_meta} linhas em meta_snapshots")
        except (brawlace.ErroColeta, brawlace.ErroParsing) as erro:
            _log(f"meta: ERRO — {erro}")
    finally:
        conexao.close()


def rastrear_membros_cla() -> dict:
    """Atualiza SÓ os membros fixos do clã (perfil via API oficial) — usado pelo
    refresh sob demanda ao abrir a /cla. Retorna {membros, batalhas_novas}."""
    conexao = db.conectar()
    total: int = 0
    n: int = 0
    try:
        for tag in TAGS_CLA_FIXAS:
            try:
                perfil = oficial.coletar_perfil(tag)
                res = db.salvar_consulta(conexao, perfil)
                if perfil.get("clube_tag"):
                    try:
                        db.salvar_clube(conexao, oficial.coletar_clube(perfil["clube_tag"]))
                    except (oficial.ErroColeta, oficial.TagInvalida):
                        pass
                conexao.commit()
                total += res["batalhas_novas"]
                n += 1
            except (oficial.TagInvalida, oficial.ErroColeta) as erro:
                _log(f"{tag}: ERRO refresh /cla — {erro}")
    finally:
        conexao.close()
    return {"membros": n, "batalhas_novas": total}


def ultima_rodada() -> str | None:
    """Última linha do log de rastreio (para exibir status na home)."""
    try:
        linhas = ARQUIVO_LOG.read_text(encoding="utf-8").strip().splitlines()
        return linhas[-1] if linhas else None
    except OSError:
        return None


def main() -> None:
    rastrear_uma_vez()


if __name__ == "__main__":
    main()
