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
  (8 quesitos com `PESOS_ROTA` por rota, menos a posição normal da rota em `ESPERADO`, que a
  coleta recalcula com `base_notas` no builds.json; sem rota usa 5 quesitos iguais), MVP/ACE/NTP (NTP = menor nota dos 10), odds das apostas.
- `imagens.py` — Pillow: cartão de `/perfil`.
- `coleta.py` — `/build`: coleta própria de partidas Solo/Duo (420) e Flex (440) de jogadores Mestre+ de
  KR, EUW e BR (League-V4 + Match-V5 + timeline). Guarda só contadores em `builds.json` (2 patches mais novos,
  combinações raras cortadas, até 300 mil ids de partidas vistas). KR/EUW têm `Limitador` próprio (o limite da
  Riot é por região); BR usa o limitador principal e só até 50% dos 100/2min, para sobrar para os alertas.
  Ritmo: `COLETA_PARTIDAS_HORA` por região (padrão 120; ~85 KB por partida). O OP.GG foi removido (2026-11-11).
  Também conta confrontos (`contra`: campeão inimigo da mesma rota) para o `/counter`, faz a `/tierlist`
  (winrate ajustada: (v+25)/(j+50)) e chama `ao_patch_novo` quando aparece um patch mais novo.
- `loja.py` — catálogo (`ITENS`) e regras da loja (`DadosLoja`: enfeite 👑/emoji, seguro/odd turbinada nas
  apostas, rifa, desafio Bravery, escudo, imunidade de 10 min, `pendentes` para desmutar/devolver apelido).
  Os comandos `/loja`, `/comprar`, `/bloquear-apelido`, `/config-loja`, o `loop_loja` (20 s) e o
  `on_voice_state_update` (desmuta quem volta para a call) ficam no `bot.py`. Compra só é cobrada se o efeito der certo.
- `dados.py` — persistência em `dados.json` (vínculos, canal de alertas, partidas em andamento,
  pendentes, histórico, moedas, controle do resumo semanal). Tudo indexado por id do servidor.
- `config.py` — lê o `.env`.

## Comandos
`/elo`, `/historico`, `/maestria`, `/perfil` (imagem), `/aovivo` (raio-X dos 10 jogadores), `/build campeão [rota] [modo]` (coleta própria Mestre+, modo Solo/Duo ou Flex; mínimo 20 partidas, usa o patch anterior se o atual tiver pouco), `/ultimate-bravery [mapa]` (sorteio; itens/feitiços baixados no 1º uso, IDs < 10000),
`/vincular`, `/desvincular`, `/ranking [fila]` (Solo/Duo e Flex),
`/semana`, `/mvp` (contagem de MVP e NTP dos últimos 7 dias; histórico grava `ntp`), `/duplas`, `/duelo`, `/tierlist`, `/counter`, `/comparar`, `/carteira`, `/diario`, `/top-moedas`, `/loja`, `/comprar`, `/bloquear-apelido`, `/config-loja`, `/config-alertas`, `/desativar-alertas`, `/ajuda`.

## Fluxo dos alertas (`loop_partidas`, a cada `INTERVALO_ALERTA_MIN`)
1. Para cada servidor com canal de alertas, checa o Spectator-V5 de cada membro vinculado.
2. Partida nova → salva elo de antes, posta raio-X + botões de aposta (Azul/Vermelho, abertas por
   `TEMPO_APOSTAS_MIN`). Amigos na mesma partida viram um único aviso.
3. Fim da partida: o `loop_resultados` (a cada 30 s) pergunta direto ao Match-V5 por `BR1_{gameId}` das
   partidas com mais de 14 min (`checar_fim_antecipado`); o spectator (2 min) também detecta (remakes).
   Vai para `pendentes`, espera a Riot atualizar o PDL (até 4 min), posta o resumo (nota, MVP, PDL, pentakill), paga as
   apostas (remake devolve), dá moedas (+50 vitória, +100 MVP/ACE) e grava no histórico.
4. `loop_semanal`: domingo 20h (configurável) posta o resumo da semana; MVP ganha +500 moedas; sorteia a rifa.
5. O resumo pós-partida também registra notas dos duelos (`duelos` no dados.json; expiram no `loop_loja`) e
   avisa sequências (`aviso_sequencia`). O histórico agora guarda `jogo` e `time` (usados no `/duplas`).
6. `loop_status` (10 min): LoL-Status-V4 do BR; avisa início/fim de manutenções e incidentes (`geral.status_ativos`).

## Estado e limitações conhecidas
- Testado só com dados simulados (o ambiente onde foi escrito não acessava a Riot). Bugs reais
  podem aparecer com respostas de verdade da API — peça o log do terminal ao usuário.
- A coleta de builds voltou (2026-11-11) para rodar no servidor de um amigo (até 2 GB). Na Discloud grátis (100 MB), use
  `COLETA_BUILDS=nao`. O bot também usa `max_messages=None`.
- Hospedagem: Discloud (plano grátis, 100 MB, app id 1794358509464). Atualizar com `python montar_zip.py`
  e arrastar o `bot-discloud.zip` na página Commit. O zip leva `.env` mas **nunca** o `dados.json`: o commit
  da Discloud só troca os arquivos enviados, e o `dados.json` de lá é a fonte da verdade (o do PC está velho).
- Ao trocar a chave da Riot, o bot reconverte os PUUIDs sozinho no início (`atualizar_puuids`).
- Apostas usam moedas fictícias sem valor real (importante para as políticas da Riot).
- Código público no GitHub (mmolinadias/bot-moskitroll), usado como "Product URL" da Personal Key.
