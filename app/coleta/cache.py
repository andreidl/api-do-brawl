"""Cache de requisições em disco com TTL (regra obrigatória do CLAUDE.md §3.5)."""
import hashlib
import time
from pathlib import Path

DIR_CACHE: Path = Path(__file__).resolve().parents[2] / "data" / "cache"


def _caminho(chave: str) -> Path:
    nome: str = hashlib.sha1(chave.encode("utf-8")).hexdigest() + ".html"
    return DIR_CACHE / nome


def obter(chave: str, ttl_segundos: int) -> str | None:
    """Retorna o conteúdo cacheado se ainda estiver dentro do TTL, senão None."""
    arquivo: Path = _caminho(chave)
    if not arquivo.exists():
        return None
    idade: float = time.time() - arquivo.stat().st_mtime
    if idade > ttl_segundos:
        return None
    return arquivo.read_text(encoding="utf-8")


def salvar(chave: str, conteudo: str) -> None:
    DIR_CACHE.mkdir(parents=True, exist_ok=True)
    _caminho(chave).write_text(conteudo, encoding="utf-8")
