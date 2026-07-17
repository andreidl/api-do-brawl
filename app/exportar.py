"""Exporta o app como SITE ESTÁTICO para GitHub Pages (pasta docs/).

Roda no PC do usuário (onde o scraping funciona). Gera uma "foto" navegável:
home + página de cada jogador + Jogar agora do dono. CSS embutido, links
reescritos para arquivos .html, interatividade (busca/refresh/montar time)
neutralizada — essas ficam só na versão local.

Uso: python -m app.exportar [#TAG_DO_DONO]
"""
import re
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from app import db
from app.main import app

RAIZ: Path = Path(__file__).resolve().parents[1]
DOCS: Path = RAIZ / "docs"
DONO_PADRAO: str = "#299PGGLQL"


def _slug(tag: str) -> str:
    return tag.lstrip("#")


def _pos_processar(html: str, css: str, mapa_links: dict[str, str]) -> str:
    html = html.replace(
        '<link rel="stylesheet" href="/static/estilo.css">', f"<style>{css}</style>"
    )
    # remove scripts (refresh automático não funciona estático)
    html = re.sub(r"<script>.*?</script>", "", html, flags=re.S)
    # neutraliza formulários interativos
    html = re.sub(
        r'<form[^>]*class="busca".*?</form>',
        '<p class="nota">🔒 Busca de tag nova só na versão local (esta é uma foto do clã).</p>',
        html, flags=re.S,
    )
    html = re.sub(r'<form[^>]*class="time-form".*?</form>', "", html, flags=re.S)
    # reescreve links conhecidos para .html
    for de, para in mapa_links.items():
        html = html.replace(f'href="{de}"', f'href="{para}"')
    # qualquer link interno restante (abas ?tipo=, etc.) vira inerte
    html = re.sub(r'href="/[^"]*"', 'href="#"', html)
    # aviso de "foto"
    html = html.replace(
        "<main>",
        '<main><p class="nota" style="text-align:center">📸 Foto do clã — '
        'atualizada quando o dono publica. Versão ao vivo roda no PC dele.</p>',
        1,
    )
    return html


def exportar(dono: str = DONO_PADRAO) -> None:
    DOCS.mkdir(exist_ok=True)
    cliente = TestClient(app)
    css: str = cliente.get("/static/estilo.css").text

    conexao = db.conectar()
    try:
        jogadores = [dict(r) for r in conexao.execute("SELECT tag, nick FROM jogadores")]
    finally:
        conexao.close()

    mapa: dict[str, str] = {"/": "index.html"}
    for j in jogadores:
        s = _slug(j["tag"])
        mapa[f"/jogador/{s}"] = f"jogador_{s}.html"
    # só o dono tem página "Jogar agora" estática; os demais links viram inertes
    mapa[f"/jogar/{_slug(dono)}"] = f"jogar_{_slug(dono)}.html"

    def salvar(rota: str, arquivo: str) -> bool:
        r = cliente.get(rota)
        if r.status_code != 200:
            print(f"  pulado {rota} (HTTP {r.status_code})")
            return False
        (DOCS / arquivo).write_text(_pos_processar(r.text, css, mapa), encoding="utf-8")
        return True

    print("Exportando home...")
    salvar("/", "index.html")
    for j in jogadores:
        s = _slug(j["tag"])
        print(f"Exportando {j['nick']}...")
        salvar(f"/jogador/{s}", f"jogador_{s}.html")

    print(f"Exportando Jogar agora do dono ({dono})...")
    if not salvar(f"/jogar/{_slug(dono)}", f"jogar_{_slug(dono)}.html"):
        print("  (Jogar agora precisa dos eventos ao vivo — rode com internet no PC)")

    (DOCS / ".nojekyll").write_text("", encoding="utf-8")
    print(f"\nPronto! {len(list(DOCS.glob('*.html')))} páginas em {DOCS}")
    print("Publique com: git add docs && git commit -m site && git push")


if __name__ == "__main__":
    exportar(sys.argv[1] if len(sys.argv) > 1 else DONO_PADRAO)
