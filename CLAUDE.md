# API do Brawl — Guia de Contexto Completo para Claude

> Leia este arquivo inteiro antes de qualquer modificação no projeto.
> **Última atualização: 24/07/2026 — conserto do meta, ~20 estatísticas novas, banco versionado.**

## IMPORTANTE — PLANO DE TRABALHO

**Leia `plano.md` no início de cada sessão.**
Esse arquivo contém a fila priorizada de tudo que falta (P0→P3).
Ao terminar uma tarefa, marque `[x]` e atualize a seção "CONCLUÍDO" com a data.

---

## 0. CHANGELOG — SESSÃO 24/07/2026

- **FIX classificação RANKED × TROFÉUS**: a API da Supercell marca a ladder normal
  de troféus como `type="ranked"` (o brawlace mostra "RANKED - MODO"). O parser
  antes classificava tudo disso como Ranked competitivo. Agora usa o **delta de
  troféu** (`trophyChange`) como verdade: batalha com delta = TROFÉU; sem delta =
  Ranked competitivo. Migração `_reclassificar_tipo_por_delta` (idempotente).
- **FIX coleta do meta (quebrada desde 17/07)**: o brawlace adicionou uma seção
  "TEAMS" no `/meta` com 1ª célula vazia → `_numero('')` derrubava tudo. O parser
  agora pula linhas sem posição numérica. Tabelas viraram 5 colunas (star player
  com separador de milhar). Fixture `meta_2026-07-23_teams.html` + testes.
- **Banco versionado**: `data/brawl.db` agora É commitado (backup dos dados
  insubstituíveis). `.gitignore`: `data/*` + `!data/brawl.db`; cache/logs/WAL fora.
  Checkpoint do WAL antes de commitar. **Backup só atualiza quando o .db é commitado.**
- **Rastreador**: `TAGS_CLA_FIXAS` em `rastrear.py` — sempre rastreia os membros
  reais do clã Snake (andreidl, bigboss, gustavo, camila, Logan), não só quem já
  foi consultado ao vivo. Assim os jogos em dupla deles são capturados pela janela
  de 25 partidas DELES também.
- **~20 estatísticas novas** no perfil (ver §4) + **índice navegável** (âncoras) no
  topo + **cards de brawler expansíveis** (`<details>`).
- **Schema**: coluna `win_streak_max` em `snapshots` + tabela `score_meta_historico`
  (evolução do score vs meta, 1 ponto/dia). Migrações idempotentes por `ALTER`.
- **90 testes pytest passando** (4 novos do parser de meta).

---

## 1. O QUE É O PROJETO

Site web em Python onde o usuário digita a **tag de um jogador de Brawl Stars**
(ex: `#299PGGLQL`) e recebe:

1. **Coleta** — dados públicos do jogador raspados da web (sem chave da API oficial)
2. **Indicadores de performance** — winrate geral e por modo, performance por
   brawler, evolução de troféus ao longo do tempo
3. **Meta** — melhores brawlers por modo/mapa no meta atual, **correlacionados**
   com os dados do jogador (o quanto ele joga com brawlers fortes; sugestões de pick)

**Princípio do projeto: o mais rápido e simples possível.** Nada de microsserviços,
filas, Docker ou frontend framework. Um app FastAPI só, HTML server-side.

### Contexto de produto (respostas do usuário em 17/07/2026)

- **Usuários reais**: andreidl (dono), camilacgs, bigboss, logankl, guduartel —
  todos do clube Snake. LoganKL é membro real do clã (não random).
- **Uso**: só PC, como "app para olhar enquanto escolho o modo" → a página
  precisa abrir RÁPIDO (mostrar o banco primeiro; scraping em segundo plano).
- **O PC não fica sempre ligado** → tarefa agendada do Windows é inadequada
  (nunca foi instalada, aliás). Rastreio deve ser embutido no app (no startup
  + periódico enquanto aberto). `instalar_rastreio.ps1` está aposentado.
- **Ranked × troféus devem ser SEPARADOS nas análises** (hoje misturam).
- **Sugestão de picks** deve pesar o winrate/uso DO JOGADOR, não só o meta.
- **Composição de trios**: analisar todas as combinações de jogadores/brawlers
  (não só um trio fixo).
- **Ranking do clube**: verificar se o jogador é do MESMO clube para entrar;
  usuário quer compartilhar print no WhatsApp do clã.
- **Dados para sempre** — nunca apagar/resumir histórico.
- **Máximo de dados possível**: buscar múltiplas fontes raspáveis; as com
  Cloudflare seguem o processo manual (§3.6b). Tag nova no app → lembrar de
  importar Brawlify/outras fontes manualmente.
- Sem meta pessoal no jogo; sem deploy por ora; o repo GitHub `brawlapiteste`
  era só teste (criar repo definitivo quando o usuário pedir).

### Decisões fechadas com o usuário (17/07/2026 — NÃO reabrir sem ele pedir)

| Decisão | Escolha |
|---|---|
| Produto | Site web completo (não é API pura para terceiros) |
| Fonte de dados | **Scraping de HTML** do brawlace.com (usuário recusou API oficial da Supercell) |
| Stack | Python + FastAPI + httpx + BeautifulSoup + pandas + Jinja2 |
| Persistência | SQLite local, snapshots a cada consulta |
| Indicadores | Todos os 4: winrate por modo, performance por brawler, evolução de troféus, score vs meta |
| Tag de teste | `#299PGGLQL` (perfil do usuário: **SNK \| andreidl**) |

---

## 2. STACK E ESTRUTURA

- **Python 3.11+** — FastAPI + uvicorn, httpx, beautifulsoup4 + lxml, pandas, Jinja2
- **SQLite** via `sqlite3` da stdlib (sem ORM — simplicidade)
- Frontend: templates Jinja2 + CSS puro servidos pelo próprio FastAPI. Sem build step.

```
C:\projetos\api-do-brawl\
  app\
    main.py                  — FastAPI: rotas web + rotas /api
    db.py                    — schema SQLite + upserts (banco em data/brawl.db)
    coleta\
      brawlace.py            — scraper: perfil, meta, eventos
      cache.py               — cache de requisições em disco com TTL
    indicadores\
      performance.py         — KPIs com pandas (parte 2)
      meta.py                — correlação jogador × meta (parte 3)
    templates\               — Jinja2 (base.html, home.html, jogador.html)
    static\                  — CSS/ícones
  tests\
    fixtures\                — HTMLs reais salvos p/ testar parsing offline
  data\                      — brawl.db (VERSIONADO como backup) + cache (ignorado)
  backups\                   — dumps .db antigos (versionados)
  plano.md                   — fila de trabalho priorizada
  requirements.txt
```

**Rodar:** `uvicorn app.main:app --reload` (na raiz do projeto)
**Testes:** `python -m pytest tests/`

---

## 3. FONTE DE DADOS — brawlace.com (VALIDADO 17/07/2026)

> Tudo abaixo foi **verificado na prática** via curl/navegador em 17/07/2026.
> Se o parsing quebrar no futuro, re-inspecionar o HTML antes de culpar o código.

### Por que brawlace.com

- **brawlify.com**: bloqueado por Cloudflare challenge → INVIÁVEL para scraping
- **api.brawlify.com**: respondeu 522 (origem fora do ar) → retestar no futuro
  como fonte secundária, mas NÃO depender dela
- **brawlace.com**: server-rendered (dados já vêm no HTML, jQuery só para UI),
  sem challenge, respondeu 200 com ~420 KB via curl com User-Agent de navegador ✅

### 3.1 Perfil do jogador — `https://brawlace.com/players/%23TAG`

- Tag em **UPPERCASE**, `#` codificado como `%23`. Tag inválida → título "404 Page Not Found".
- A página contém, em um único GET:
  - **Stats gerais:** nick, level, troféus atuais/máximos, ranked rank (atual e
    máximo), win streak (atual/máx), vitórias 3v3, solo e duo
  - **Tabela de brawlers** (um `<tr>` por brawler): nome, power, tier, troféus,
    troféus máximos, win streaks, hypercharge/gears/star powers/gadgets, skin
  - **Battle log — últimas 25 partidas**, seção `<h2 id='battlelog-section'>`:
    - Resumo pronto: `Victory : 11 (44%)` / `Defeat : 14`
    - Cada batalha é um card com **id = hash hex de 40 chars, ÚNICO por batalha**
      → usar como chave primária para deduplicar no SQLite
    - Header do card: `RANKED - HOT ZONE | Defeat | 01:16` +
      `<time datetime='2026-07-17T03:11:36Z'>` + `data-map-name='Controller Chaos'`
    - Corpo: cada jogador com brawler (atributo `title` do img), power, troféus,
      tag (`data-bs-player-tag`) e badge de star player
    - Filtro por modo via query string: `?filter[gameMode]=hotZone` (valores
      camelCase: `gemGrab`, `brawlBall`, `soloShowdown`, `knockout`, `bounty`, `hotZone`...)
    - **Coleta turbo (implementada 17/07/2026):** `coletar_battlelog_modo()` usa esse
      filtro para 7 modos (`MODOS_BATTLELOG`) → até 25 batalhas EXTRAS por modo por
      consulta/rodada do rastreador. Falha em um modo nunca derruba a consulta.
    - **Todos os jogadores do card são gravados** em `batalha_jogadores`
      (brawler, power, troféus, nick, tag, aliado/inimigo, star player) →
      alimenta matchups (vs brawler inimigo) e parceiros (winrate por aliado).

### 3.2 Meta global — `https://brawlace.com/meta`

- Meta **diário** por modo de jogo, atualizado ~3x/dia, com histórico de datas
- Por modo: ranking de brawlers por **contagem e % de Star Player** + trends
- Modos disponíveis: Solo/Duo/Trio Showdown, Brawl Ball (3v3 e 5v5), Gem Grab,
  Knockout (3v3 e 5v5), Bounty, Hot Zone, Heist, Brawl Arena, Basket Brawl, Wipeout
- Também tem "Game Mode Popularity"

### 3.3 Eventos/mapas ativos — `https://brawlace.com/events`

- Eventos atuais e futuros com modo + mapa (200, ~190 KB)

### 3.4 Brawlers (referência) — `https://brawlace.com/brawlers`

- Lista de todos os brawlers com detalhes (200, ~100 KB)

### 3.4b Fonte complementar — brawltime.ninja (API JSON pública, validada 17/07/2026)

- `GET https://brawltime.ninja/api/player.byTagExtra?input={"json":"TAG"}` (tag SEM `#`,
  input URL-encoded) → `accountCreationYear`, `recordLevel`, `recordPoints`
- Usada só para a seção "Carreira". **Falha nunca derruba a consulta** (retorna None).
- TTL 24 h. Implementada em `app/coleta/brawltime.py`.
- O tracking do BrawlTime para uma tag só começa quando alguém visita o perfil lá —
  histórico deles do usuário começou em 17/07/2026, não tem passado antigo.

### 3.6 Histórico do passado — importação única do Brawlify (FEITA 17/07/2026)

- A Supercell só expõe as últimas **25 batalhas**; batalha antiga só existe em
  quem gravou na época. Descoberta importante: **o brawlify.com rastreava a tag
  do usuário desde 15/11/2025** (245 dias, 1.030 batalhas, 652V/377D = 63%).
- O Brawlify é protegido por Cloudflare → scraping automático IMPOSSÍVEL.
  A coleta foi feita **uma única vez, manualmente**: usuário passou o security
  check no navegador, Claude extraiu os cards diários de cada mês via JS no DOM
  (`/player/TAG/history?year=&month=`), salvou em `dados_brawlify/*.json`.
- `python -m app.importar_brawlify dados_brawlify` parseia e grava nas tabelas
  `historico_diario` (57 dias: batalhas/V/D/delta + brawlers do dia em JSON +
  `trofeus_fim` reconstruído por soma reversa de deltas ancorada em 73.118 no
  dia 17/07/2026) e `historico_brawler` (agregados: EMZ 103 jogos 57% etc.).
  Import é idempotente (INSERT OR REPLACE).
- Também importado (17/07/2026): `dados_brawlify/brawlers_cards.json` — página
  `/player/TAG/brawlers`, cards `article.brawler-card` com V/D totais do período
  POR BRAWLER + detalhe por modo. Atenção: cada card lista só os ~4 modos mais
  jogados; V/D totais são exatos (linha BATTLES), mas `trofeus_delta` somado dos
  modos pode subcontar em brawlers muito jogados. Winrate = V/(V+D), empates fora.
- O battle log batalha-por-batalha do Brawlify é PAGO ($4.99/mês) — não temos.
- Se o usuário quiser atualizar no futuro: repetir o processo manual (ele passa
  o check, extrair só os meses novos). NÃO tentar automatizar o bypass.
- **17/07/2026 — repetido para a camila (#2QLLLGV0R0)**: 9 dias (06/02→17/07),
  212 batalhas, 31 brawlers → `dados_brawlify_camila/`. O importador agora é
  genérico: `python -m app.importar_brawlify <pasta> [#TAG] [DATA=TROFEUS_FIM]`.
  Cards com "Trophy Milestone" viram âncoras absolutas intermediárias (a camila
  tem gaps enormes de rastreamento; sem isso a soma reversa dava valores errados).

### 3.6b ROTEIRO — importar o Brawlify de uma tag nova (processo manual, ~2 min)

> O app NUNCA acessa o Brawlify sozinho (Cloudflare). Isto é feito pelo Claude
> numa sessão Cowork com o **Chrome do usuário aberto** (extensão do Claude ativa).
> O Brawlify só tem passado de tags que alguém já visitou lá — se o perfil
> nunca foi aberto no site, não há nada a importar (a visita inicia o tracking).

1. Abrir `https://brawlify.com/player/TAG/history` no Chrome do usuário
   (o security check da Cloudflare geralmente passa sozinho; senão o usuário clica).
2. Conferir o "BATTLE HISTORY SUMMARY" (X battles / Y days tracked) — anotar os
   totais para validar no fim.
3. Na seção MONTH, clicar em cada aba de mês e extrair os cards diários via JS:
   elementos com texto `YYYY-MM-DD` → subir ao card → `innerText` com linhas
   unidas por `|`. Formato: `{"data": "YYYY-MM-DD", "txt": "...|N battles|...|Battle Summary|W|Wins|L|Losses|...|Brawlers Played|NOME|kx|±d|..."}`.
   Manter o trecho "Trophy Milestone|N Trophies" quando existir (âncora absoluta).
4. Abrir `/player/TAG/brawlers`, rolar até o fim (lazy load), extrair os
   `article` que contêm "BATTLES" (innerText com `|`) → `brawlers_cards.json`.
5. Salvar em `dados_brawlify_<nome>/` como `YYYY_MM.json` (um por mês) +
   `brawlers_cards.json`. Validar: soma de battles/W/L/delta dos dias == summary.
6. Importar: `python -m app.importar_brawlify dados_brawlify_<nome> "#TAG" DATA=TROFEUS_FIM`
   (âncora = troféus atuais do jogador no dia da extração; ver topo do perfil).
7. Adicionar a linha de import no `rodar.bat` (bloco "historicos do Brawlify")
   e registrar no plano.md. O import é idempotente e por tag (não afeta as outras).
- Daqui pra frente quem acumula é o nosso rastreador: tarefa agendada
  `ApiDoBrawl_Rastreio` (instalar com `instalar_rastreio.ps1`).

### 3.4c Meta por MAPA — brawltime.ninja tier lists (VALIDADO 17/07/2026)

- `https://brawltime.ninja/tier-list/mode/{modo-slug}/map/{Mapa-Com-Hifens}`
  (ex.: `mode/gem-grab/map/Gem-Fort`) — página **SSR**: o HTML cru já contém
  as tabelas (verificado via fetch no navegador do usuário; o container cloud
  é bloqueado por proxy, mas a máquina do usuário acessa normal).
- Tabela 1: "Adjusted Win Rate" por brawler NO MAPA (amostra global enorme,
  ex. 888k batalhas). Tabela 2: "Best Teams" do mapa (combinações + vitórias).
- Implementado em `app/coleta/brawltime.py` (`coletar_meta_mapa`, cache 6 h,
  falha → None). Alimenta o Score v2 de picks e a distribuição de time.
- `api.brawlify.com` retestada em 17/07/2026: ainda 522 (fora do ar).

### 3.4d 5ª fonte — brawlytix.com (VALIDADA 17/07/2026)

- `https://brawlytix.com/player/{TAG_SEM_HASH}` — server-rendered, raspável.
- Dados ÚNICOS: horas jogadas (estimadas por XP), skill score 0-10, valor
  estimado da conta em gems, Elo ranked numérico (atual + recorde), XP,
  prestige, wins/hora, skins por raridade c/ valor, progressão (SP/gadgets/
  gears faltando, power points/coins até maxar), fama. 42 pares no total.
- Estrutura: `div.stat-box > div.stat` (valor) + `<label>` (nome); skill/
  account value via regex no texto. `app/coleta/brawlytix.py`, cache 6 h,
  falha → None. Seção "Conta (Brawlytix)" na aba Tudo do jogador.
- Também tem battle log com RANK de showdown e "recommended picks" próprios
  (não usados por ora — nosso Score v2 já cobre).

### 3.4e Acessórios por brawler — brawltime `/tier-list/brawler/{slug}` (VALIDADO 17/07/2026)

- SSR raspável. Tabelas transpostas: linha 1 = nomes (em `<a title>`), linha
  "Win Rate" = winrate por coluna. Dá o melhor Star Power/Gadget/Gear do brawler
  (GLOBAL, não por mapa — o tab por mapa é client-side/cube API, frágil).
- `app/coleta/brawltime.coletar_acessorios_brawler(nome)`, cache 24h, falha→None.
- Cruzado com os nomes que o jogador POSSUI (parser do brawlace estendido:
  `star_powers_nomes`/`gadgets_nomes`/`gears_nomes`) em `meta.cruzar_acessorios`.

### 3.5 Regras de coleta (OBRIGATÓRIAS)

- **Sempre** enviar User-Agent de navegador:
  `Mozilla/5.0 (Windows NT 10.0; Win64; x64)` — sem UA o site pode bloquear
- **Cache em disco obrigatório** antes de qualquer request:
  perfil TTL 10 min · meta TTL 6 h · eventos TTL 1 h
- Máximo **1 request por segundo**; nunca crawlear em massa — só a tag consultada
- Todo parser deve ter **teste com fixture HTML salvo** em `tests/fixtures/`
  (scraping quebra quando o site muda de layout; o teste offline detecta isso)
- Parsing falhou / campo sumiu → levantar exceção clara com o nome do campo,
  nunca retornar dado parcial silenciosamente

---

## 4. INDICADORES (PARTE 2) — especificação

Calculados com pandas em `app/indicadores/performance.py`:

| Indicador | Fonte | Cálculo |
|---|---|---|
| Winrate geral | battle log acumulado no SQLite | vitórias / (vitórias+derrotas), excluir draws do denominador |
| Winrate por modo | battle log | mesmo cálculo agrupado por `modo` |
| Winrate por brawler | battle log | agrupado pelo brawler usado pelo jogador |
| Uso por brawler | battle log | % de partidas com cada brawler |
| Queda de troféus | tabela de brawlers | `(highest - atual) / highest` — brawlers "em queda" |
| Evolução de troféus | snapshots SQLite | série temporal de `trofeus` por consulta |

**Adicionados 24/07/2026** (todos em `performance.calcular_indicadores` sobre `decididas`, salvo indicado):

| Indicador | Função | Observação |
|---|---|---|
| Forma recente | `_forma_recente` | winrate últimas 20 / últimos 7 dias + saldo de troféus + streak atual |
| Winrate por modo (+⭐ +duração) | `_agrupado(..,"modo")` | star player e duração média por grupo |
| Winrate por mapa | `_agrupado(..,"mapa")` | idem por mapa |
| Melhor brawler por modo | `_melhor_brawler_por_modo` | Wilson, mín. 3 jogos |
| Modo × brawler / Mapa × brawler | `_cruz_brawler(..,chave)` | cada brawler em cada modo/mapa (chaves genéricas `grupo`/`jogos`) |
| Detalhe por brawler (cards) | `_brawler_detalhado` | por brawler: sub-tabelas por modo e por mapa |
| Troféus líquidos por brawler | `_trofeus_por_brawler` | soma do `trophyChange` (ganho/perda/saldo) |
| Quando joga melhor | `_por_periodo` | winrate por faixa do dia e dia da semana (BRT = UTC-3) |
| Duração × resultado | `_duracao_x_resultado` | duração média vitórias vs derrotas |
| Evolução do Ranked | `_evolucao_ranked` | rank points extraídos de `ranked_atual` dos snapshots |
| Rivais (head-to-head) | `social()` | vs jogadores enfrentados 3+ vezes |
| Melhores matchups | `social()` | contra quais brawlers você domina (além do "sofre") |
| Lift de parceiro + seu melhor brawler junto | `social()` | winrate com vs. sem cada aliado |
| Star em derrota | `star_player()` | MVP mesmo perdendo |
| Brawlers meta ociosos | `meta.brawlers_meta_ociosos` | você tem (power≥9), forte no meta, joga pouco |
| Score vs meta + mapa | `meta.score_vs_meta` | detalhe por (modo, mapa, brawler) |
| Evolução do score vs meta | `db.historico_score_meta` | gráfico da série `score_meta_historico` (1/dia) |

> UI: **índice navegável** (âncoras `#id` com scroll suave) no topo de `jogador.html`;
> só lista as seções que existem naquela aba. **Cards de brawler** usam `<details>`.
> Home: contagem de stars no ranking + botão "Copiar ranking (WhatsApp)".

> O battle log só expõe as últimas 25 partidas. O valor do SQLite é **acumular**:
> cada consulta insere as batalhas novas (dedupe por hash) — com o tempo o
> histórico fica rico. Deixar claro na UI quando a amostra é pequena (<20 partidas).

## 5. META E CORRELAÇÃO (PARTE 3) — especificação

`app/indicadores/meta.py`:

- **Tier por modo:** posição de cada brawler no ranking de Star Player % do /meta
- **Score vs meta do jogador:** para os brawlers mais jogados dele (parte 2),
  média ponderada da posição no meta dos modos que ele joga →
  "você joga com brawlers meta?" (score 0–100)
- **Sugestão de picks:** cruzar eventos ativos (/events) × meta do modo ×
  brawlers do jogador com maior power/troféus → "para o mapa X, seus melhores
  picks são A, B, C"

## 6. BANCO — SQLite (`data/brawl.db`)

```sql
CREATE TABLE jogadores (
  tag TEXT PRIMARY KEY,           -- '#299PGGLQL'
  nick TEXT,
  primeiro_visto TEXT,            -- ISO 8601 UTC
  ultimo_visto TEXT
);
CREATE TABLE snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tag TEXT REFERENCES jogadores(tag),
  criado_em TEXT,                 -- ISO 8601 UTC
  trofeus INTEGER, trofeus_max INTEGER, level INTEGER,
  vitorias_3v3 INTEGER, vitorias_solo INTEGER, vitorias_duo INTEGER,
  ranked_atual TEXT, ranked_max TEXT,  -- ex.: 'GOLD I (1601)'; o nº = rank points
  win_streak_max INTEGER,         -- maior sequência de vitórias (adicionado 24/07)
  brawlers_json TEXT              -- tabela de brawlers inteira em JSON
);
-- IMPORTANTE (17/07/2026): o hash do brawlace é GLOBAL por batalha — a mesma
-- partida tem o mesmo hash em qualquer perfil (verificado na prática comparando
-- o battle log de 2 jogadores da mesma partida). Por isso `batalhas` guarda UMA
-- linha por batalha física e os dados por jogador ficam em `batalha_jogadores`.
-- Consultar um jogador alimenta o histórico de TODOS os participantes (o
-- resultado do consultado determina o time vencedor → resultado dos 6).
-- Migração automática do schema antigo em db._migrar_para_batalhas_globais().
CREATE TABLE batalhas (
  hash TEXT PRIMARY KEY,          -- hash de 40 chars do brawlace (único e GLOBAL)
  ocorrida_em TEXT,               -- do <time datetime>
  modo TEXT,                      -- 'HOT ZONE'
  tipo TEXT,                      -- 'RANKED' | 'TROPHIES'. REGRA (24/07): quem
                                  -- move troféu é só a ladder. type="ranked" da
                                  -- Supercell = ladder de TROFÉU (brawlace mostra
                                  -- "RANKED - MODO"). Classificar por trophyChange:
                                  -- delta != 0 → TROPHIES; sem delta → Ranked.
  mapa TEXT,
  duracao_seg INTEGER,
  time_vencedor INTEGER           -- índice do time vencedor (NULL: draw/showdown)
);
CREATE TABLE batalha_jogadores (
  hash TEXT, tag_jogador TEXT, nick TEXT, brawler TEXT, power INTEGER,
  trofeus INTEGER, time INTEGER, resultado TEXT, trofeus_delta INTEGER,
  star_player INTEGER, PRIMARY KEY (hash, tag_jogador)
);
CREATE TABLE meta_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  data TEXT, modo TEXT, brawler TEXT,
  star_player_pct REAL, posicao INTEGER
);
CREATE TABLE score_meta_historico (   -- evolução do score vs meta (add 24/07)
  tag TEXT, dia TEXT, score REAL,      -- 1 ponto/dia; gravado a cada consulta
  PRIMARY KEY (tag, dia)
);
```

## 7. ROTAS

| Rota | Tipo | Descrição |
|---|---|---|
| `GET /` | HTML | home: input de tag + últimos jogadores consultados |
| `GET /jogador/{tag}` | HTML | página completa: stats, indicadores, gráfico, meta |
| `GET /api/jogador/{tag}` | JSON | mesmos dados em JSON |
| `GET /api/meta` | JSON | meta atual por modo |

Fluxo de `/jogador/{tag}`: normaliza tag → cache/scrape perfil → grava snapshot +
batalhas novas → calcula indicadores → cache/scrape meta → correlaciona → renderiza.

## 8. CONVENÇÕES

- Nomes de variáveis, funções e UI em **português** (padrão dos projetos do usuário)
- Tipagem explícita em todas as assinaturas (`def winrate(df: pd.DataFrame) -> float:`)
- UI em português (pt-BR)
- `data/brawl.db` é **versionado** (backup dos dados insubstituíveis); `data/cache/`,
  logs e WAL/SHM ficam fora do git; fixtures de teste DENTRO do git. O backup só
  atualiza quando o `.db` é commitado — fazer `PRAGMA wal_checkpoint(TRUNCATE)` antes
- Sem ORM, sem async desnecessário, sem framework de frontend — simplicidade primeiro
- **Nunca** usar `--no-verify` nos commits; **nunca** adicionar `Co-Authored-By`

## 9. RISCOS CONHECIDOS

| Risco | Mitigação |
|---|---|
| brawlace.com muda o layout → parsers quebram | fixtures + exceções claras por campo |
| brawlace.com adota Cloudflare no futuro | reavaliar com o usuário: API oficial (developer.brawlstars.com + proxy RoyaleAPI) é o plano B já discutido |
| Battle log só tem 25 partidas | SQLite acumula; avisar na UI quando amostra < 20 |
| Rate limit / bloqueio por abuso | cache com TTL + 1 req/s + só a tag consultada |
