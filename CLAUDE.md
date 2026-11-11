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
  (campeões, itens, runas, feitiços), cache de imagens em `cache/`.
- `analise.py` — textos de elo, `pontuacao_elo` (100 pts = 1 divisão), nota 0–10 por percentil
  (KDA, participação, dano, ouro, visão), MVP/ACE, odds das apostas.
- `builds.py` — coleta partidas ranqueadas de Desafiante/Grão-Mestre aos poucos e agrega
  itens/botas/runas/feitiços por `campeao:rota` em `builds.json`.
- `imagens.py` — Pillow: cartão de `/perfil` e imagem do `/build`.
- `dados.py` — persistência em `dados.json` (vínculos, canal de alertas, partidas em andamento,
  pendentes, histórico, moedas, controle do resumo semanal). Tudo indexado por id do servidor.
- `config.py` — lê o `.env`.

## Comandos
`/elo`, `/historico`, `/maestria`, `/perfil` (imagem), `/aovivo` (raio-X dos 10 jogadores + botão de build),
`/build campeão [rota]`, `/vincular`, `/desvincular`, `/ranking [fila]` (Solo/Duo e Flex),
`/semana`, `/carteira`, `/diario`, `/top-moedas`, `/config-alertas`, `/desativar-alertas`, `/ajuda`.

## Fluxo dos alertas (`loop_partidas`, a cada `INTERVALO_ALERTA_MIN`)
1. Para cada servidor com canal de alertas, checa o Spectator-V5 de cada membro vinculado.
2. Partida nova → salva elo de antes, posta raio-X + botões de aposta (Azul/Vermelho, abertas por
   `TEMPO_APOSTAS_MIN`) + botões de build. Amigos na mesma partida viram um único aviso.
3. Partida sumiu do spectator → vai para `pendentes`; busca `BR1_{gameId}` no Match-V5, espera a
   Riot atualizar o PDL (até 3 tentativas), posta o resumo (nota, MVP, PDL, pentakill), paga as
   apostas (remake devolve), dá moedas (+50 vitória, +100 MVP/ACE) e grava no histórico.
4. `loop_semanal`: domingo 20h (configurável) posta o resumo da semana; MVP ganha +500 moedas.

## Estado e limitações conhecidas
- Testado só com dados simulados (o ambiente onde foi escrito não acessava a Riot). Bugs reais
  podem aparecer com respostas de verdade da API — peça o log do terminal ao usuário.
- `/build` começa vazio; depende da coleta ao longo de horas.
- Apostas usam moedas fictícias sem valor real (importante para as políticas da Riot).
- Próximos passos que o usuário mencionou: hospedar 24h de graça (sugestão: Oracle Cloud Always
  Free) e talvez publicar o código no GitHub para usar como "Product URL" no pedido da Personal Key.
