"""Import único: copia o `data/brawl.db` (SQLite) para o Postgres (Supabase).

Preserva TODO o histórico já acumulado (batalhas globais, snapshots, meta,
histórico Brawlify, clube). Estratégia: truncate-then-load — espelha o SQLite
no Postgres de forma idempotente (pode rodar de novo sem duplicar).

Uso:
    # com DATABASE_URL no .env ou no ambiente:
    python -m app.importar_para_postgres            # aborta se o PG já tiver dados
    python -m app.importar_para_postgres --forcar   # sobrescreve o que houver

As colunas `id` (seriais) de snapshots/meta_snapshots NÃO são copiadas —
o Postgres as regera (nada as referencia).
"""
import sqlite3
import sys
from pathlib import Path

from app import db

# Ordem lógica (sem FKs reforçadas, mas mantém legível). id serial é omitido.
TABELAS: list[str] = [
    "jogadores",
    "clubes",
    "clube_membros",
    "batalhas",
    "batalha_jogadores",
    "snapshots",
    "meta_snapshots",
    "historico_diario",
    "historico_brawler",
    "historico_brawler_modo",
    "score_meta_historico",
]
_COLUNAS_IGNORADAS: set[str] = {"id"}  # seriais regerados pelo Postgres


def _colunas_sqlite(sq: sqlite3.Connection, tabela: str) -> list[str]:
    return [
        linha[1]
        for linha in sq.execute(f"PRAGMA table_info({tabela})").fetchall()
        if linha[1] not in _COLUNAS_IGNORADAS
    ]


def _total_no_postgres(pg, tabelas: list[str]) -> int:
    total = 0
    for t in tabelas:
        total += pg.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"]
    return total


def importar(forcar: bool = False) -> None:
    if db._database_url() is None:
        raise SystemExit("DATABASE_URL não definida — nada para importar (modo SQLite).")
    if not Path(db.CAMINHO_BANCO).exists():
        raise SystemExit(f"SQLite não encontrado: {db.CAMINHO_BANCO}")

    sq = sqlite3.connect(db.CAMINHO_BANCO)
    sq.row_factory = sqlite3.Row
    pg = db.conectar()  # DATABASE_URL presente → Postgres
    db.garantir_schema_pg(pg)  # cria as tabelas se ainda não existirem

    try:
        existentes = _total_no_postgres(pg, TABELAS)
        if existentes and not forcar:
            raise SystemExit(
                f"O Postgres já tem {existentes} linhas nas tabelas-alvo. "
                "Rode com --forcar para sobrescrever (truncate + reimport)."
            )

        # Zera as tabelas-alvo numa transação (CASCADE p/ resolver dependências).
        pg.execute("TRUNCATE " + ", ".join(TABELAS) + " RESTART IDENTITY CASCADE")

        total = 0
        for tabela in TABELAS:
            colunas = _colunas_sqlite(sq, tabela)
            linhas = sq.execute(f"SELECT * FROM {tabela}").fetchall()
            if not linhas:
                print(f"  {tabela:24} 0")
                continue
            placeholders = ", ".join(["?"] * len(colunas))
            sql = (f"INSERT INTO {tabela} ({', '.join(colunas)}) "
                   f"VALUES ({placeholders}) ON CONFLICT DO NOTHING")
            dados = [tuple(linha[c] for c in colunas) for linha in linhas]
            pg.executemany(sql, dados)
            print(f"  {tabela:24} {len(dados)}")
            total += len(dados)

        pg.commit()
        conferido = _total_no_postgres(pg, TABELAS)
        print(f"\nImport concluído: {total} linhas copiadas; "
              f"{conferido} linhas no Postgres agora.")
    finally:
        sq.close()
        pg.close()


def main() -> None:
    importar(forcar="--forcar" in sys.argv[1:])


if __name__ == "__main__":
    main()
