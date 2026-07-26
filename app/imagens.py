"""URLs de imagem dos brawlers (e acessórios) via CDN público do Brawlify.

O mapa nome→id vem da API OFICIAL (`/brawlers`), cacheado em memória. As imagens
carregam no NAVEGADOR do visitante (o servidor só monta a URL), então o bloqueio
de IP de datacenter não afeta. Se o mapa não carregar (API fora), as funções
devolvem "" e os templates simplesmente mostram só o nome — nada quebra.
"""
from app.coleta import oficial

CDN = "https://cdn.brawlify.com"

_mapa_brawler: dict | None = None   # {NOME_NORMALIZADO: id}
_mapa_sp: dict | None = None        # {NOME_NORMALIZADO: id} star powers
_mapa_gadget: dict | None = None    # {NOME_NORMALIZADO: id} gadgets
_totais: dict | None = None         # totais disponíveis no jogo (denominadores)


def _norm(nome: str) -> str:
    return (nome or "").strip().upper()


def _carregar() -> None:
    global _mapa_brawler, _mapa_sp, _mapa_gadget, _totais
    if _mapa_brawler is not None:
        return
    b_map, sp_map, g_map = {}, {}, {}
    tot = {"brawlers": 0, "star_powers": 0, "gadgets": 0}
    try:
        for b in oficial.coletar_brawlers():
            if b.get("id") and b.get("name"):
                b_map[_norm(b["name"])] = b["id"]
                tot["brawlers"] += 1
            sps = b.get("star_powers", [])
            tot["star_powers"] += len(sps)
            for s in sps:
                if s.get("id") and s.get("name"):
                    sp_map[_norm(s["name"])] = s["id"]
            gds = b.get("gadgets", [])
            tot["gadgets"] += len(gds)
            for g in gds:
                if g.get("id") and g.get("name"):
                    g_map[_norm(g["name"])] = g["id"]
    except Exception:
        pass  # API fora / sem token → mapas vazios (templates mostram só o nome)
    _mapa_brawler, _mapa_sp, _mapa_gadget, _totais = b_map, sp_map, g_map, tot


def totais_colecao() -> dict:
    """Totais disponíveis no jogo (da API oficial) p/ os denominadores da
    comparação: {brawlers, star_powers, gadgets}. 0 se o mapa não carregou."""
    _carregar()
    return dict(_totais or {"brawlers": 0, "star_powers": 0, "gadgets": 0})


def img_brawler(nome: str) -> str:
    _carregar()
    bid = _mapa_brawler.get(_norm(nome))
    return f"{CDN}/brawlers/borderless/{bid}.png" if bid else ""


def img_star_power(nome: str) -> str:
    _carregar()
    sid = _mapa_sp.get(_norm(nome))
    return f"{CDN}/star-powers/borderless/{sid}.png" if sid else ""


def img_gadget(nome: str) -> str:
    _carregar()
    gid = _mapa_gadget.get(_norm(nome))
    return f"{CDN}/gadgets/borderless/{gid}.png" if gid else ""


def recarregar() -> int:
    """Força recarregar o mapa (ex.: no startup). Retorna nº de brawlers no mapa."""
    global _mapa_brawler
    _mapa_brawler = None
    _carregar()
    return len(_mapa_brawler or {})
