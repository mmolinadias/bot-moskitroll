<div align="center">

# 🎮 bot-moskitroll

**Bot de Discord para acompanhar o League of Legends da sua turma no servidor BR.**

Elo, histórico, raio-X da partida ao vivo, resumo pós-jogo com nota de 0 a 10, apostas com moedas fictícias, uma loja para gastar essas moedas, ranking, resumo da semana e builds do alto elo, tudo direto no Discord.

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![discord.py](https://img.shields.io/badge/discord.py-2.4%2B-5865F2?logo=discord&logoColor=white)
![Riot API](https://img.shields.io/badge/Riot%20Games-API%20oficial-D32936?logo=riotgames&logoColor=white)
![Servidor](https://img.shields.io/badge/servidor-BR1-009C3B)

</div>

---

## ✨ O que ele faz

| | |
|---|---|
| 🖼️ **Perfil em imagem** | `/perfil` gera um cartão com ícone, elo de Solo/Duo e Flex, campeões favoritos e as últimas 10 partidas. |
| 🔴 **Alertas de partida** | Quando alguém do grupo entra em partida, o bot avisa no canal com o raio-X dos 10 jogadores (elo, winrate e maestria) e diz qual time é favorito. |
| 📊 **Resumo pós-jogo** | KDA, dano, participação, CS, visão, **nota de 0 a 10**, **MVP/ACE**, PDL ganho ou perdido, subida de elo, pentakill e avisos de sequência (on fire 🔥 ou tilt 😬). |
| 💰 **Apostas fictícias** | Aposte no time azul ou vermelho com moedas que não valem nada de verdade. As odds dependem do elo dos times. |
| 🛒 **Loja** | Gaste as moedas com título e fundo no perfil, coroa, cargo colorido, seguro de aposta, rifa... ou castigando, mutando e chutando os amigos da call. |
| 🏆 **Ranking e semana** | Ranking de Solo/Duo e Flex do servidor e, todo domingo, o resumo da semana: MVP, quem mais subiu, quem mais morreu, pé frio... |
| 🛠️ **Builds Mestre+** | `/build` mostra runas, feitiços, itens e ordem das habilidades mais usados por jogadores **Mestre+ do KR, EUW e BR**, com `/tierlist` e `/counter` dos mesmos dados. |
| ⚔️ **Duelos e duplas** | `/duelo` aposta moedas em quem tira a maior nota na próxima partida; `/duplas` mostra quem ganha mais jogando junto; `/comparar` coloca dois jogadores lado a lado. |
| 🚨 **Avisos automáticos** | Manutenção ou problema no servidor BR (status oficial da Riot) e patch novo no ar. |
| 🎲 **Ultimate Bravery** | Sorteia campeão, 6 itens e 2 feitiços, no Summoner's Rift ou no ARAM. |

## 💬 Comandos

| Comando | O que faz |
|---|---|
| `/perfil [Nome#TAG]` | Cartão de perfil em imagem |
| `/elo [Nome#TAG]` | Elo, PDL e winrate |
| `/historico [Nome#TAG] [quantidade]` | Últimas partidas |
| `/maestria [Nome#TAG] [quantidade]` | Campeões com mais maestria |
| `/aovivo [Nome#TAG]` | Raio-X da partida atual |
| `/build campeão [rota] [modo]` | Build mais usada no Mestre+ (Solo/Duo ou Flex) |
| `/tierlist rota [modo]` | Campeões mais fortes da rota no Mestre+ |
| `/counter campeão [rota] [modo]` | Contra quem o campeão mais ganha e perde no Mestre+ |
| `/comparar Nome#TAG [Nome#TAG]` | Dois jogadores lado a lado (elo e últimas 5 partidas) |
| `/ultimate-bravery [mapa]` | Sorteio de campeão, itens e feitiços |
| `/vincular Nome#TAG` · `/desvincular` | Liga ou desliga a sua conta |
| `/ranking [fila]` | Ranking Solo/Duo e Flex do servidor |
| `/semana` | Resumo dos últimos 7 dias |
| `/duplas` | Quais amigos ganham mais jogando juntos |
| `/duelo @amigo moedas` | Quem tirar a maior nota na próxima partida leva as moedas |
| `/carteira` · `/diario` · `/top-moedas` | Moedas das apostas |
| `/loja` · `/comprar item` | Itens à venda e compra |
| `/bloquear-apelido` | Não deixa ninguém comprar apelido forçado para você |
| `/config-loja` | Liga ou desliga os castigos (admin) |
| `/config-alertas #canal` · `/desativar-alertas` | Liga ou desliga os avisos (admin) |
| `/ajuda` | Lista os comandos |

> Sem o `Nome#TAG`, os comandos usam a conta que você vinculou com `/vincular`.

## 🛒 Loja

| Item | Preço | O que faz |
|---|---|---|
| 🏷️ Título no perfil | 1.500 | Frase embaixo do seu nome no `/perfil` |
| 🎨 Cor do cartão | 2.500 | Cor de destaque do seu `/perfil` |
| 🖼️ Fundo com campeão | 3.000 | Campeão no fundo do seu `/perfil` |
| 😎 Emoji no ranking | 1.000 | Emoji ao lado do seu nome no `/ranking` e no `/top-moedas` |
| 🌈 Cargo colorido | 5.000 | Cargo com a cor que você escolher |
| 👑 Coroa de Magnata | 20.000 | Coroa ao lado do seu nome em todo lugar |
| 🛟 Seguro de aposta | 300 | Na próxima aposta, se perder, volta metade |
| 🚀 Odd turbinada | 500 | Na próxima aposta, se ganhar, o prêmio é 1,5x |
| 🎟️ Bilhete da rifa | 100 | Concorre ao pote, sorteado no domingo com o resumo da semana |
| 🎲 Desafio Bravery | 800 | Sorteia um Ultimate Bravery para um amigo; se ele ganhar com o campeão em até 2 dias, leva 1.600 |
| 📢 Anúncio | 500 | O bot posta sua mensagem em destaque no canal dos alertas |
| 🤡 Apelido forçado | 2.000 | Muda o apelido de um amigo por 24h |
| ⛓️ Castigo | 300 / 1.200 / 2.000 | Castigo do Discord por 1, 5 ou 10 minutos |
| 🔇 Mutar microfone | 200 / 800 / 1.500 | Muta o amigo na call por 1, 5 ou 10 minutos |
| 🙉 Ensurdecer | 200 / 800 / 1.500 | O amigo para de ouvir a call por 1, 5 ou 10 minutos |
| 🦶 Chutar da call | 400 | Desconecta o amigo da call |
| 🛡️ Escudo | 1.500 | Bloqueia o próximo castigo, mute, ensurdecer, chute ou apelido contra você |

- Quem leva um castigo fica **protegido por 10 minutos** depois que ele acaba. Não vale castigar você mesmo nem bots.
- Quem não quer apelido forçado usa `/bloquear-apelido`. Um admin pode desligar todos os castigos com `/config-loja castigos:False`.
- O Discord não deixa o bot castigar o dono do servidor, admins ou quem tem cargo acima do bot. Se a ação falhar, a compra não é cobrada.

## ⚙️ Como funciona por dentro

```mermaid
flowchart LR
    A[Alguém vinculado<br>entra em partida] --> B[Bot posta o raio-X<br>e abre as apostas]
    B --> C[Partida acaba]
    C --> D[Bot busca o resultado<br>e o PDL novo]
    D --> E[Resumo com nota, MVP e PDL<br>+ pagamento das apostas]
    E --> F[Histórico para o<br>resumo da semana]
```

- **Nota de 0 a 10:** compara cada jogador com os outros 9 da partida em KDA, participação em abates, dano, ouro e visão.
- **Moedas:** cada pessoa começa com 1.000. Quem joga ganha +50 por vitória e +100 se for MVP ou ACE. O MVP da semana ganha +500. Remake devolve as apostas.
- **Builds:** o bot junta sozinho partidas ranqueadas de jogadores Mestre, Grão-Mestre e Desafiante do KR, EUW e BR e guarda só os totais (runas, feitiços, itens e habilidades), dos 2 patches mais recentes.
- **Limite da Riot:** todas as chamadas passam por um controle que respeita o limite da chave (20 por segundo e 100 a cada 2 minutos, em cada região). No BR, a coleta de builds usa no máximo metade do limite, para os alertas nunca ficarem esperando.

## 🚀 Instalação

**Você vai precisar de:** Python 3.10 ou mais novo, um bot criado no [Discord Developer Portal](https://discord.com/developers/applications) e uma chave da [Riot](https://developer.riotgames.com).

1. Baixe o código:
   ```bash
   git clone https://github.com/mmolinadias/bot-moskitroll.git
   cd bot-moskitroll
   ```
2. Instale as bibliotecas:
   ```bash
   pip install -r requirements.txt
   ```
3. Copie o `.env.exemplo` para `.env` e preencha `DISCORD_TOKEN`, `RIOT_API_KEY` e `GUILD_ID`.
4. Ligue o bot:
   ```bash
   python bot.py
   ```
5. No Discord, cada pessoa usa `/vincular Nome#TAG` e um admin usa `/config-alertas #canal`.

No Discord Developer Portal, em **OAuth2 → URL Generator**, marque `bot` e `applications.commands`, com as permissões **View Channels**, **Send Messages**, **Embed Links** e **Attach Files**.

Para a loja funcionar, o cargo do bot precisa destas permissões, e precisa estar **acima** dos cargos das pessoas que vão ser castigadas:
**Gerenciar Cargos** (cargo colorido), **Gerenciar Apelidos** (apelido forçado), **Castigar Membros** (castigo), **Silenciar Membros** (mutar), **Ensurdecer Membros** (ensurdecer) e **Mover Membros** (chutar da call).


O passo a passo completo, com dicas para quem está começando, está no [LEIA-ME.md](LEIA-ME.md).

## 🔧 Configuração (`.env`)

| Opção | Padrão | Para que serve |
|---|---|---|
| `DISCORD_TOKEN` | — | Token do bot |
| `RIOT_API_KEY` | — | Chave da Riot |
| `GUILD_ID` | vazio | ID do servidor, para os comandos aparecerem na hora |
| `RIOT_PLATFORM` / `RIOT_REGION` | `br1` / `americas` | Servidor do LoL dos jogadores vinculados |
| `INTERVALO_ALERTA_MIN` | `2` | De quantos em quantos minutos checa as partidas |
| `RESUMO_SEMANAL_DIA` / `RESUMO_SEMANAL_HORA` | `6` / `20` | Quando sai o resumo da semana (6 = domingo) |
| `MOEDAS_INICIAIS` / `MOEDAS_DIARIO` | `1000` / `250` | Moedas de quem se vincula e do `/diario` |
| `TEMPO_APOSTAS_MIN` | `8` | Por quantos minutos as apostas ficam abertas |
| `COLETA_BUILDS` | `sim` | Liga a coleta de builds do `/build` |
| `COLETA_REGIOES` | `kr,euw,br` | Regiões da coleta |
| `COLETA_PARTIDAS_HORA` | `120` | Partidas por hora em cada região (~85 KB cada) |

> ⚠️ O `.env` tem o token do Discord e a chave da Riot. Ele já está no `.gitignore`: **nunca** compartilhe esse arquivo.

## 🖥️ Hospedagem

- **Servidor próprio ou VPS (recomendado):** com a coleta de builds ligada, o bot usa uns 150 a 250 MB de RAM e cerca de 0,7 GB de internet por dia.
- **Discloud (plano grátis, 100 MB):** funciona com `COLETA_BUILDS=nao`. Para atualizar, rode `python montar_zip.py` e envie o `bot-discloud.zip` na página **Commit**. O zip nunca leva o `dados.json`, para não apagar as moedas e o histórico de lá.

## 📁 Estrutura

```
bot.py          comandos, botões das apostas e loops dos alertas
riot.py         API da Riot (com controle de limite) e Data Dragon
coleta.py       coleta das builds Mestre+ para o /build
analise.py      elo, nota de 0 a 10, MVP/ACE e odds
loja.py         catálogo e regras da loja
imagens.py      cartão do /perfil (Pillow)
dados.py        dados.json: vínculos, moedas, apostas e histórico
config.py       leitura do .env
montar_zip.py   gera o zip para a Discloud
```

---

<sub>bot-moskitroll isn't endorsed by Riot Games and doesn't reflect the views or opinions of Riot Games or anyone officially involved in producing or managing Riot Games properties. Riot Games, and all associated properties are trademarks or registered trademarks of Riot Games, Inc. As moedas das apostas são fictícias e não têm valor real.</sub>
