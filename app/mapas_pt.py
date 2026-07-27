"""Tradução EN -> PT-BR dos nomes de mapas do Brawl Stars.

Nem a API oficial da Supercell nem o Brawlify expõem o nome dos mapas em
português — só em inglês. O nome PT-BR que aparece no jogo vem do arquivo de
localização interno do cliente, que não tem API pública fetchável e atual.

Por isso esta tabela é curada à mão. Para adicionar/corrigir um mapa:
  - a CHAVE é o nome em inglês, exatamente como vem da API (ex.: "Safe Zone");
  - o VALOR é o nome como aparece no jogo em pt-BR (ex.: "Zona Segura").
A busca ignora maiúsc./minúsc., então "Slippery road" casa com "Slippery Road".
Mapas sem entrada aqui aparecem em inglês (fallback) — sem risco de nome errado.

Como você joga em pt-BR e vê os nomes reais, é só ir preenchendo aqui embaixo.
"""

# Semente com traduções oficiais conhecidas. Expanda à vontade.
MAPAS_PT: dict[str, str] = {
    # Gem Grab / Pegue a Gema
    "Hard Rock Mine": "Mina Hard Rock",
    "Crystal Arcade": "Arcade de Cristal",
    "Deathcap Trap": "Armadilha Cogumelo",
    "Undermine": "Subterrâneo",
    "Rustic Arcade": "Arcade Rústico",
    "Last Stop": "Última Parada",
    "Open Space": "Espaço Aberto",
    "Acute Angle": "Ângulo Agudo",
    # Showdown / Sobrevivência
    "Skull Creek": "Riacho da Caveira",
    "Feast or Famine": "Banquete ou Fome",
    "Rockwall Brawl": "Muro de Pedra",
    "Cavern Churn": "Caverna Revolta",
    "Stormy Plains": "Planícies Tempestuosas",
    "Safe Zone": "Zona Segura",
    "Dark Passage": "Passagem Escura",
    "Rice Field": "Campo de Arroz",
    "Sneaky Fields": "Campos Furtivos",
    # Brawl Ball / Futebrawl
    "Backyard Bowl": "Estádio do Quintal",
    "Super Beach": "Superpraia",
    "Sunny Soccer": "Futebol Ensolarado",
    "Triple Dribble": "Drible Triplo",
    "Sneaky Sneak": "Ataque Furtivo",
    "Pinball Dreams": "Sonhos de Pinball",
    "Center Stage": "Palco Central",
    # Bounty / Caça-Estrelas
    "Shooting Star": "Estrela Cadente",
    "Snake Prairie": "Pradaria da Cobra",
    "Canal Grande": "Canal Grande",
    "Hideout": "Esconderijo",
    "Layer Cake": "Bolo de Camadas",
    "Dry Season": "Estação Seca",
    # Heist / Ataque ao Cofre
    "Kaboom Canyon": "Cânion Explosivo",
    "Safe Zone (Heist)": "Zona Segura",
    "Hot Potato": "Batata Quente",
    "Pit Stop": "Pit Stop",
    "Safety Center": "Central de Segurança",
    # Knockout / Nocaute
    "Goldarm Gulch": "Desfiladeiro Braço de Ouro",
    "Belle's Rock": "Rocha da Belle",
    "Flaring Phoenix": "Fênix Flamejante",
    "Out in the Open": "A Descoberto",
    "New Horizons": "Novos Horizontes",
    "Four Levels": "Quatro Níveis",
    # Hot Zone / Zona Restrita
    "Ring of Fire": "Anel de Fogo",
    "Open Business": "Negócio Aberto",
    "Parallel Plays": "Jogadas Paralelas",
    "Dueling Beetles": "Besouros em Duelo",
    # Diversos / eventos
    "Training Island": "Ilha de Treino",
    "Under Pressure": "Sob Pressão",
    "Twisting Vines": "Vinhas Retorcidas",
    "Raging Ocean": "Oceano Furioso",
}

# Índice normalizado (minúsculas) para busca tolerante a caixa.
_NORM: dict[str, str] = {k.strip().lower(): v for k, v in MAPAS_PT.items()}


def mapa_pt(nome: str | None) -> str | None:
    """Nome do mapa em pt-BR, ou o próprio nome (em inglês) se não houver tradução."""
    if not nome:
        return nome
    return _NORM.get(nome.strip().lower(), nome)
