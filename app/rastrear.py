"""Rastreamento automático — consulta todos os jogadores já vistos e acumula
batalhas novas no banco. Executado pelo Agendador de Tarefas do Windows a cada
2 h (tarefa 'ApiDoBrawl_Rastreio'). Rodar manual: python -m app.rastrear
"""
from datetime import datetime
from pathlib import Path

from app import db
from app.coleta import brawlace

ARQUIVO_LOG: Path = Path(__file__).resolve().parents[1] / "data" / "rastreio.log"


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
        tags: list[str] = [
            linha["tag"] for linha in conexao.execute("SELECT tag FROM jogadores")
        ]
        if not tags:
            _log("nenhum jogador no banco ainda — nada a rastrear")
            return
        for tag in tags:
            try:
                perfil: dict = brawlace.coletar_perfil(tag)
                resultado: dict = db.salvar_consulta(conexao, perfil)
                if perfil.get("clube_tag"):
                    try:
                        db.salvar_clube(conexao, brawlace.coletar_clube(perfil["clube_tag"]))
                    except (brawlace.ErroColeta, brawlace.ErroParsing):
                        pass
                extras: int = 0
                for modo in brawlace.MODOS_BATTLELOG:
                    try:
                        batalhas_modo = brawlace.coletar_battlelog_modo(tag, modo)
                        extras += db.salvar_batalhas(conexao, perfil["tag"], batalhas_modo)
                    except (brawlace.ErroColeta, brawlace.ErroParsing):
                        continue
                conexao.commit()
                _log(
                    f"{tag} ({perfil['nick']}): +{resultado['batalhas_novas']} batalhas "
                    f"+{extras} por modo (total {resultado['total_batalhas'] + extras})"
                )
            except (brawlace.TagInvalida, brawlace.ErroColeta, brawlace.ErroParsing) as erro:
                _log(f"{tag}: ERRO — {erro}")

        # snapshot do meta (cache 6 h — barato) para alimentar as tendências
        try:
            novas_meta: int = db.salvar_meta(conexao, brawlace.coletar_meta())
            _log(f"meta: +{novas_meta} linhas em meta_snapshots")
        except (brawlace.ErroColeta, brawlace.ErroParsing) as erro:
            _log(f"meta: ERRO — {erro}")
    finally:
        conexao.close()


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
