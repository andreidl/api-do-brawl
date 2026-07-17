# PLANO — API do Brawl

> Fila priorizada. Trabalhar de cima para baixo. Marcar `[x]` ao concluir
> e mover para CONCLUÍDO com a data.

## P0 — Fundação (sem isso nada funciona) — ✅ CONCLUÍDO 17/07/2026

- [x] Scaffold: `requirements.txt`, venv, `app/main.py` com FastAPI + rota `/`
- [x] `app/coleta/cache.py` — cache em disco com TTL (perfil 10min, meta 6h, eventos 1h)
- [x] `app/coleta/brawlace.py` — `coletar_perfil(tag)`:
  - [x] Baixar HTML com User-Agent correto, tratar 404 (tag inválida)
  - [x] Parsear stats gerais (nick, level, troféus, ranked, vitórias 3v3/solo/duo)
  - [x] Parsear tabela de brawlers
  - [x] Parsear battle log (25 partidas: hash, modo, tipo, mapa, brawler, resultado, duração, timestamp, star player)
  - [x] Salvar fixture HTML em `tests/fixtures/` + testes pytest de parsing
- [x] `app/db.py` — schema do CLAUDE.md §6 + upsert de jogador/snapshot/batalhas (dedupe por hash)

## P1 — Indicadores (parte 2) — ✅ CONCLUÍDO 17/07/2026

- [x] `app/indicadores/performance.py` — winrate geral/por modo/por brawler, uso por brawler, queda de troféus (pandas)
- [x] Evolução de troféus a partir dos snapshots (1 ponto/dia, gráfico SVG inline)
- [x] Página `GET /jogador/{tag}` com tudo renderizado (Jinja2)
- [x] `GET /api/jogador/{tag}` em JSON
- [x] Aviso de "amostra pequena" quando < 20 batalhas acumuladas
- [x] `app/rastrear.py` — rastreamento automático de todos os jogadores do banco (log em data/rastreio.log)
- [x] ~~USUÁRIO precisa rodar `instalar_rastreio.ps1`~~ — APOSENTADO em 17/07/2026: nunca foi instalado e o PC não fica sempre ligado. Substituído pelo rastreio embutido no app (P4).

## P2 — Meta e correlação (parte 3) — ✅ CONCLUÍDO 17/07/2026

- [x] `coletar_meta()` — parseia /meta (14-15 modos, ranking por Star Player %) + fixture + testes
- [x] `coletar_eventos()` — parseia /events aba ativa (modo + mapa + horários) + fixture + testes
- [x] `app/indicadores/meta.py` — score vs meta 0-100 (percentil ponderado por partidas) + sugestão de picks por evento ativo (meta do modo × brawlers do jogador com power ≥ 9)
- [x] Integrado na página do jogador (seção "Meta atual e recomendações") + `GET /api/meta`
- [x] `meta_snapshots` gravado no SQLite a cada coleta (dedupe por data+modo+brawler)

## P4 — Backlog priorizado (entrevista com o usuário, 17/07/2026)

- [x] **Rastreio embutido no app** — thread em background (10s após o start + a cada 30 min com o app aberto), com lock anti-sobreposição; status da última rodada na home. Task Scheduler/`instalar_rastreio.ps1` APOSENTADOS (nunca tinham sido instalados). Desligável com `BRAWL_RASTREIO=0`
- [x] **Página instantânea** — jogador conhecido abre em ~150ms direto do banco (novo `db.perfil_do_banco`), mesmo com o brawlace fora do ar; JS dispara `POST /api/refrescar/{tag}` em segundo plano e recarrega UMA vez se houver batalha nova. Jogador inédito segue o fluxo com scraping
- [x] **Separar ranked × troféus** — abas Tudo/Troféus/Ranked com conteúdo próprio por aba (cartões, seções e indicadores). Corrigido parser do header de showdown ('RANKED | RANK n - MODO') + reparo automático de 40 batalhas corrompidas + rank guardado no snapshot
- [ ] **Composição de times** — winrate por dupla/trio de jogadores E por combinação de brawlers, todas as combinações vistas em batalha_jogadores
- [x] **Picks personalizados** — score do pick = 50% meta + 50% desempenho do jogador (Wilson), priorizando o winrate NAQUELE modo (70/30 sobre o geral, via `historico_brawler_modo` + batalhas acumuladas). UI mostra '%X neste modo (Nj)'
- [x] **Clube Snake** — roster real coletado de /clubs/%238LG0QGLC (cache 6h, atualiza a cada consulta/rastreio), ranking da home filtrado por membros + seção "Conhecidos de fora do clube". (Pendente: botão de print p/ WhatsApp)
- [x] **Tags novas → pendência de importação** — home lista consultados sem `historico_diario` com instrução de pedir a importação ao Claude (§3.6b); some sozinho após importar
- [ ] **Composições × evento ativo** — sugerir o melhor trio/comp do clube para cada mapa em rotação (aguardar mais amostra acumulada)
- [ ] **Composições por modo** — dividir duplas/trios por modo quando houver ~200+ batalhas acumuladas (hoje fragmentaria demais)
- [x] **Detecção de reset de temporada** — `detectar_resets`: queda ≥500 troféus entre snapshots não explicada pelos deltas das partidas → aviso '🔄 provável reset' acima da curva de evolução, com os números da discrepância
- [x] **Pesquisa de novas fontes** — varredura 17/07/2026: brawltime por mapa INTEGRADO (§3.4c), **brawlytix.com integrado como 5ª fonte** (§3.4d — horas, skill score, valor da conta, Elo, skins, progressão), api.brawlify segue morta (522), brawlstats.com tem Cloudflare (só manual), brawltracker/noff.gg não promissores

## P3 — Polimento

- [x] Home com últimos jogadores consultados (já existia; estilizada como lista `.recentes`)
- [x] CSS decente (tema escuro, cores do Brawl Stars) — `estilo.css` reescrito: paleta navy + amarelo #ffce00 + azul, gradientes, cartões com hover, tabelas com destaque V/D, botão estilo jogo, responsivo mobile
- [x] Tratamento de erros amigável na UI — `erro.html` com painel destacado; home agora exibe mensagem quando `?erro=tag`
- [x] git init + primeiro commit (repositório publicado em github.com/andreidl/brawlapiteste)
- [ ] Avaliar deploy (só se o usuário pedir — por ora roda local)

## CONCLUÍDO

- [x] 17/07/2026 — **Revisão holística (4 revisores em paralelo) + correções**. Bugs corrigidos:
  - 🔴 CRÍTICO: `meta._fator_meta_v2` dividia o percentil (já 0–1) por 100 → peso do meta nos picks era ~0. Corrigido; o meta volta a pesar 50%.
  - 🔴 CRÍTICO: `brawltime.py` sem `import re` → `coletar_acessorios_brawler` dava NameError sempre → "Jogar agora" caía com 500 em produção. Corrigido + coleta e `_acess_meta` blindados (nunca derrubam a página).
  - 🟠 `exportar.py`: links "Jogar agora" dos não-donos apontavam para arquivos inexistentes (404 no site). Agora só o dono tem link ativo.
  - 🟠 Migração de banco resumível (crash no meio não perde mais dados; tabelas *_antigas órfãs são retomadas).
  - 🟠 `cache.salvar` atômico (tmp+rename) — sem HTML parcial com rastreio concorrente.
  - 🟡 `_tendencias_meta_seguro` agora captura erro de SQLite; `ranking_jogadores` guarda mínimo≥1; `_queda_trofeus` tolera snapshot antigo sem troféus; header de showdown sem Victory/Defeat infere pelo delta; brawlytix aceita valor com decimal; star_player na migração com COALESCE.
  - Revisores confirmaram corretos: dedup de batalhas, JOINs sem duplicação, Wilson, composições, detecção de reset, tratamento de erro não-fatal. **85 testes passando (5 novos de regressão).**


- [x] 17/07/2026 — **Acessórios: o que equipar** (foco do produto). Parser do brawlace estendido p/ capturar NOMES de star powers/gadgets/gears que cada jogador possui. Nova fonte `brawltime.ninja/tier-list/brawler/{slug}` (SSR raspável) com o melhor SP/gadget/gear por brawler (global). `cruzar_acessorios` junta os dois: cada pick do "Jogar agora" mostra "SP: X ✓ / Gadget: Y ⚠️ / Gear / ⚡hyper" — verde se você tem o recomendado, amarelo se falta. Aplicado aos picks e à distribuição de time.

- [x] 17/07/2026 — **Publicação estática (GitHub Pages)**. `app/exportar.py` gera `docs/` navegável (home + perfis + Jogar agora), CSS embutido, links reescritos, interatividade neutralizada, banner "foto do clã". `publicar.bat` (2 cliques: raspa → gera → git push) + guia `PUBLICAR.md`. Trade-off aceito: foto atualizada na publicação; ao vivo só local. **81 testes passando.**


- [x] 17/07/2026 — **Brawlify de BIGBOSS e gustavo importados**: BIGBOSS (#9029RVG2J) 28 dias/362 batalhas 68% (dez/2025→jul/2026, 48 brawlers); gustavo (#28GY9QJVC) 20 dias/291 batalhas 79% (dez/2025→jul/2026, 30 brawlers). Totais validados exatos contra o resumo do site. Importador agora pula cards sem batalhas (só unlocks). Todos os 4 membros do trio+ com histórico de longo prazo no banco. `rodar.bat` importa os 4.


- [x] 17/07/2026 — **Score v2 + brawltime por MAPA**: nova fonte validada — páginas SSR `brawltime.ninja/tier-list/mode/X/map/Y` (winrate AJUSTADO por brawler no mapa, amostra mundial de centenas de milhares de batalhas + melhores TIMES do mapa), raspáveis com httpx (parser + fixture + cache 6h em `app/coleta/brawltime.py`). Score de picks/distribuição agora = 50% meta (60% mapa + 40% modo quando há dados) + 50% desempenho pessoal + bônus de kit (SP/gadget/hyper — parser de brawlers estendido) − penalidade de troféus díspares na dupla + bônus de sinergia (combinação presente nos best teams do mapa). Distribuição respeita o tamanho do time por modo (solo=cada um por si; duo=2 e informa quem fica de fora). **73 testes passando.**


- [x] 17/07/2026 — **Unificação do banco (batalhas globais)**: verificado na prática que o hash do brawlace é o MESMO para a mesma partida em qualquer perfil (8/8 hashes idênticos entre o log do usuário e o da camila). `batalhas` virou global (1 linha por partida física, `time_vencedor`); `batalha_jogadores` guarda brawler/power/time/resultado POR participante — o resultado do consultado deriva o dos 6 jogadores, então **consultar um jogador alimenta o histórico de todos os parceiros**. Migração automática do schema antigo (corrigiu bug em que batalhas compartilhadas sumiriam do 2º jogador consultado). Validação cruzada: brawlers da camila derivados das consultas do usuário batem com o Brawlify dela. **56 testes passando.**

- [x] 17/07/2026 — **Histórico Brawlify da camila (#2QLLLGV0R0)**: 2ª extração manual (Cloudflare passou sozinho no Chrome do usuário) — 9 dias rastreados (06/02→17/07), 212 batalhas 161V/51D (76%), 31 brawlers → `dados_brawlify_camila/`. Importador generalizado: aceita `[#TAG] [DATA=TROFEUS]` na CLI, rebuild de brawlers agora apaga SÓ a tag importada (antes o DROP TABLE destruiria dados de outras tags), e "Trophy Milestone" dos cards vira âncora intermediária de troféus absolutos (essencial p/ gaps de rastreamento). `rodar.bat` importa os dois históricos a cada início. **53 testes passando.**

- [x] 17/07/2026 — **Dados dormentes + coleta turbo**: (1) nova tabela `batalha_jogadores` — todos os participantes de cada batalha (brawler/power/troféus/time/star) parseados e gravados; (2) seções "Matchups e parceiros" (contra quem você perde, winrate com cada aliado) e "Star Player" (taxa geral/por brawler); (3) tendências do meta entre datas do `meta_snapshots` (aparece com 2+ dias); (4) coleta por modo via `?filter[gameMode]=` — até 25 batalhas EXTRAS por modo (7 modos) por consulta e no rastreador, que agora também grava snapshot do meta a cada rodada. **53 testes passando.**

- [x] 17/07/2026 — **P3 (polimento visual)**: tema escuro completo estilo Brawl Stars no `estilo.css` (~230 linhas), painel de erro, mensagem de tag inválida na home, lista de recentes estilizada. Sem mudança de lógica além do parâmetro `erro` na rota `/`. **43 testes passando.**

- [x] 17/07/2026 — **Todos os brawlers do período**: extraídos os 104 cards de `/player/TAG/brawlers` do Brawlify (sessão liberada pelo usuário), importados os 82 com batalhas → `historico_brawler` rebuild (V/D/empates/winrate/troféus) + nova `historico_brawler_modo` (V/D por modo de cada brawler). Página mostra a tabela completa. **43 testes passando.**

- [x] 17/07/2026 — **P2 inteiro (meta e correlação)**: parsers de /meta e /events com fixtures, score vs meta (usuário: 84,6/100), sugestões de pick por evento ativo, `GET /api/meta`, 1.422 linhas de meta salvas em `meta_snapshots`. **40 testes passando.** As 3 partes do escopo original do projeto estão completas.

- [x] 17/07/2026 — **Importação do histórico Brawlify (245 dias)**: usuário passou o Cloudflare check no navegador, extraídos 57 dias de jogo (nov/2025→jul/2026) = 1.030 batalhas 652V/377D (63%), +3.527 troféus. Novas tabelas `historico_diario` + `historico_brawler`, troféus absolutos reconstruídos por soma reversa (69.591→73.118, validado contra o resumo do site). Seção "Histórico de longo prazo" na página com gráfico de 8 meses. **29 testes passando.** Processo documentado no CLAUDE.md §3.6 (repetível manualmente; nunca automatizar bypass).

- [x] 17/07/2026 — **Seção Carreira + passado possível**: gráfico de troféus embutido do brawlace (`grafico_trofeus`), fonte complementar brawltime.ninja (`app/coleta/brawltime.py` — ano da conta, record points), seção "Carreira (vida inteira)" na página. Documentada no CLAUDE.md a resposta definitiva sobre "mais passado" (25 batalhas = limite da Supercell). **25 testes passando.**

- [x] 17/07/2026 — **P1 inteiro**: indicadores com pandas (winrate geral 44%, por modo, por brawler, queda de troféus, evolução) renderizados na página + JSON. Rastreador `app/rastrear.py` testado manualmente (2 jogadores no banco). **23 testes passando.** Falta só o usuário instalar a tarefa agendada (`instalar_rastreio.ps1`).
- [x] 17/07/2026 — **P0 inteiro**: scraper de perfil + cache TTL + SQLite com dedupe + páginas home/jogador/erro + API JSON. **16 testes pytest passando.** Validado end-to-end com a tag real #299PGGLQL (25 batalhas coletadas e gravadas; 2ª consulta deduplicou: 0 novas). Adiantado do P1: página do jogador já renderiza stats/batalhas/brawlers e `/api/jogador/{tag}` já existe.
- [x] 17/07/2026 — **Rastreio embutido + página instantânea (P4 itens 1-2)**: thread de rastreio dentro do FastAPI (30 min, lock, BRAWL_RASTREIO=0 desliga), db.perfil_do_banco serve a página em ~150ms do banco (funciona até com brawlace fora do ar), refresh em segundo plano via POST /api/refrescar com reload único, status do rastreio na home. instalar_rastreio.ps1 aposentado. **58 testes passando.**

- [x] 17/07/2026 — Decisões de produto/stack/fonte/persistência fechadas com o usuário
- [x] 17/07/2026 — Fonte validada na prática: brawlace.com raspável (brawlify bloqueado por Cloudflare)
- [x] 17/07/2026 — Estrutura de pastas, CLAUDE.md, plano.md, requirements.txt criados
