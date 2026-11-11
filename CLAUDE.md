# Bot LoL para Discord

Bot de Discord em Python (discord.py 2.4+) que usa a API oficial da Riot para mostrar dados de
League of Legends de um grupo de amigos no servidor BR1. Fale com o usuário em **português do Brasil**.
O usuário é iniciante em programação: explique passos de terminal de forma simples (ele usa Windows).

## Como rodar
- `pip install -r requirements.txt` e depois `python bot.py`
- Configuração no `.env` (modelo em `.env.exemplo`): `DISCORD_TOKEN`, `RIOT_API_KEY`, `GUILD_ID`,
  `RIOT_PLATFORM=br1`, `RIOT_REGION=americas` e opções de alertas/apostas/resumo semanal.
- **Nunca** mostrar, commitar ou enviar o conteúdo do `.env` (token do Discord e chave da Riot).
- A chave de desenvolvimento da Riot expira a cada 24h; o usuário pediu uma Personal Key.

## Arquivos
- `bot.py` — comandos slash, botões (DynamicItem persistentes), loops (`tasks.loop`).
- `riot.py` — `RiotAPI`: requisições com `Limitador` (20/s e 100/2min), Data Dragon pt_BR
  (nomes de campeões; itens e feitiços só quando usam o /ultimate-bravery), cache de imagens em `cache/` (até 100 na memória).
- `analise.py` — textos de elo, `pontuacao_elo` (100 pts = 1 divisão), nota 0–10 por percentil
  (KDA, participação, dano, ouro, visão), MVP/ACE, odds das apostas.
- `imagens.py` — Pillow: cartão de `/perfil`.
- `opgg.py` — `/build`: busca a build no serviço público (MCP) do OP.GG (`mcp-api.op.gg/mcp`, sem chave),
  lê o formato próprio deles (`class X: campos` + `X(...)`), cache de 6h. Não é API oficial: pode quebrar.
- `dados.py` — persistência em `dados.json` (vínculos, canal de alertas, partidas em andamento,
  pendentes, histórico, moedas, controle do resumo semanal). Tudo indexado por id do servidor.
- `config.py` — lê o `.env`.

## Comandos
`/elo`, `/historico`, `/maestria`, `/perfil` (imagem), `/aovivo` (raio-X dos 10 jogadores), `/build campeão [rota] [modo] [elo]` (OP.GG; elo = parâmetro `tier`, padrão do bot = master_plus nas ranqueadas e sem filtro no ARAM; URF/Nexus Blitz dão erro fora de época), `/ultimate-bravery [mapa]` (sorteio; itens/feitiços baixados no 1º uso, IDs < 10000),
`/vincular`, `/desvincular`, `/ranking [fila]` (Solo/Duo e Flex),
`/semana`, `/carteira`, `/diario`, `/top-moedas`, `/config-alertas`, `/desativar-alertas`, `/ajuda`.

## Fluxo dos alertas (`loop_partidas`, a cada `INTERVALO_ALERTA_MIN`)
1. Para cada servidor com canal de alertas, checa o Spectator-V5 de cada membro vinculado.
2. Partida nova → salva elo de antes, posta raio-X + botões de aposta (Azul/Vermelho, abertas por
   `TEMPO_APOSTAS_MIN`). Amigos na mesma partida viram um único aviso.
3. Partida sumiu do spectator → vai para `pendentes`; busca `BR1_{gameId}` no Match-V5, espera a
   Riot atualizar o PDL (até 3 tentativas), posta o resumo (nota, MVP, PDL, pentakill), paga as
   apostas (remake devolve), dá moedas (+50 vitória, +100 MVP/ACE) e grava no histórico.
4. `loop_semanal`: domingo 20h (configurável) posta o resumo da semana; MVP ganha +500 moedas.

## Estado e limitações conhecidas
- Testado só com dados simulados (o ambiente onde foi escrito não acessava a Riot). Bugs reais
  podem aparecer com respostas de verdade da API — peça o log do terminal ao usuário.
- A coleta de builds do alto elo foi removida (2026-11-10) para caber nos 100 MB da Discloud; o `/build`
  voltou usando o OP.GG. O bot também usa `max_messages=None`.
- Hospedagem: Discloud (plano grátis, 100 MB, app id 1794358509464). Atualizar com `python montar_zip.py`
  e arrastar o `bot-discloud.zip` na página Commit. O zip leva `.env` mas **nunca** o `dados.json`: o commit
  da Discloud só troca os arquivos enviados, e o `dados.json` de lá é a fonte da verdade (o do PC está velho).
- Ao trocar a chave da Riot, o bot reconverte os PUUIDs sozinho no início (`atualizar_puuids`).
- Apostas usam moedas fictícias sem valor real (importante para as políticas da Riot).
- Código público no GitHub (mmolinadias/bot-moskitroll), usado como "Product URL" da Personal Key.
