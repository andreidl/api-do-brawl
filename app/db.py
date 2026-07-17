"""SQLite — schema e gravação (CLAUDE.md §6). Banco em data/brawl.db."""
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

CAMINHO_BANCO: Path = Path(__file__).resolve().parents[1] / "data" / "brawl.db"

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
"""


def conectar(caminho: Path | None = None) -> sqlite3.Connection:
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
    if "rank" not in _colunas(conexao, "batalha_jogadores"):
        conexao.execute("ALTER TABLE batalha_jogadores ADD COLUMN rank INTEGER")
        conexao.commit()
    # migração leve: snapshots antigos sem colunas de ranked
    if "ranked_atual" not in _colunas(conexao, "snapshots"):
        conexao.execute("ALTER TABLE snapshots ADD COLUMN ranked_atual TEXT")
        conexao.execute("ALTER TABLE snapshots ADD COLUMN ranked_max TEXT")
        conexao.commit()
    return conexao


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
                                  ranked_atual, ranked_max, brawlers_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            tag, agora,
            stats.get("trofeus"), stats.get("trofeus_max"), stats.get("level"),
            stats.get("vitorias_3v3"), stats.get("vitorias_solo"), stats.get("vitorias_duo"),
            stats.get("ranked_atual"), stats.get("ranked_max"),
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
            """INSERT OR IGNORE INTO batalhas
               (hash, ocorrida_em, modo, tipo, mapa, duracao_seg, time_vencedor)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
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
                     nick = COALESCE(excluded.nick, nick),
                     brawler = COALESCE(excluded.brawler, brawler),
                     power = COALESCE(excluded.power, power),
                     trofeus = COALESCE(excluded.trofeus, trofeus),
                     time = COALESCE(batalha_jogadores.time, excluded.time),
                     resultado = COALESCE(batalha_jogadores.resultado, excluded.resultado),
                     trofeus_delta = COALESCE(batalha_jogadores.trofeus_delta, excluded.trofeus_delta),
                     star_player = MAX(batalha_jogadores.star_player, excluded.star_player),
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


def contar_batalhas(conexao: sqlite3.Connection, tag: str) -> int:
    return conexao.execute(
        "SELECT COUNT(*) FROM batalha_jogadores WHERE tag_jogador = ?", (tag,)
    ).fetchone()[0]


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
                """INSERT OR IGNORE INTO meta_snapshots
                   (data, modo, brawler, star_player_pct, posicao)
                   VALUES (?, ?, ?, ?, ?)""",
                (meta.get("data"), modo, linha["brawler"],
                 linha["star_player_pct"], linha["posicao"]),
            )
            novas += cursor.rowcount
    conexao.commit()
    return novas


def ranking_jogadores(conexao: sqlite3.Connection, minimo_jogos: int = 5) -> list[dict]:
    """Ranking de todos os jogadores conhecidos no banco (consultados ou não):
    batalhas decididas, winrate, taxa de star player e troféus máximos vistos.
    Só entra quem tem >= minimo_jogos batalhas decididas."""
    minimo_jogos = max(1, minimo_jogos)  # nunca 0 → evita divisão por zero
    linhas = conexao.execute(
        """SELECT bj.tag_jogador AS tag,
                  MAX(bj.nick) AS nick,
                  SUM(CASE WHEN bj.resultado IN ('Victory','Defeat') THEN 1 ELSE 0 END) AS decididas,
                  SUM(CASE WHEN bj.resultado = 'Victory' THEN 1 ELSE 0 END) AS vitorias,
                  SUM(bj.star_player) AS stars,
                  MAX(bj.trofeus) AS trofeus
           FROM batalha_jogadores bj
           GROUP BY bj.tag_jogador
           HAVING decididas >= ?""",
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
            "star_pct": round((l["stars"] or 0) / l["decididas"] * 100, 1),
            "trofeus": l["trofeus"],
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
        "INSERT OR IGNORE INTO clube_membros (clube_tag, tag, nick) VALUES (?, ?, ?)",
        [(clube["clube_tag"], m["tag"], m["nick"]) for m in clube["membros"]],
    )
    conexao.commit()


def clube_principal(conexao: sqlite3.Connection) -> dict | None:
    """O clube conhecido mais recentemente atualizado (para o ranking da home)."""
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
