"""Persistência — schema e gravação (CLAUDE.md §6).

Dois backends com o MESMO código de acesso:
- **SQLite** (dev/local): `data/brawl.db`. É o padrão quando `DATABASE_URL`
  está ausente, e SEMPRE quando `conectar()` recebe um caminho (usado pelos testes).
- **Postgres** (produção/online): quando a env `DATABASE_URL` está definida e
  nenhum caminho é passado. Um wrapper (`_ConexaoPG`) imita a fatia da API do
  sqlite3.Connection que o app usa e traduz os placeholders `?` → `%s`.

A SQL das funções é escrita de forma portável (padrão `ON CONFLICT`, `CASE` no
lugar de `MAX(a,b)`, sem alias em `HAVING`) para rodar igual nos dois bancos.
"""
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

try:  # psycopg é opcional no dev SQLite; obrigatório só no modo Postgres
    import psycopg
    from psycopg.rows import dict_row as _dict_row
except ImportError:  # pragma: no cover - ambiente sem Postgres
    psycopg = None
    _dict_row = None

CAMINHO_BANCO: Path = Path(__file__).resolve().parents[1] / "data" / "brawl.db"
_RAIZ: Path = Path(__file__).resolve().parents[1]

# Exceções de banco para os except do app cobrirem os DOIS backends.
ErrosBanco: tuple = (sqlite3.Error,) + ((psycopg.Error,) if psycopg else ())


def _database_url() -> str | None:
    """URL do Postgres via env `DATABASE_URL`, com fallback pro `.env` local (dev).

    Mesmo padrão do `oficial.py`: em produção use variável de ambiente; no dev
    dá pra deixar no `.env` (gitignored). Ausente/vazia = modo SQLite.
    """
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        env = _RAIZ / ".env"
        if env.exists():
            for linha in env.read_text(encoding="utf-8").splitlines():
                if linha.strip().startswith("#") or "=" not in linha:
                    continue
                k, _, v = linha.partition("=")
                if k.strip() == "DATABASE_URL":
                    url = v.strip()
                    break
    return url or None


def _traduzir_sql(sql: str, tem_params: bool) -> str:
    """Converte a SQL portável (placeholders `?`) para o dialeto do psycopg (`%s`).

    Só escapa `%` → `%%` quando há params (aí o psycopg faz a interpolação e
    des-escapa); sem params o `%` literal é mandado como está.
    """
    if tem_params:
        sql = sql.replace("%", "%%")
    return sql.replace("?", "%s")


class _ConexaoPG:
    """Fatia da API do sqlite3.Connection que o app usa, sobre um psycopg.Connection."""

    def __init__(self, conn) -> None:
        self._conn = conn

    def execute(self, sql: str, params: tuple = ()):
        return self._conn.execute(_traduzir_sql(sql, bool(params)), params or None)

    def executemany(self, sql: str, seq) -> None:
        seq = list(seq)
        cur = self._conn.cursor()
        cur.executemany(_traduzir_sql(sql, True), seq)

    def executescript(self, sql: str) -> None:
        # psycopg não tem executescript; roda cada statement separado.
        for stmt in sql.split(";"):
            if stmt.strip():
                self._conn.execute(stmt)

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        self._conn.close()


_SCHEMA: str = """
CREATE TABLE IF NOT EXISTS jogadores (
  tag TEXT PRIMARY KEY,
  nick TEXT,
  primeiro_visto TEXT,
  ultimo_visto TEXT
);
CREATE TABLE IF NOT EXISTS snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tag TEXT REFERENCES jogadores(tag),
  criado_em TEXT,
  trofeus INTEGER, trofeus_max INTEGER, level INTEGER,
  vitorias_3v3 INTEGER, vitorias_solo INTEGER, vitorias_duo INTEGER,
  ranked_atual TEXT, ranked_max TEXT,
  win_streak_max INTEGER,
  brawlers_json TEXT
);
-- UMA linha por batalha FÍSICA (o hash do brawlace é global: a mesma partida
-- tem o mesmo hash em qualquer perfil). Dados por jogador ficam em
-- batalha_jogadores — assim consultar um jogador alimenta o histórico de todos
-- os participantes conhecidos.
CREATE TABLE IF NOT EXISTS batalhas (
  hash TEXT PRIMARY KEY,
  ocorrida_em TEXT,
  modo TEXT,
  tipo TEXT,
  mapa TEXT,
  duracao_seg INTEGER,
  time_vencedor INTEGER            -- índice do time que venceu (NULL: draw/showdown/desconhecido)
);
CREATE TABLE IF NOT EXISTS meta_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  data TEXT, modo TEXT, brawler TEXT,
  star_player_pct REAL, posicao INTEGER
);
CREATE TABLE IF NOT EXISTS historico_diario (
  tag TEXT, data TEXT, batalhas INTEGER, vitorias INTEGER, derrotas INTEGER,
  trofeus_delta INTEGER, trofeus_fim INTEGER, brawlers_json TEXT,
  fonte TEXT DEFAULT 'brawlify',
  PRIMARY KEY (tag, data)
);
CREATE TABLE IF NOT EXISTS historico_brawler (
  tag TEXT, brawler TEXT, jogos INTEGER, vitorias INTEGER, derrotas INTEGER,
  empates INTEGER, winrate_pct REAL, trofeus_delta INTEGER,
  fonte TEXT DEFAULT 'brawlify',
  PRIMARY KEY (tag, brawler, fonte)
);
CREATE TABLE IF NOT EXISTS historico_brawler_modo (
  tag TEXT, brawler TEXT, modo TEXT, vitorias INTEGER, derrotas INTEGER,
  empates INTEGER, trofeus_delta INTEGER,
  PRIMARY KEY (tag, brawler, modo)
);
CREATE TABLE IF NOT EXISTS batalha_jogadores (
  hash TEXT,                     -- REFERENCES batalhas(hash)
  tag_jogador TEXT,              -- tag do participante
  nick TEXT,
  brawler TEXT,
  power INTEGER,
  trofeus INTEGER,
  time INTEGER,                  -- índice do painel/time no card (NULL se desconhecido)
  resultado TEXT,                -- Victory/Defeat/Draw/Rank N DESTE jogador (NULL se desconhecido)
  trofeus_delta INTEGER,         -- só conhecido para o jogador consultado
  star_player INTEGER,
  rank INTEGER,                  -- colocação em showdown (só do consultado)
  PRIMARY KEY (hash, tag_jogador)
);
CREATE INDEX IF NOT EXISTS idx_bj_tag ON batalha_jogadores (tag_jogador);
CREATE TABLE IF NOT EXISTS clubes (
  clube_tag TEXT PRIMARY KEY,
  nome TEXT,
  atualizado_em TEXT
);
CREATE TABLE IF NOT EXISTS clube_membros (
  clube_tag TEXT REFERENCES clubes(clube_tag),
  tag TEXT,
  nick TEXT,
  PRIMARY KEY (clube_tag, tag)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_meta_snapshot
  ON meta_snapshots (data, modo, brawler);
-- 1 ponto por dia: o score vs meta do jogador ao longo do tempo
CREATE TABLE IF NOT EXISTS score_meta_historico (
  tag TEXT, dia TEXT, score REAL,
  PRIMARY KEY (tag, dia)
);
"""


# Schema Postgres: mesmas tabelas, com IDENTITY no lugar de AUTOINCREMENT e sem
# FKs (o SQLite não as reforça por padrão; batalha_jogadores tem tags que não
# estão em `jogadores`, então FK reforçada quebraria). Tipos alargados p/ BIGINT.
_SCHEMA_PG: str = """
CREATE TABLE IF NOT EXISTS jogadores (
  tag TEXT PRIMARY KEY,
  nick TEXT,
  primeiro_visto TEXT,
  ultimo_visto TEXT
);
CREATE TABLE IF NOT EXISTS snapshots (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  tag TEXT,
  criado_em TEXT,
  trofeus BIGINT, trofeus_max BIGINT, level BIGINT,
  vitorias_3v3 BIGINT, vitorias_solo BIGINT, vitorias_duo BIGINT,
  ranked_atual TEXT, ranked_max TEXT,
  win_streak_max BIGINT,
  brawlers_json TEXT
);
CREATE TABLE IF NOT EXISTS batalhas (
  hash TEXT PRIMARY KEY,
  ocorrida_em TEXT,
  modo TEXT,
  tipo TEXT,
  mapa TEXT,
  duracao_seg BIGINT,
  time_vencedor BIGINT
);
CREATE TABLE IF NOT EXISTS meta_snapshots (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  data TEXT, modo TEXT, brawler TEXT,
  star_player_pct DOUBLE PRECISION, posicao BIGINT
);
CREATE TABLE IF NOT EXISTS historico_diario (
  tag TEXT, data TEXT, batalhas BIGINT, vitorias BIGINT, derrotas BIGINT,
  trofeus_delta BIGINT, trofeus_fim BIGINT, brawlers_json TEXT,
  fonte TEXT DEFAULT 'brawlify',
  PRIMARY KEY (tag, data)
);
CREATE TABLE IF NOT EXISTS historico_brawler (
  tag TEXT, brawler TEXT, jogos BIGINT, vitorias BIGINT, derrotas BIGINT,
  empates BIGINT, winrate_pct DOUBLE PRECISION, trofeus_delta BIGINT,
  fonte TEXT DEFAULT 'brawlify',
  PRIMARY KEY (tag, brawler, fonte)
);
CREATE TABLE IF NOT EXISTS historico_brawler_modo (
  tag TEXT, brawler TEXT, modo TEXT, vitorias BIGINT, derrotas BIGINT,
  empates BIGINT, trofeus_delta BIGINT,
  PRIMARY KEY (tag, brawler, modo)
);
CREATE TABLE IF NOT EXISTS batalha_jogadores (
  hash TEXT,
  tag_jogador TEXT,
  nick TEXT,
  brawler TEXT,
  power BIGINT,
  trofeus BIGINT,
  time BIGINT,
  resultado TEXT,
  trofeus_delta BIGINT,
  star_player BIGINT,
  rank BIGINT,
  PRIMARY KEY (hash, tag_jogador)
);
CREATE INDEX IF NOT EXISTS idx_bj_tag ON batalha_jogadores (tag_jogador);
CREATE TABLE IF NOT EXISTS clubes (
  clube_tag TEXT PRIMARY KEY,
  nome TEXT,
  atualizado_em TEXT
);
CREATE TABLE IF NOT EXISTS clube_membros (
  clube_tag TEXT,
  tag TEXT,
  nick TEXT,
  PRIMARY KEY (clube_tag, tag)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_meta_snapshot
  ON meta_snapshots (data, modo, brawler);
CREATE TABLE IF NOT EXISTS score_meta_historico (
  tag TEXT, dia TEXT, score DOUBLE PRECISION,
  PRIMARY KEY (tag, dia)
);
"""


def conectar(caminho: Path | None = None):
    """Abre a conexão. Postgres se `DATABASE_URL` estiver setada e nenhum caminho
    for passado; senão SQLite. Passar `caminho` força SQLite (usado nos testes)."""
    if caminho is None:
        url = _database_url()
        if url:
            return _conectar_postgres(url)
    caminho = caminho or CAMINHO_BANCO
    caminho.parent.mkdir(parents=True, exist_ok=True)
    # timeout: com o rastreio embutido escrevendo em paralelo, uma escrita
    # concorrente ESPERA a vez em vez de estourar "database is locked"
    conexao = sqlite3.connect(caminho, timeout=30.0)
    conexao.row_factory = sqlite3.Row
    conexao.execute("PRAGMA journal_mode=WAL")   # leituras nunca bloqueiam
    conexao.execute("PRAGMA busy_timeout=30000")
    _migrar_para_batalhas_globais(conexao)
    conexao.executescript(_SCHEMA)
    _reparar_showdown_mal_parseado(conexao)
    _reclassificar_tipo_por_delta(conexao)
    if "rank" not in _colunas(conexao, "batalha_jogadores"):
        conexao.execute("ALTER TABLE batalha_jogadores ADD COLUMN rank INTEGER")
        conexao.commit()
    # migração leve: snapshots antigos sem colunas de ranked
    if "ranked_atual" not in _colunas(conexao, "snapshots"):
        conexao.execute("ALTER TABLE snapshots ADD COLUMN ranked_atual TEXT")
        conexao.execute("ALTER TABLE snapshots ADD COLUMN ranked_max TEXT")
        conexao.commit()
    if "win_streak_max" not in _colunas(conexao, "snapshots"):
        conexao.execute("ALTER TABLE snapshots ADD COLUMN win_streak_max INTEGER")
        conexao.commit()
    return conexao


def _conectar_postgres(url: str) -> _ConexaoPG:
    """Só abre a conexão — SEM DDL/migração. Rodar schema/UPDATE a cada conexão
    pegaria lock e seria lento (é 1 conexão por request). O schema é garantido
    UMA vez por `garantir_schema_pg` (no import e no startup do app)."""
    if psycopg is None:
        raise RuntimeError("DATABASE_URL definida mas psycopg não está instalado "
                           "(pip install 'psycopg[binary]')")
    return _ConexaoPG(psycopg.connect(url, row_factory=_dict_row))


def garantir_schema_pg(conexao: _ConexaoPG) -> None:
    """Cria o schema Postgres se ainda não existir + roda a reclassificação uma
    única vez. Deve rodar só no import e no startup do app — NUNCA a cada conexão
    (o DDL e o UPDATE pegam lock; sob concorrência causam timeout)."""
    existe = conexao.execute(
        "SELECT to_regclass('public.jogadores') AS t"
    ).fetchone()["t"]
    if existe is None:
        conexao.executescript(_SCHEMA_PG)
        conexao.commit()
    _reclassificar_tipo_por_delta(conexao)  # SQL portável; no-op se nada a mudar


def _colunas(conexao: sqlite3.Connection, tabela: str) -> list[str]:
    return [l[1] for l in conexao.execute(f"PRAGMA table_info({tabela})").fetchall()]


def _tabela_existe(conexao: sqlite3.Connection, tabela: str) -> bool:
    return conexao.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (tabela,)
    ).fetchone() is not None


def _migrar_para_batalhas_globais(conexao: sqlite3.Connection) -> None:
    """Migra o schema antigo (batalhas por dono) para o global (uma linha por
    batalha física + participantes em batalha_jogadores).

    RESUMÍVEL: se um crash interromper no meio, os dados ficam preservados em
    batalhas_antigas/bj_antigas e a cópia (idempotente) recomeça na reconexão.
    """
    precisa_renomear: bool = "tag" in _colunas(conexao, "batalhas")
    tem_orfao: bool = _tabela_existe(conexao, "batalhas_antigas")
    if not precisa_renomear and not tem_orfao:
        return  # já migrado (ou banco novo)

    if precisa_renomear:
        # executescript comita implicitamente — mas os dados antigos já estão
        # a salvo em *_antigas; a cópia abaixo é idempotente e resumível.
        conexao.execute("ALTER TABLE batalhas RENAME TO batalhas_antigas")
        if "aliado" in _colunas(conexao, "batalha_jogadores"):
            conexao.execute("ALTER TABLE batalha_jogadores RENAME TO bj_antigas")
        conexao.executescript(_SCHEMA)

    tem_bj: bool = _tabela_existe(conexao, "bj_antigas")
    for antiga in conexao.execute("SELECT * FROM batalhas_antigas").fetchall():
        resultado: str | None = antiga["resultado"]
        # convenção da migração: time 0 = time do dono da consulta antiga
        vencedor: int | None = {"Victory": 0, "Defeat": 1}.get(resultado or "")
        conexao.execute(
            """INSERT OR IGNORE INTO batalhas
               (hash, ocorrida_em, modo, tipo, mapa, duracao_seg, time_vencedor)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (antiga["hash"], antiga["ocorrida_em"], antiga["modo"], antiga["tipo"],
             antiga["mapa"], antiga["duracao_seg"], vencedor),
        )
        # linha do próprio dono (garante presença mesmo sem bj_antigas)
        conexao.execute(
            """INSERT OR IGNORE INTO batalha_jogadores
               (hash, tag_jogador, nick, brawler, power, trofeus, time,
                resultado, trofeus_delta, star_player)
               VALUES (?, ?, NULL, ?, NULL, NULL, 0, ?, ?, ?)""",
            (antiga["hash"], antiga["tag"], antiga["brawler"], resultado,
             antiga["trofeus_delta"], antiga["star_player"]),
        )
        if tem_bj:
            for j in conexao.execute(
                "SELECT * FROM bj_antigas WHERE hash = ?", (antiga["hash"],)
            ).fetchall():
                time_j: int = 0 if j["aliado"] else 1
                res_j: str | None = None
                if resultado in ("Victory", "Defeat"):
                    res_j = "Victory" if time_j == vencedor else "Defeat"
                elif resultado == "Draw":
                    res_j = "Draw"
                conexao.execute(
                    """INSERT INTO batalha_jogadores
                       (hash, tag_jogador, nick, brawler, power, trofeus, time,
                        resultado, trofeus_delta, star_player)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(hash, tag_jogador) DO UPDATE SET
                         nick = COALESCE(excluded.nick, nick),
                         power = COALESCE(excluded.power, power),
                         trofeus = COALESCE(excluded.trofeus, trofeus),
                         resultado = COALESCE(batalha_jogadores.resultado, excluded.resultado),
                         star_player = MAX(COALESCE(batalha_jogadores.star_player, 0),
                                           COALESCE(excluded.star_player, 0))""",
                    (j["hash"], j["tag_jogador"], j["nick"], j["brawler"], j["power"],
                     j["trofeus"], time_j, res_j,
                     antiga["trofeus_delta"] if j["eu"] else None, j["star_player"]),
                )
    conexao.executescript("""
        DROP TABLE batalhas_antigas;
        DROP TABLE IF EXISTS bj_antigas;
    """)
    conexao.commit()


_RE_RANK_ANTIGO = __import__("re").compile(r"^RANK (\d+) - (.+)$")


def _reparar_showdown_mal_parseado(conexao: sqlite3.Connection) -> None:
    """Reparo único: showdowns de troféus salvos com modo='RANKED' e
    resultado='RANK n - MODO' (formato de header não previsto pelo parser).
    Restaura o modo real e infere Victory/Defeat pelo sinal do delta."""
    linhas = conexao.execute("SELECT hash FROM batalhas WHERE modo = 'RANKED'").fetchall()
    if not linhas:
        return
    for linha in linhas:
        modo_novo: str | None = None
        for j in conexao.execute(
            "SELECT tag_jogador, resultado, trofeus_delta FROM batalha_jogadores"
            " WHERE hash = ? AND resultado LIKE 'RANK %'", (linha["hash"],)
        ).fetchall():
            m = _RE_RANK_ANTIGO.match(j["resultado"] or "")
            if not m:
                continue
            modo_novo = m.group(2)
            delta = j["trofeus_delta"] or 0
            resultado = "Victory" if delta > 0 else ("Defeat" if delta < 0 else None)
            conexao.execute(
                "UPDATE batalha_jogadores SET resultado = ? WHERE hash = ? AND tag_jogador = ?",
                (resultado, linha["hash"], j["tag_jogador"]),
            )
        if modo_novo:
            conexao.execute(
                "UPDATE batalhas SET modo = ?, tipo = 'TROPHIES' WHERE hash = ?",
                (modo_novo, linha["hash"]),
            )
    conexao.commit()


def _reclassificar_tipo_por_delta(conexao: sqlite3.Connection) -> None:
    """Reparo idempotente: batalhas que MOVERAM troféu são de TROFÉU, não Ranked.

    O brawlace rotula a ladder normal como 'RANKED - MODO' (é o type='ranked' da
    API da Supercell), mas quem dá/tira troféu é só a ladder — o modo competitivo
    Ranked não mexe em troféu. Toda batalha com trophyChange (delta ≠ 0) em algum
    participante é, portanto, de TROFÉU. Só faz UPGRADE (nunca marca competitivo
    como troféu sem delta), então é seguro rodar a cada conexão."""
    conexao.execute(
        """UPDATE batalhas SET tipo = 'TROPHIES'
           WHERE tipo <> 'TROPHIES'
             AND hash IN (
               SELECT hash FROM batalha_jogadores
               WHERE trofeus_delta IS NOT NULL AND trofeus_delta <> 0
             )"""
    )
    conexao.commit()


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def salvar_consulta(conexao: sqlite3.Connection, perfil: dict) -> dict:
    """Grava jogador + snapshot + batalhas novas (dedupe por hash).

    Retorna {'batalhas_novas': int, 'total_batalhas': int}.
    """
    agora: str = _agora()
    tag: str = perfil["tag"]
    stats: dict = perfil["stats"]

    conexao.execute(
        """INSERT INTO jogadores (tag, nick, primeiro_visto, ultimo_visto)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(tag) DO UPDATE SET nick = excluded.nick, ultimo_visto = excluded.ultimo_visto""",
        (tag, perfil["nick"], agora, agora),
    )
    conexao.execute(
        """INSERT INTO snapshots (tag, criado_em, trofeus, trofeus_max, level,
                                  vitorias_3v3, vitorias_solo, vitorias_duo,
                                  ranked_atual, ranked_max, win_streak_max, brawlers_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            tag, agora,
            stats.get("trofeus"), stats.get("trofeus_max"), stats.get("level"),
            stats.get("vitorias_3v3"), stats.get("vitorias_solo"), stats.get("vitorias_duo"),
            stats.get("ranked_atual"), stats.get("ranked_max"), stats.get("win_streak_max"),
            json.dumps(perfil["brawlers"], ensure_ascii=False),
        ),
    )

    novas: int = salvar_batalhas(conexao, tag, perfil["batalhas"])
    conexao.commit()

    return {"batalhas_novas": novas, "total_batalhas": contar_batalhas(conexao, tag)}


def salvar_batalhas(conexao: sqlite3.Connection, tag: str, batalhas: list[dict]) -> int:
    """Insere batalhas globais (dedupe por hash) + participantes com resultado.

    O resultado do jogador consultado permite derivar o time vencedor e,
    portanto, o resultado de TODOS os participantes (3v3) — uma consulta
    alimenta o histórico de todo mundo que estava na partida.
    Retorna quantas batalhas ainda não existiam no banco.
    NÃO faz commit — quem chama decide (salvar_consulta comita no fim).
    """
    novas: int = 0
    for batalha in batalhas:
        resultado: str = batalha["resultado"]
        jogadores: list[dict] = batalha.get("jogadores", [])
        meu_time: int | None = next(
            (j["time"] for j in jogadores if j["eu"]), None
        )
        vencedor: int | None = None
        if resultado in ("Victory", "Defeat") and meu_time is not None and jogadores:
            times = {j["time"] for j in jogadores}
            if len(times) == 2:  # 3v3/5v5 — em showdown não dá para derivar
                outro = next(t for t in times if t != meu_time)
                vencedor = meu_time if resultado == "Victory" else outro

        cursor = conexao.execute(
            """INSERT INTO batalhas
               (hash, ocorrida_em, modo, tipo, mapa, duracao_seg, time_vencedor)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT DO NOTHING""",
            (batalha["hash"], batalha["ocorrida_em"], batalha["modo"],
             batalha["tipo"], batalha["mapa"], batalha["duracao_seg"], vencedor),
        )
        novas += cursor.rowcount
        if cursor.rowcount == 0 and vencedor is not None:
            conexao.execute(
                "UPDATE batalhas SET time_vencedor = ? WHERE hash = ? AND time_vencedor IS NULL",
                (vencedor, batalha["hash"]),
            )

        def _upsert_jogador(tag_j: str, nick: str | None, brawler: str | None,
                            power: int | None, trofeus: int | None,
                            time_j: int | None, res: str | None,
                            delta: int | None, star: bool,
                            rank: int | None = None) -> None:
            conexao.execute(
                """INSERT INTO batalha_jogadores
                   (hash, tag_jogador, nick, brawler, power, trofeus, time,
                    resultado, trofeus_delta, star_player, rank)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(hash, tag_jogador) DO UPDATE SET
                     nick = COALESCE(excluded.nick, batalha_jogadores.nick),
                     brawler = COALESCE(excluded.brawler, batalha_jogadores.brawler),
                     power = COALESCE(excluded.power, batalha_jogadores.power),
                     trofeus = COALESCE(excluded.trofeus, batalha_jogadores.trofeus),
                     time = COALESCE(batalha_jogadores.time, excluded.time),
                     resultado = COALESCE(batalha_jogadores.resultado, excluded.resultado),
                     trofeus_delta = COALESCE(batalha_jogadores.trofeus_delta, excluded.trofeus_delta),
                     star_player = CASE WHEN excluded.star_player > batalha_jogadores.star_player
                                        THEN excluded.star_player ELSE batalha_jogadores.star_player END,
                     rank = COALESCE(batalha_jogadores.rank, excluded.rank)""",
                (batalha["hash"], tag_j, nick, brawler, power, trofeus,
                 time_j, res, delta, int(star), rank),
            )

        for jogador in jogadores:
            res_j: str | None = None
            if jogador["eu"]:
                res_j = resultado
            elif resultado == "Draw":
                res_j = "Draw"
            elif vencedor is not None:
                res_j = "Victory" if jogador["time"] == vencedor else "Defeat"
            _upsert_jogador(
                jogador["tag_jogador"], jogador["nick"], jogador["brawler"],
                jogador["power"], jogador["trofeus"], jogador["time"], res_j,
                batalha["trofeus_delta"] if jogador["eu"] else None,
                jogador["star_player"],
                batalha.get("rank_showdown") if jogador["eu"] else None,
            )
        if not any(j["eu"] for j in jogadores):
            # parser não achou o dono no card (raro) — garante a linha dele
            _upsert_jogador(tag, None, batalha["brawler"], None, None, None,
                            resultado, batalha["trofeus_delta"],
                            bool(batalha["star_player"]),
                            batalha.get("rank_showdown"))
    return novas


def jogadores_das_batalhas(conexao: sqlite3.Connection, tag: str) -> list[dict]:
    """Todos os participantes das batalhas em que `tag` jogou.

    `resultado` é o do PONTO DE VISTA de `tag`; aliado/eu são relativos a ele
    (formato que app.indicadores.performance.social espera).
    """
    linhas = conexao.execute(
        """SELECT outros.hash, outros.tag_jogador, outros.nick, outros.brawler,
                  outros.power, outros.trofeus, outros.star_player,
                  eu.resultado AS resultado, b.modo, b.tipo,
                  CASE WHEN outros.time IS NOT NULL AND outros.time = eu.time
                       THEN 1 ELSE 0 END AS aliado,
                  CASE WHEN outros.tag_jogador = eu.tag_jogador
                       THEN 1 ELSE 0 END AS eu
           FROM batalha_jogadores eu
           JOIN batalha_jogadores outros ON outros.hash = eu.hash
           JOIN batalhas b ON b.hash = eu.hash
           WHERE eu.tag_jogador = ?""",
        (tag,),
    ).fetchall()
    return [dict(linha) for linha in linhas]


def batalhas_do_jogador(conexao: sqlite3.Connection, tag: str) -> list[dict]:
    """Batalhas em que `tag` participou, com os campos do ponto de vista dele."""
    linhas = conexao.execute(
        """SELECT b.hash, b.ocorrida_em, b.modo, b.tipo, b.mapa, b.duracao_seg,
                  bj.brawler, bj.resultado, bj.trofeus_delta, bj.star_player,
                  bj.rank
           FROM batalhas b
           JOIN batalha_jogadores bj ON bj.hash = b.hash
           WHERE bj.tag_jogador = ?
           ORDER BY b.ocorrida_em DESC""",
        (tag,),
    ).fetchall()
    return [dict(linha) for linha in linhas]


def brawlers_usados_do_jogador(conexao: sqlite3.Connection, tag: str) -> list[dict]:
    """Brawlers que o jogador usou em TODAS as batalhas capturadas (não só as
    decididas), mais usados primeiro: usos, vitórias (3v3/duo etc.) e star player.
    Fonte: batalha_jogadores (o que foi visto nas nossas buscas)."""
    linhas = conexao.execute(
        """SELECT bj.brawler AS brawler,
                  COUNT(*) AS usos,
                  SUM(CASE WHEN bj.resultado = 'Victory' THEN 1 ELSE 0 END) AS vitorias,
                  SUM(bj.star_player) AS stars
           FROM batalha_jogadores bj
           WHERE bj.tag_jogador = ? AND bj.brawler IS NOT NULL
           GROUP BY bj.brawler
           ORDER BY usos DESC""",
        (tag,),
    ).fetchall()
    return [{"brawler": l["brawler"], "usos": int(l["usos"]),
             "vitorias": int(l["vitorias"] or 0), "stars": int(l["stars"] or 0)}
            for l in linhas]


def contar_batalhas(conexao: sqlite3.Connection, tag: str) -> int:
    return conexao.execute(
        "SELECT COUNT(*) AS n FROM batalha_jogadores WHERE tag_jogador = ?", (tag,)
    ).fetchone()["n"]


def snapshots_do_jogador(conexao: sqlite3.Connection, tag: str) -> list[dict]:
    linhas = conexao.execute(
        "SELECT * FROM snapshots WHERE tag = ? ORDER BY criado_em", (tag,)
    ).fetchall()
    return [dict(linha) for linha in linhas]


def historico_diario_do_jogador(conexao: sqlite3.Connection, tag: str) -> list[dict]:
    linhas = conexao.execute(
        "SELECT * FROM historico_diario WHERE tag = ? ORDER BY data", (tag,)
    ).fetchall()
    return [dict(linha) for linha in linhas]


def historico_brawler_do_jogador(conexao: sqlite3.Connection, tag: str) -> list[dict]:
    linhas = conexao.execute(
        "SELECT * FROM historico_brawler WHERE tag = ? ORDER BY jogos DESC", (tag,)
    ).fetchall()
    return [dict(linha) for linha in linhas]


def salvar_meta(conexao: sqlite3.Connection, meta: dict) -> int:
    """Grava o snapshot do meta (dedupe por data+modo+brawler). Retorna novas linhas."""
    novas: int = 0
    for modo, ranking in meta.get("modos", {}).items():
        for linha in ranking:
            cursor = conexao.execute(
                """INSERT INTO meta_snapshots
                   (data, modo, brawler, star_player_pct, posicao)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT (data, modo, brawler) DO NOTHING""",
                (meta.get("data"), modo, linha["brawler"],
                 linha["star_player_pct"], linha["posicao"]),
            )
            novas += cursor.rowcount
    conexao.commit()
    return novas


def salvar_score_meta(conexao: sqlite3.Connection, tag: str, score: float | None) -> None:
    """Grava o score vs meta do dia (1 ponto/dia; o último do dia prevalece)."""
    if score is None:
        return
    conexao.execute(
        """INSERT INTO score_meta_historico (tag, dia, score) VALUES (?, ?, ?)
           ON CONFLICT (tag, dia) DO UPDATE SET score = excluded.score""",
        (tag, _agora()[:10], round(float(score), 1)),
    )
    conexao.commit()


def historico_score_meta(conexao: sqlite3.Connection, tag: str) -> list[dict]:
    """Série diária do score vs meta do jogador (para o gráfico de evolução)."""
    linhas = conexao.execute(
        "SELECT dia, score FROM score_meta_historico WHERE tag = ? ORDER BY dia", (tag,)
    ).fetchall()
    return [{"dia": l["dia"], "score": l["score"]} for l in linhas]


def estatisticas_globais(conexao: sqlite3.Connection) -> dict:
    """Totais de TODO o dado coletado — para o painel da home. Contagens baratas
    sobre as tabelas principais (o que temos e de quando a quando)."""
    def _n(sql: str):
        return conexao.execute(sql).fetchone()["n"]
    return {
        "batalhas": _n("SELECT COUNT(*) AS n FROM batalhas"),
        "registros_jogador": _n("SELECT COUNT(*) AS n FROM batalha_jogadores"),
        "jogadores_vistos": _n("SELECT COUNT(DISTINCT tag_jogador) AS n FROM batalha_jogadores"),
        "jogadores_consultados": _n("SELECT COUNT(*) AS n FROM jogadores"),
        "brawlers_vistos": _n("SELECT COUNT(DISTINCT brawler) AS n FROM batalha_jogadores WHERE brawler IS NOT NULL"),
        "mapas": _n("SELECT COUNT(DISTINCT mapa) AS n FROM batalhas WHERE mapa IS NOT NULL"),
        "modos": _n("SELECT COUNT(DISTINCT modo) AS n FROM batalhas WHERE modo IS NOT NULL"),
        "meta_snapshots": _n("SELECT COUNT(*) AS n FROM meta_snapshots"),
        "snapshots": _n("SELECT COUNT(*) AS n FROM snapshots"),
        "primeira_batalha": conexao.execute(
            "SELECT MIN(ocorrida_em) AS n FROM batalhas").fetchone()["n"],
        "ultima_batalha": conexao.execute(
            "SELECT MAX(ocorrida_em) AS n FROM batalhas").fetchone()["n"],
    }


def melhor_brawler_por_grupo(conexao: sqlite3.Connection, dimensao: str,
                             minimo: int = 5, limite: int | None = None) -> list[dict]:
    """META PRÓPRIO (das nossas batalhas): melhor brawler em cada mapa ou modo,
    por Wilson score (winrate ajustado à amostra). Só considera batalhas decididas
    e combos (grupo, brawler) com >= `minimo` jogos. Grupos mais jogados primeiro.
    `dimensao` = 'mapa' ou 'modo'."""
    if dimensao not in ("mapa", "modo"):
        raise ValueError(f"dimensao inválida: {dimensao!r}")
    col = "b." + dimensao
    linhas = conexao.execute(
        f"""SELECT {col} AS grupo, bj.brawler AS brawler,
                   COUNT(*) AS jogos,
                   SUM(CASE WHEN bj.resultado = 'Victory' THEN 1 ELSE 0 END) AS vitorias
            FROM batalha_jogadores bj JOIN batalhas b ON b.hash = bj.hash
            WHERE bj.resultado IN ('Victory','Defeat')
              AND bj.brawler IS NOT NULL AND {col} IS NOT NULL
            GROUP BY {col}, bj.brawler
            HAVING COUNT(*) >= ?""",
        (minimo,)).fetchall()
    from app.indicadores.performance import wilson
    grupos: dict = {}
    for l in linhas:
        g, jogos, vit = l["grupo"], int(l["jogos"]), int(l["vitorias"])
        w = wilson(vit, jogos)
        grupos.setdefault(g, {"grupo": g, "jogos_grupo": 0, "_w": -1.0})
        grupos[g]["jogos_grupo"] += jogos
        if w > grupos[g]["_w"]:
            grupos[g].update({"_w": w, "brawler": l["brawler"], "jogos": jogos,
                              "vitorias": vit, "winrate": round(vit / jogos * 100, 1)})
    saida = [g for g in grupos.values() if "brawler" in g]
    for g in saida:
        g.pop("_w", None)
    saida.sort(key=lambda x: -x["jogos_grupo"])
    return saida[:limite] if limite else saida


def brawlers_mais_usados_geral(conexao: sqlite3.Connection, limite: int = 15) -> list[dict]:
    """META PRÓPRIO: brawlers mais usados em TODAS as batalhas capturadas, com
    vitórias, star player e winrate (sobre as decididas). Mais usados primeiro."""
    linhas = conexao.execute(
        """SELECT bj.brawler AS brawler,
                  COUNT(*) AS usos,
                  SUM(CASE WHEN bj.resultado = 'Victory' THEN 1 ELSE 0 END) AS vitorias,
                  SUM(CASE WHEN bj.resultado IN ('Victory','Defeat') THEN 1 ELSE 0 END) AS decididas,
                  SUM(bj.star_player) AS stars
           FROM batalha_jogadores bj
           WHERE bj.brawler IS NOT NULL
           GROUP BY bj.brawler
           ORDER BY usos DESC""").fetchall()
    saida: list[dict] = []
    for l in linhas[:limite]:
        dec, vit = int(l["decididas"] or 0), int(l["vitorias"] or 0)
        saida.append({"brawler": l["brawler"], "usos": int(l["usos"]),
                      "vitorias": vit, "stars": int(l["stars"] or 0),
                      "winrate": round(vit / dec * 100, 1) if dec else None})
    return saida


def _contagem_simples(conexao: sqlite3.Connection, coluna: str, limite: int | None) -> list[dict]:
    linhas = conexao.execute(
        f"SELECT {coluna} AS nome, COUNT(*) AS jogos FROM batalhas "
        f"WHERE {coluna} IS NOT NULL GROUP BY {coluna} ORDER BY jogos DESC"
    ).fetchall()
    dados = [{"nome": l["nome"], "jogos": int(l["jogos"])} for l in linhas]
    return dados[:limite] if limite else dados


def mapas_mais_jogados(conexao: sqlite3.Connection, limite: int = 12) -> list[dict]:
    """META PRÓPRIO: mapas mais jogados nas batalhas capturadas."""
    return _contagem_simples(conexao, "mapa", limite)


def modos_mais_jogados(conexao: sqlite3.Connection, limite: int | None = None) -> list[dict]:
    """META PRÓPRIO: modos mais jogados nas batalhas capturadas."""
    return _contagem_simples(conexao, "modo", limite)


def resumo_comparacao(conexao: sqlite3.Connection, tag: str) -> dict | None:
    """KPIs de um jogador para a tela de comparação (tudo do banco). None se o
    jogador nunca foi consultado (sem snapshot)."""
    perfil = perfil_do_banco(conexao, tag)
    if perfil is None:
        return None
    stats = perfil["stats"]
    r = conexao.execute(
        """SELECT COUNT(*) AS total,
                  SUM(CASE WHEN resultado IN ('Victory','Defeat') THEN 1 ELSE 0 END) AS dec,
                  SUM(CASE WHEN resultado = 'Victory' THEN 1 ELSE 0 END) AS vit,
                  SUM(star_player) AS stars
           FROM batalha_jogadores WHERE tag_jogador = ?""",
        (tag,)).fetchone()
    dec, vit = int(r["dec"] or 0), int(r["vit"] or 0)
    stars = int(r["stars"] or 0)
    usados = brawlers_usados_do_jogador(conexao, tag)
    return {
        "tag": tag, "nick": perfil["nick"],
        "trofeus": stats.get("trofeus"), "trofeus_max": stats.get("trofeus_max"),
        "level": stats.get("level"),
        "vitorias_3v3": stats.get("vitorias_3v3"),
        "vitorias_solo": stats.get("vitorias_solo"),
        "vitorias_duo": stats.get("vitorias_duo"),
        "ranked_atual": stats.get("ranked_atual"),
        "batalhas": int(r["total"] or 0), "decididas": dec, "vitorias": vit,
        "winrate": round(vit / dec * 100, 1) if dec else None,
        "stars": stars, "star_pct": round(stars / dec * 100, 1) if dec else None,
        "n_brawlers": len(usados),
        "brawler_top": usados[0] if usados else None,
    }


def data_meta_recente(conexao: sqlite3.Connection) -> str | None:
    """Data (timestamp texto) do snapshot de meta mais recente, ou None se vazio."""
    linha = conexao.execute("SELECT MAX(data) AS d FROM meta_snapshots").fetchone()
    return linha["d"] if linha else None


def brawlers_no_meta(conexao: sqlite3.Connection) -> list[dict]:
    """Todos os brawlers do meta (data mais recente), com a MELHOR posição entre
    os modos e em quantos modos aparecem — para o índice `/brawler`. A→Z? Não:
    ordena pela melhor posição (mais fortes primeiro)."""
    linhas = conexao.execute(
        """SELECT brawler,
                  MIN(posicao) AS melhor_pos,
                  COUNT(*) AS modos
           FROM meta_snapshots
           WHERE data = (SELECT MAX(data) FROM meta_snapshots)
           GROUP BY brawler
           ORDER BY MIN(posicao)""",
    ).fetchall()
    return [{"brawler": l["brawler"], "melhor_pos": l["melhor_pos"],
             "modos": l["modos"]} for l in linhas]


def meta_do_brawler(conexao: sqlite3.Connection, brawler: str) -> list[dict]:
    """Posição + % de star player do brawler em cada modo, na data mais recente
    do meta. Melhores modos (menor posição) primeiro. Lista vazia se não achar."""
    linhas = conexao.execute(
        """SELECT modo, star_player_pct, posicao
           FROM meta_snapshots
           WHERE brawler = ? AND data = (SELECT MAX(data) FROM meta_snapshots)
           ORDER BY posicao""",
        (brawler,),
    ).fetchall()
    return [{"modo": l["modo"], "star_player_pct": l["star_player_pct"],
             "posicao": l["posicao"]} for l in linhas]


def meta_brawler_detalhado(conexao: sqlite3.Connection, brawler: str) -> dict:
    """Detalhe rico do brawler no meta: por modo, posição COM contexto (de N
    brawlers), nível (forte/médio/fraco pelo percentil) e tendência vs a data
    anterior. Retorna {data, modos:[...], fortes:[...], fracos:[...]}."""
    d1 = data_meta_recente(conexao)
    if d1 is None:
        return {"data": None, "modos": [], "fortes": [], "fracos": []}
    # data anterior (para a tendência)
    r = conexao.execute(
        "SELECT MAX(data) AS d FROM meta_snapshots WHERE data < ?", (d1,)
    ).fetchone()
    d0 = r["d"] if r else None
    # quantos brawlers cada modo tem na data atual (para o "Xº de N")
    totais = {l["modo"]: l["n"] for l in conexao.execute(
        "SELECT modo, COUNT(*) AS n FROM meta_snapshots WHERE data = ? GROUP BY modo",
        (d1,)).fetchall()}
    # posições do brawler na data anterior (para o delta)
    anteriores: dict = {}
    if d0:
        anteriores = {l["modo"]: l["posicao"] for l in conexao.execute(
            "SELECT modo, posicao FROM meta_snapshots WHERE brawler = ? AND data = ?",
            (brawler, d0)).fetchall()}
    modos: list[dict] = []
    for l in conexao.execute(
        """SELECT modo, star_player_pct, posicao FROM meta_snapshots
           WHERE brawler = ? AND data = ? ORDER BY posicao""",
        (brawler, d1)).fetchall():
        modo, pos, spp = l["modo"], l["posicao"], l["star_player_pct"]
        total = totais.get(modo)
        pct = (pos / total) if total else None  # 0 = topo; 1 = fundo
        nivel = ("forte" if pct is not None and pct <= 0.20
                 else "fraco" if pct is not None and pct > 0.55 else "medio")
        delta = (anteriores[modo] - pos) if modo in anteriores else None  # + = subiu
        modos.append({"modo": modo, "posicao": pos, "total": total,
                      "star_player_pct": spp, "nivel": nivel, "delta": delta})
    return {
        "data": d1,
        "modos": modos,
        "fortes": [m["modo"] for m in modos if m["nivel"] == "forte"],
        "fracos": [m["modo"] for m in modos if m["nivel"] == "fraco"],
    }


def _nivel_meta(pos: int, total: int | None) -> str:
    """Classifica a força do brawler no modo pelo percentil da posição."""
    if not total:
        return "medio"
    pct = pos / total
    return "forte" if pct <= 0.20 else "fraco" if pct > 0.55 else "medio"


def meta_todos_detalhado(conexao: sqlite3.Connection) -> dict:
    """Detalhe de TODOS os brawlers do meta (data recente) para o accordion de
    /brawler — cada um com seus modos (posição de N, nível, tendência), forte/
    fraco resumidos. Eficiente: 3 queries no total. {data, brawlers:[...]}."""
    d1 = data_meta_recente(conexao)
    if d1 is None:
        return {"data": None, "brawlers": []}
    r = conexao.execute(
        "SELECT MAX(data) AS d FROM meta_snapshots WHERE data < ?", (d1,)
    ).fetchone()
    d0 = r["d"] if r else None
    totais = {l["modo"]: l["n"] for l in conexao.execute(
        "SELECT modo, COUNT(*) AS n FROM meta_snapshots WHERE data = ? GROUP BY modo",
        (d1,)).fetchall()}
    anteriores: dict = {}
    if d0:
        for l in conexao.execute(
            "SELECT brawler, modo, posicao FROM meta_snapshots WHERE data = ?",
            (d0,)).fetchall():
            anteriores[(l["brawler"], l["modo"])] = l["posicao"]
    por_brawler: dict = {}
    for l in conexao.execute(
        """SELECT brawler, modo, star_player_pct, posicao
           FROM meta_snapshots WHERE data = ? ORDER BY posicao""",
        (d1,)).fetchall():
        b, modo, pos, spp = l["brawler"], l["modo"], l["posicao"], l["star_player_pct"]
        total = totais.get(modo)
        delta = anteriores[(b, modo)] - pos if (b, modo) in anteriores else None
        por_brawler.setdefault(b, []).append({
            "modo": modo, "posicao": pos, "total": total,
            "star_player_pct": spp, "nivel": _nivel_meta(pos, total), "delta": delta,
        })
    brawlers: list[dict] = []
    for b, modos in por_brawler.items():
        modos.sort(key=lambda m: m["posicao"])
        posicoes = [m["posicao"] for m in modos]
        brawlers.append({
            "brawler": b,
            "melhor_pos": modos[0]["posicao"],
            # posição MÉDIA entre os modos = força GERAL (menor = mais forte no geral)
            "pos_media": round(sum(posicoes) / len(posicoes), 1),
            "modos_qtd": len(modos),
            "modos": modos,
            "fortes": [m["modo"] for m in modos if m["nivel"] == "forte"],
            "fracos": [m["modo"] for m in modos if m["nivel"] == "fraco"],
        })
    # ordena pela força GERAL (posição média), não pela melhor posição num único modo
    brawlers.sort(key=lambda x: x["pos_media"])
    return {"data": d1, "brawlers": brawlers}


def ranking_jogadores(conexao: sqlite3.Connection, minimo_jogos: int = 5) -> list[dict]:
    """Ranking de todos os jogadores conhecidos no banco (consultados ou não):
    batalhas decididas, winrate, taxa de star player e troféus GANHOS (soma dos
    deltas das partidas registradas — só conta os deltas conhecidos, i.e., das
    batalhas em que o jogador foi consultado). Só entra quem tem >= minimo_jogos
    batalhas decididas."""
    minimo_jogos = max(1, minimo_jogos)  # nunca 0 → evita divisão por zero
    linhas = conexao.execute(
        """SELECT bj.tag_jogador AS tag,
                  MAX(bj.nick) AS nick,
                  SUM(CASE WHEN bj.resultado IN ('Victory','Defeat') THEN 1 ELSE 0 END) AS decididas,
                  SUM(CASE WHEN bj.resultado = 'Victory' THEN 1 ELSE 0 END) AS vitorias,
                  SUM(bj.star_player) AS stars,
                  SUM(bj.trofeus_delta) AS trofeus_ganhos
           FROM batalha_jogadores bj
           GROUP BY bj.tag_jogador
           HAVING SUM(CASE WHEN bj.resultado IN ('Victory','Defeat') THEN 1 ELSE 0 END) >= ?""",
        (minimo_jogos,),
    ).fetchall()
    ranking: list[dict] = []
    for l in linhas:
        ranking.append({
            "tag": l["tag"],
            "nick": l["nick"] or l["tag"],
            "jogos": l["decididas"],
            "vitorias": l["vitorias"],
            "winrate": round(l["vitorias"] / l["decididas"] * 100, 1),
            "stars": l["stars"] or 0,
            "star_pct": round((l["stars"] or 0) / l["decididas"] * 100, 1),
            # Postgres SUM() volta Decimal; normaliza p/ int (SQLite já é int).
            "trofeus_ganhos": int(l["trofeus_ganhos"] or 0),
        })
    from app.indicadores.performance import wilson  # import local evita ciclo
    ranking.sort(key=lambda r: -wilson(r["vitorias"], r["jogos"]))
    return ranking


def perfil_do_banco(conexao: sqlite3.Connection, tag: str) -> dict | None:
    """Monta um 'perfil' com o que há no banco (snapshot mais recente + batalhas
    acumuladas) — para a página abrir INSTANTANEAMENTE sem esperar scraping.
    Retorna None se o jogador nunca foi consultado (sem snapshot)."""
    jogador = conexao.execute(
        "SELECT nick FROM jogadores WHERE tag = ?", (tag,)
    ).fetchone()
    snapshot = conexao.execute(
        "SELECT * FROM snapshots WHERE tag = ? ORDER BY criado_em DESC LIMIT 1",
        (tag,),
    ).fetchone()
    if jogador is None or snapshot is None:
        return None
    return {
        "tag": tag,
        "nick": jogador["nick"],
        "clube": None,
        "stats": {
            "trofeus": snapshot["trofeus"],
            "trofeus_max": snapshot["trofeus_max"],
            "level": snapshot["level"],
            "ranked_atual": snapshot["ranked_atual"] if "ranked_atual" in snapshot.keys() else None,
            "ranked_max": snapshot["ranked_max"] if "ranked_max" in snapshot.keys() else None,
            "vitorias_3v3": snapshot["vitorias_3v3"],
            "vitorias_solo": snapshot["vitorias_solo"],
            "vitorias_duo": snapshot["vitorias_duo"],
            "win_streak_max": snapshot["win_streak_max"] if "win_streak_max" in snapshot.keys() else None,
        },
        "brawlers": json.loads(snapshot["brawlers_json"] or "[]"),
        "batalhas": batalhas_do_jogador(conexao, tag)[:25],
        "grafico_trofeus": [],
        "_snapshot_em": snapshot["criado_em"],
    }


def salvar_clube(conexao: sqlite3.Connection, clube: dict) -> None:
    """Grava/atualiza o roster do clube (substitui os membros — snapshot atual)."""
    conexao.execute(
        """INSERT INTO clubes (clube_tag, nome, atualizado_em) VALUES (?, ?, ?)
           ON CONFLICT(clube_tag) DO UPDATE SET
             nome = excluded.nome, atualizado_em = excluded.atualizado_em""",
        (clube["clube_tag"], clube["nome"], _agora()),
    )
    conexao.execute("DELETE FROM clube_membros WHERE clube_tag = ?", (clube["clube_tag"],))
    conexao.executemany(
        """INSERT INTO clube_membros (clube_tag, tag, nick) VALUES (?, ?, ?)
           ON CONFLICT DO NOTHING""",
        [(clube["clube_tag"], m["tag"], m["nick"]) for m in clube["membros"]],
    )
    conexao.commit()


# Clube fixo do app (clã Snake). Antes usávamos "o mais recentemente atualizado",
# mas consultar um jogador de OUTRO clube trocava o principal (ex.: "crias").
# Override por env CLUBE_TAG_PRINCIPAL se algum dia mudar de clã.
CLUBE_TAG_PRINCIPAL: str = os.environ.get("CLUBE_TAG_PRINCIPAL", "#8LG0QGLC").strip()


def clube_principal(conexao: sqlite3.Connection) -> dict | None:
    """O clã Snake (fixo por tag). Fallback: o clube mais recente, se a tag fixa
    ainda não estiver no banco."""
    linha = None
    if CLUBE_TAG_PRINCIPAL:
        linha = conexao.execute(
            "SELECT * FROM clubes WHERE clube_tag = ?", (CLUBE_TAG_PRINCIPAL,)
        ).fetchone()
    if linha is None:
        linha = conexao.execute(
            "SELECT * FROM clubes ORDER BY atualizado_em DESC LIMIT 1"
        ).fetchone()
    if linha is None:
        return None
    membros = conexao.execute(
        "SELECT tag, nick FROM clube_membros WHERE clube_tag = ?", (linha["clube_tag"],)
    ).fetchall()
    return {
        "clube_tag": linha["clube_tag"],
        "nome": linha["nome"],
        "membros": {m["tag"] for m in membros},
    }


def times_das_batalhas(conexao: sqlite3.Connection) -> list[dict]:
    """Todos os participantes com time e resultado conhecidos (p/ composições)."""
    linhas = conexao.execute(
        """SELECT bj.hash, bj.time, bj.tag_jogador, bj.nick, bj.resultado,
                  bj.brawler, bj.star_player, b.modo
           FROM batalha_jogadores bj
           JOIN batalhas b ON b.hash = bj.hash
           WHERE bj.resultado IN ('Victory', 'Defeat') AND bj.time IS NOT NULL"""
    ).fetchall()
    return [dict(l) for l in linhas]


def historico_brawler_modo_do_jogador(conexao: sqlite3.Connection, tag: str) -> list[dict]:
    linhas = conexao.execute(
        "SELECT * FROM historico_brawler_modo WHERE tag = ?", (tag,)
    ).fetchall()
    return [dict(l) for l in linhas]


def tags_sem_historico_externo(conexao: sqlite3.Connection) -> list[dict]:
    """Jogadores consultados que ainda NÃO têm importação do Brawlify
    (historico_diario vazio) — lembrete do processo manual (CLAUDE.md §3.6b)."""
    linhas = conexao.execute(
        """SELECT j.tag, j.nick, j.primeiro_visto
           FROM jogadores j
           WHERE NOT EXISTS (
             SELECT 1 FROM historico_diario h WHERE h.tag = j.tag
           )
           ORDER BY j.primeiro_visto DESC"""
    ).fetchall()
    return [dict(l) for l in linhas]
