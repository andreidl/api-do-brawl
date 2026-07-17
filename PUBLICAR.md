# Publicar o site do clã no GitHub Pages (grátis, sem servidor)

O site é uma **foto** navegável: rankings, composições, perfis e o "Jogar agora".
Consulta de tag nova e dados minuto-a-minuto continuam só na versão local (seu PC).

## Configurar (uma única vez)

1. Crie um repositório no GitHub (ex.: `api-do-brawl`). Pode ser **privado** ou público
   — para o GitHub Pages funcionar de graça em repo privado você precisa de conta Free
   mesmo (Pages funciona em público sempre; em privado exige Pro). Se for para o clã
   inteiro ver, use **público**.
2. Na pasta do projeto, ligue o repositório (troque SEU-USUARIO/SEU-REPO):
   ```
   git remote add origin https://github.com/SEU-USUARIO/SEU-REPO.git
   git branch -M main
   git push -u origin main
   ```
3. No GitHub: **Settings → Pages → Build and deployment → Source: Deploy from a branch**,
   Branch: **main** / pasta **/docs** → Save.
4. Em ~1 minuto seu site fica no ar em:
   `https://SEU-USUARIO.github.io/SEU-REPO/`

## Atualizar o site (sempre que quiser)

Só dê **dois cliques no `publicar.bat`**. Ele raspa os dados atuais, gera a foto nova
e sobe para o GitHub. O link do clã atualiza sozinho em ~1 minuto.

> Dica: rode o `rodar.bat` de vez em quando (ou deixe aberto) para o rastreador
> acumular batalhas; depois `publicar.bat` para o clã ver a versão mais rica.
