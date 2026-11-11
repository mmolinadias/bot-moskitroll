# Bot LoL para Discord — versão 2

## O que tem de novo
- **`/perfil`**: cartão de perfil em imagem com ícone, elo de Solo/Duo e Flex, campeões favoritos e as últimas 10 partidas.
- **`/aovivo`**: raio-X da partida, com elo, winrate e maestria dos 10 jogadores, e qual time é favorito.
- **Alertas de partida**: quando alguém vinculado entra em partida, o bot posta o raio-X, e os botões de **aposta**.
- **Resumo pós-partida**: resultado, KDA, dano, participação, CS, visão, **nota de 0 a 10**, **MVP/ACE**, **PDL ganho ou perdido** (avisa quando alguém sobe de elo) e pentakill.
- **Apostas com moedas fictícias**: aposte no time azul ou vermelho. A odd depende do elo dos times. Comandos: `/carteira`, `/diario` e `/top-moedas`.
- **Resumo semanal automático** (domingo às 20h): MVP da semana, quem mais jogou, quem mais ganhou, quem mais subiu ou caiu de PDL, quem mais morreu, pé frio, melhor partida e pentakills. Também dá para ver a qualquer hora com `/semana`.
- **`/ranking`**: agora mostra Solo/Duo **e** Flex.

---

## Como atualizar (para quem já tinha a versão 1)
1. **Desligue o bot**: aperte Ctrl + C no terminal.
2. Copie os arquivos novos (`*.py`, `requirements.txt`, `LEIA-ME.md`, `.gitignore`) para a pasta do bot e substitua os antigos.
   - **Não apague o seu `.env` nem o `dados.json`.** O `.env` tem o seu token e a sua chave, e o `dados.json` guarda quem fez `/vincular`.
   - O arquivo `.env.exemplo` mostra as opções novas. Elas são opcionais, porque o bot já vem com valores padrão. Se quiser mudar alguma, copie a linha para o seu `.env`.
3. Instale as bibliotecas novas:
   ```
   pip install -r requirements.txt
   ```
4. Ligue o bot de novo: `python bot.py`

## Como atualizar o bot na Discloud
1. Na pasta do bot, rode:
   ```
   python montar_zip.py
   ```
2. Na Discloud, abra o bot, vá em **Commit** e arraste o `bot-discloud.zip`.
3. Confira em **Logs** se apareceu "Bot online".

O zip **não leva o `dados.json` de propósito**. A Discloud só troca os arquivos que estão no zip, então as moedas, apostas, vínculos e o histórico que o bot juntou lá continuam intactos. **Nunca envie o `dados.json` do seu PC**: ele está desatualizado e apagaria esses dados.

Para guardar uma cópia dos dados, use o botão **Backup** na página do bot na Discloud.

## Instalação do zero
1. Crie o bot em https://discord.com/developers/applications: **New Application → Bot → Reset Token** e copie o token.
2. Em **OAuth2 → URL Generator**, marque `bot` e `applications.commands`. Nas permissões, marque **View Channels**, **Send Messages**, **Embed Links** e **Attach Files**. Abra a URL e adicione o bot ao seu servidor.
3. Pegue a chave da Riot em https://developer.riotgames.com.
4. Renomeie `.env.exemplo` para `.env` e preencha `DISCORD_TOKEN`, `RIOT_API_KEY` e `GUILD_ID`.
5. Instale o Python 3.10 ou mais novo (no Windows, marque "Add Python to PATH"). Depois rode `pip install -r requirements.txt` e `python bot.py`.

## Primeiros passos no Discord
1. Cada pessoa usa **`/vincular Nome#TAG`** e ganha 1.000 moedas.
2. Um admin usa **`/config-alertas #canal`** para ligar os avisos de partida, os resumos, as apostas e o resumo semanal.
3. Pronto! Quando alguém entrar em partida, o aviso aparece no canal.

## Comandos
| Comando | O que faz |
|---|---|
| `/perfil [Nome#TAG]` | Cartão de perfil em imagem |
| `/elo [Nome#TAG]` | Elo, PDL e winrate |
| `/historico [Nome#TAG] [quantidade]` | Últimas partidas |
| `/maestria [Nome#TAG] [quantidade]` | Campeões com mais maestria |
| `/aovivo [Nome#TAG]` | Raio-X da partida atual |
| `/build campeão [rota] [modo]` | Build mais usada do campeão por jogadores Mestre+ de KR, EUW e BR (Solo/Duo ou Flex) |
| `/ultimate-bravery [mapa]` | Sorteia campeão, 6 itens e 2 feitiços (Summoner's Rift ou ARAM) |
| `/vincular Nome#TAG` / `/desvincular` | Liga ou desliga a sua conta |
| `/ranking [fila]` | Ranking Solo/Duo e Flex do servidor |
| `/semana` | Resumo dos últimos 7 dias |
| `/carteira [membro]` / `/diario` / `/top-moedas` | Moedas das apostas |
| `/config-alertas #canal` / `/desativar-alertas` | Liga ou desliga os avisos (admin) |
| `/ajuda` | Lista os comandos |

## Como funcionam algumas coisas
- **Builds (`/build`):** o bot junta sozinho partidas de jogadores Mestre+ do KR, EUW e BR e soma runas, feitiços, itens e ordem das habilidades. Logo que liga pela primeira vez, leva algumas horas até ter partidas suficientes. Gasta cerca de 0,7 GB de internet por dia (dá para diminuir com `COLETA_PARTIDAS_HORA` no `.env`) e respeita o limite da chave da Riot. Na Discloud grátis, desligue com `COLETA_BUILDS=nao`.
- **Nota de 0 a 10:** compara cada jogador com os outros 9 em KDA, participação em abates, dano, ouro e visão. O vencedor ganha um pequeno bônus.
- **Apostas:** ficam abertas por 8 minutos depois do aviso. Quem está jogando só pode apostar no próprio time. Se for remake, o dinheiro volta. As moedas não valem nada de verdade.
- **Moedas extras:** quem joga ganha +50 moedas por vitória e +100 se for MVP ou ACE. O MVP da semana ganha +500.
- **Limite da Riot:** o bot controla sozinho as requisições para não passar do limite da chave. Se tiver muita gente vinculada, os avisos podem demorar um pouco mais.

## Problemas comuns
- **"A chave da Riot é inválida ou expirou"**: gere uma chave nova, coloque no `.env` e reinicie. Com a Personal Key, isso para de acontecer.
- **Os comandos novos não aparecem**: confira se o `GUILD_ID` está no `.env`, reinicie o bot e reabra o Discord (Ctrl + R).
- **Erro `No module named PIL`**: rode `pip install -r requirements.txt` de novo.
