"""Cache de requisições em disco com TTL (regra obrigatória do CLAUDE.md §3.5)."""
import hashlib
import os
import time
from pathlib import Path

DIR_CACHE: Path = Path(__file__).resolve().parents[2] / "data" / "cache"


def _caminho(chave: str) -> Path:
    nome: str = hashlib.sha1(chave.encode("utf-8")).hexdigest() + ".html"
    return DIR_CACHE / nome


def obter(chave: str, ttl_segundos: int) -> str | None:
    """Retorna o conteúdo cacheado se ainda estiver dentro do TTL, senão None.

    Leitura tolerante: se o arquivo sumir/corromper entre o stat e a leitura
    (escrita concorrente), retorna None em vez de estourar.
    """
    arquivo: Path = _caminho(chave)
    try:
        idade: float = time.time() - arquivo.stat().st_mtime
        if idade > ttl_segundos:
            return None
        return arquivo.read_text(encoding="utf-8")
    except OSError:
        return None


def salvar(chave: str, conteudo: str) -> None:
    """Escrita ATÔMICA (tmp + rename) — leitores concorrentes nunca veem HTML
    parcial, e o rastreio embutido pode escrever em paralelo com requests."""
    DIR_CACHE.mkdir(parents=True, exist_ok=True)
    destino: Path = _caminho(chave)
    tmp: Path = destino.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(conteudo, encoding="utf-8")
    os.replace(tmp, destino)
