"""
Bot de Discord conectado ao League of Legends.
Rode com:  python bot.py
"""
import asyncio
import logging
import random
import time
from collections import Counter, defaultdict
from itertools import combinations
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import tasks
from discord.utils import escape_markdown

import config
from analise import (FILA_PARA_TIPO, FILAS_RANK, TIMES_PT, calcular_notas, calcular_odds,
                     compacto, kda, melhor_fila, nome_fila, numero, pontuacao_elo, texto_elo,
                     texto_pontuacao, texto_variacao, tier_curto, winrate)
from dados import Dados
from imagens import gerar_cartao_perfil
from loja import (APELIDO_HORAS, CASTIGOS, CATEGORIAS, CONTAVEIS, DESAFIO_HORAS, ITENS, PREMIO_DESAFIO,
                  DadosLoja, ErroLoja, emoji_valido, limpar_texto, nome_lol, preco, texto_preco)
from loja import CORES as CORES_LOJA
from coleta import NOMES_FILAS, ROTAS, Coleta, _ordem_patch
from riot import NaoEncontrado, RiotAPI, RiotErro

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("bot-lol")

riot = RiotAPI()
store = Dados(config.PASTA / "dados.json")
loja = DadosLoja(store)
coleta = Coleta(riot, config.PASTA / "builds.json")

CORES = {"ok": 0x2ECC71, "info": 0x3498DB, "aviso": 0xE67E22, "erro": 0xE74C3C, "ouro": 0xF1C40F}
SEM_MENCAO = discord.AllowedMentions.none()

try:
    from zoneinfo import ZoneInfo
    FUSO = ZoneInfo(config.FUSO)
except Exception:
    FUSO = timezone(timedelta(hours=-3))


# ================================================================ bot
class BotLoL(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default(), max_messages=None)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await riot.iniciar()
        await atualizar_puuids()
        self.add_dynamic_items(BotaoAposta, BotaoDuelo)
        if config.GUILD_ID:
            guild = discord.Object(id=int(config.GUILD_ID))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            log.info("Comandos sincronizados no servidor %s", config.GUILD_ID)
        else:
            await self.tree.sync()
            log.info("Comandos sincronizados globalmente (podem levar até 1h para aparecer)")
        loop_partidas.start()
        loop_resultados.start()
        loop_semanal.start()
        loop_loja.start()
        loop_status.start()
        if config.COLETA_BUILDS:
            coleta.ao_patch_novo = anunciar_patch
            coleta.iniciar()

    async def close(self):
        store.salvar()
        coleta.parar()
        await riot.fechar()
        await super().close()


def _trocar_ids(obj, mapa: dict[str, str]):
    """Troca PUUIDs antigos pelos novos em qualquer lugar dos dados salvos."""
    if isinstance(obj, dict):
        return {mapa.get(k, k): _trocar_ids(v, mapa) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_trocar_ids(v, mapa) for v in obj]
    if isinstance(obj, str):
        return mapa.get(obj, obj)
    return obj


async def atualizar_puuids():
    """A Riot criptografa o PUUID de um jeito diferente para cada chave. Se a chave mudou
    (ex.: de desenvolvimento para Personal Key), busca de novo cada conta pelo Riot ID."""
    mapa: dict[str, str] = {}
    for g, vinculos in store.d["vinculos"].items():
        for u, v in vinculos.items():
            antigo = v["puuid"]
            if antigo in mapa:
                continue
            try:
                conta = await riot.conta_por_puuid(antigo)
            except RiotErro:
                conta = None
            if conta is None:  # PUUID de outra chave: procura pelo nome
                try:
                    conta = await riot.conta(v["riot_id"])
                except RiotErro as e:
                    log.warning("Não consegui atualizar %s: %s", v["riot_id"], e)
                    continue
            if conta["puuid"] != antigo:
                mapa[antigo] = conta["puuid"]
            novo_nome = f"{conta.get('gameName')}#{conta.get('tagLine')}"
            if conta.get("gameName") and novo_nome != v["riot_id"]:
                log.info("Riot ID atualizado: %s -> %s", v["riot_id"], novo_nome)
                v["riot_id"] = novo_nome
    if mapa:
        store.d = _trocar_ids(store.d, mapa)
        log.info("PUUIDs atualizados para a chave atual: %d conta(s)", len(mapa))
    store.salvar()


bot = BotLoL()


@bot.event
async def on_ready():
    log.info("Bot online como %s (servidores: %d)", bot.user, len(bot.guilds))
    await bot.change_presence(activity=discord.Game("League of Legends | /ajuda"))


@bot.tree.error
async def ao_dar_erro(interaction: discord.Interaction, error: app_commands.AppCommandError):
    original = getattr(error, "original", error)
    if isinstance(original, RiotErro):
        msg = str(original)
    elif isinstance(error, app_commands.MissingPermissions):
        msg = "Você precisa da permissão **Gerenciar Servidor** para isso."
    else:
        log.exception("Erro no comando", exc_info=original)
        msg = "Algo deu errado. Tente de novo em instantes."
    await responder(interaction, embed=discord.Embed(description=f"❌ {msg}", color=CORES["erro"]),
                    ephemeral=True)


async def responder(interaction: discord.Interaction, **kwargs):
    if interaction.response.is_done():
        await interaction.followup.send(**kwargs)
    else:
        await interaction.response.send_message(**kwargs)


async def resolver_jogador(jogador: str | None, interaction: discord.Interaction) -> dict:
    """Aceita um Riot ID; se vazio, usa a conta vinculada de quem chamou o comando."""
    if jogador:
        return await riot.conta(jogador)
    if interaction.guild:
        v = store.de("vinculos", interaction.guild.id).get(str(interaction.user.id))
        if v:
            nome, tag = v["riot_id"].rsplit("#", 1)
            return {"puuid": v["puuid"], "gameName": nome, "tagLine": tag}
    raise RiotErro("Informe um jogador (ex.: `Faker#KR1`) ou use `/vincular` antes.")


def nome(g, u) -> str:
    """Nome do membro no LoL em negrito (ou a menção, se não tiver conta vinculada)."""
    return nome_lol(store, g, u)


def plural(n: int, palavra: str) -> str:
    return f"{n} {palavra}{'' if n == 1 else 's'}"


def nome_conta(conta: dict) -> str:
    return f"{conta['gameName']}#{conta['tagLine']}"


# ================================================================ /elo /historico /maestria
@bot.tree.command(name="elo", description="Mostra elo, PDL e winrate de um jogador")
@app_commands.describe(jogador="Riot ID com TAG, ex.: Faker#KR1 (vazio = sua conta vinculada)")
async def cmd_elo(interaction: discord.Interaction, jogador: str | None = None):
    await interaction.response.defer()
    conta = await resolver_jogador(jogador, interaction)
    perfil, filas = await asyncio.gather(riot.invocador(conta["puuid"]), riot.elo(conta["puuid"]))
    embed = discord.Embed(title=nome_conta(conta), description=f"Nível {perfil['summonerLevel']}",
                          color=CORES["info"])
    embed.set_thumbnail(url=riot.url_icone_perfil(perfil["profileIconId"]))
    filas_rank = [f for f in filas if f["queueType"] in FILAS_RANK]
    if not filas_rank:
        embed.add_field(name="Ranqueadas", value="Sem ranqueadas nesta temporada.", inline=False)
    for f in sorted(filas_rank, key=lambda f: f["queueType"] != "RANKED_SOLO_5x5"):
        extra = "\n🔥 Em sequência de vitórias" if f.get("hotStreak") else ""
        embed.add_field(name=FILAS_RANK[f["queueType"]],
                        value=f"**{texto_elo(f)}**\n{f['wins']}V {f['losses']}D ({winrate(f)}% winrate){extra}")
    await interaction.followup.send(embed=embed)


@bot.tree.command(name="historico", description="Mostra as últimas partidas de um jogador")
@app_commands.describe(jogador="Riot ID com TAG (vazio = sua conta vinculada)",
                       quantidade="Quantas partidas (1 a 10)")
async def cmd_historico(interaction: discord.Interaction, jogador: str | None = None,
                        quantidade: app_commands.Range[int, 1, 10] = 5):
    await interaction.response.defer()
    conta = await resolver_jogador(jogador, interaction)
    ids = await riot.ids_partidas(conta["puuid"], quantidade)
    if not ids:
        await interaction.followup.send("Nenhuma partida encontrada para esse jogador.")
        return
    partidas = await asyncio.gather(*(riot.partida(i) for i in ids), return_exceptions=True)
    linhas, vitorias, derrotas = [], 0, 0
    for p in partidas:
        if isinstance(p, Exception):
            continue
        info = p["info"]
        eu = next((x for x in info["participants"] if x["puuid"] == conta["puuid"]), None)
        if not eu:
            continue
        k, d, a = eu["kills"], eu["deaths"], eu["assists"]
        cs = eu.get("totalMinionsKilled", 0) + eu.get("neutralMinionsKilled", 0)
        quando = info.get("gameEndTimestamp", info.get("gameCreation", 0)) // 1000
        if eu.get("gameEndedInEarlySurrender"):
            icone = "⚪"
        elif eu["win"]:
            icone, vitorias = "✅", vitorias + 1
        else:
            icone, derrotas = "❌", derrotas + 1
        linhas.append(f"{icone} **{riot.nome_por_id_interno(eu['championName'])}** {k}/{d}/{a} "
                      f"(KDA {kda(k, d, a):.1f}) · {cs} CS · {nome_fila(info['queueId'])} · "
                      f"{info['gameDuration'] // 60}min · <t:{quando}:R>")
    embed = discord.Embed(title=f"Histórico de {nome_conta(conta)}",
                          description="\n".join(linhas) or "Não consegui ler as partidas.",
                          color=CORES["ok"] if vitorias >= derrotas else CORES["aviso"])
    embed.set_footer(text=f"{vitorias}V {derrotas}D nas últimas {len(linhas)} partidas")
    await interaction.followup.send(embed=embed)


@bot.tree.command(name="maestria", description="Campeões com mais maestria de um jogador")
@app_commands.describe(jogador="Riot ID com TAG (vazio = sua conta vinculada)",
                       quantidade="Quantos campeões (1 a 10)")
async def cmd_maestria(interaction: discord.Interaction, jogador: str | None = None,
                       quantidade: app_commands.Range[int, 1, 10] = 5):
    await interaction.response.defer()
    conta = await resolver_jogador(jogador, interaction)
    lista = await riot.maestrias(conta["puuid"], quantidade)
    if not lista:
        await interaction.followup.send("Esse jogador ainda não tem maestria em nenhum campeão.")
        return
    medalhas = ["🥇", "🥈", "🥉"]
    linhas = [f"{medalhas[i] if i < 3 else f'`{i + 1}.`'} **{riot.nome_campeao(m['championId'])}** — "
              f"Nível {m['championLevel']} · {numero(m['championPoints'])} pts" for i, m in enumerate(lista)]
    embed = discord.Embed(title=f"Maestrias de {nome_conta(conta)}", description="\n".join(linhas),
                          color=CORES["info"])
    if riot.url_campeao(lista[0]["championId"]):
        embed.set_thumbnail(url=riot.url_campeao(lista[0]["championId"]))
    await interaction.followup.send(embed=embed)


# ================================================================ /perfil (cartão em imagem)
@bot.tree.command(name="perfil", description="Cartão de perfil em imagem com elo, campeões e últimas partidas")
@app_commands.describe(jogador="Riot ID com TAG (vazio = sua conta vinculada)")
async def cmd_perfil(interaction: discord.Interaction, jogador: str | None = None):
    await interaction.response.defer()
    conta = await resolver_jogador(jogador, interaction)
    puuid = conta["puuid"]
    perfil, filas, maes, ids = await asyncio.gather(
        riot.invocador(puuid), riot.elo(puuid), riot.maestrias(puuid, 3), riot.ids_partidas(puuid, 10))
    partidas = await asyncio.gather(*(riot.partida(i) for i in ids), return_exceptions=True)

    recentes, rotas = [], Counter()
    for p in partidas:
        if isinstance(p, Exception):
            continue
        eu = next((x for x in p["info"]["participants"] if x["puuid"] == puuid), None)
        if not eu:
            continue
        res = "R" if eu.get("gameEndedInEarlySurrender") else ("V" if eu["win"] else "D")
        recentes.append({"res": res, "k": eu["kills"], "d": eu["deaths"], "a": eu["assists"]})
        if eu.get("teamPosition"):
            rotas[eu["teamPosition"]] += 1

    dados_cartao = {
        "nome": conta["gameName"], "tag": conta["tagLine"], "nivel": perfil["summonerLevel"],
        "icone": perfil["profileIconId"], "servidor": config.PLATFORM,
        "solo": next((f for f in filas if f["queueType"] == "RANKED_SOLO_5x5"), None),
        "flex": next((f for f in filas if f["queueType"] == "RANKED_FLEX_SR"), None),
        "maestrias": [{"key": m["championId"], "nome": riot.nome_campeao(m["championId"]),
                       "nivel": m["championLevel"], "pontos": m["championPoints"]} for m in maes],
        "recentes": recentes, "rota": rotas.most_common(1)[0][0] if rotas else None,
    }
    if interaction.guild:  # itens da loja de quem é dono dessa conta
        vinculos = store.de("vinculos", interaction.guild.id)
        dono = next((u for u, v in vinculos.items() if v["puuid"] == puuid), None)
        if dono:
            itens = loja.servidor(interaction.guild.id)["usuarios"].get(dono, {})
            dados_cartao.update({k: itens[k] for k in ("titulo", "cor", "fundo", "coroa") if itens.get(k)})
    arquivo = await gerar_cartao_perfil(riot, dados_cartao)
    await interaction.followup.send(file=discord.File(arquivo, filename="perfil.png"))


# ================================================================ raio-X da partida ao vivo
async def montar_raio_x(jogo: dict, destaque: set[str], titulo: str = "🎮 Partida ao vivo"):
    """Embed com elo, winrate e maestria dos 10 jogadores + força de cada time."""
    participantes = jogo.get("participants", [])

    async def detalhar(p):
        r = {"p": p, "nome": p.get("riotId") or "", "elo": None, "solo": None, "mae": None}
        puuid = p.get("puuid")
        if not puuid or p.get("bot"):
            r["nome"] = r["nome"] or "Oculto"
            return r
        tarefas = [riot.elo(puuid), riot.maestria_campeao(puuid, p.get("championId", 0))]
        if not r["nome"]:
            tarefas.append(riot.conta_por_puuid(puuid))
        res = await asyncio.gather(*tarefas, return_exceptions=True)
        if not isinstance(res[0], Exception):
            r["elo"] = melhor_fila(res[0])
            r["solo"] = next((e for e in res[0] if e["queueType"] == "RANKED_SOLO_5x5"), None)
        if not isinstance(res[1], Exception):
            r["mae"] = res[1]
        if len(res) > 2 and not isinstance(res[2], Exception):
            r["nome"] = f"{res[2]['gameName']}#{res[2]['tagLine']}"
        return r

    detalhes = await asyncio.gather(*(detalhar(p) for p in participantes))
    times: dict[int, list] = defaultdict(list)
    for r in detalhes:
        times[r["p"].get("teamId", 0)].append(r)

    forcas = {}
    for t, lista in times.items():
        valores = [pontuacao_elo(r["solo"]) for r in lista if r["solo"]]
        forcas[t] = sum(valores) / len(valores) if valores else None

    fila = jogo.get("gameQueueConfigId", 0)
    inicio = jogo.get("gameStartTime") or 0
    desc = [f"**{nome_fila(fila)}**" + (f" · começou <t:{inicio // 1000}:R>" if inicio else "")]
    azul, vermelho = forcas.get(100), forcas.get(200)
    if azul is not None and vermelho is not None:
        medias = f"média {texto_pontuacao(azul)} × {texto_pontuacao(vermelho)}"
        if abs(azul - vermelho) < 50:
            desc.append(f"⚖️ Partida equilibrada ({medias})")
        else:
            fav = "🔵 Time Azul" if azul > vermelho else "🔴 Time Vermelho"
            desc.append(f"📊 Favorito no papel: **{fav}** ({medias})")
    embed = discord.Embed(title=titulo, description="\n".join(desc), color=CORES["ok"])

    nomes_time = {100: "🔵 Time Azul", 200: "🔴 Time Vermelho"}
    for t in sorted(times):
        linhas = []
        for r in times[t]:
            p = r["p"]
            estrela = "⭐ " if p.get("puuid") in destaque else ""
            e = r["elo"]
            elo_txt = f"{tier_curto(e)} {e['leaguePoints']} PDL · {winrate(e)}% WR" if e else "Sem rank"
            m = r["mae"]
            mae_txt = f"M{m['championLevel']} ({compacto(m['championPoints'])})" if m else "sem maestria"
            linhas.append(f"{estrela}**{riot.nome_campeao(p.get('championId', 0))}** — "
                          f"{escape_markdown(r['nome'])}\n　{elo_txt} · {mae_txt}")
        embed.add_field(name=nomes_time.get(t, f"Time {t}"), value="\n".join(linhas)[:1024] or "—", inline=False)
    return embed, forcas


@bot.tree.command(name="aovivo", description="Raio-X da partida atual: elo e maestria dos 10 jogadores")
@app_commands.describe(jogador="Riot ID com TAG (vazio = sua conta vinculada)")
async def cmd_aovivo(interaction: discord.Interaction, jogador: str | None = None):
    await interaction.response.defer()
    conta = await resolver_jogador(jogador, interaction)
    jogo = await riot.partida_ao_vivo(conta["puuid"])
    if not jogo:
        await interaction.followup.send(embed=discord.Embed(
            description=f"💤 **{escape_markdown(nome_conta(conta))}** não está em partida agora.",
            color=CORES["aviso"]))
        return
    embed, _ = await montar_raio_x(jogo, {conta["puuid"]}, f"🎮 {nome_conta(conta)} está em partida!")
    eu = next((p for p in jogo["participants"] if p.get("puuid") == conta["puuid"]), None)
    if eu and riot.url_campeao(eu.get("championId")):
        embed.set_thumbnail(url=riot.url_campeao(eu["championId"]))
    await interaction.followup.send(embed=embed)


# ================================================================ /vincular /desvincular /ranking
@bot.tree.command(name="vincular", description="Liga sua conta do Discord ao seu Riot ID")
@app_commands.guild_only()
@app_commands.describe(jogador="Seu Riot ID com TAG, ex.: Faker#KR1")
async def cmd_vincular(interaction: discord.Interaction, jogador: str):
    await interaction.response.defer(ephemeral=True)
    conta = await riot.conta(jogador)
    await riot.invocador(conta["puuid"])
    store.de("vinculos", interaction.guild.id)[str(interaction.user.id)] = {
        "puuid": conta["puuid"], "riot_id": nome_conta(conta)}
    store.carteira(interaction.guild.id, interaction.user.id)
    store.salvar()
    await interaction.followup.send(embed=discord.Embed(
        description=f"✅ Conta vinculada a **{escape_markdown(nome_conta(conta))}**.\n"
                    f"Você entrou no `/ranking`, recebe avisos de partida e ganhou "
                    f"**{numero(config.SALDO_INICIAL)} moedas** para apostar.", color=CORES["ok"]))


@bot.tree.command(name="desvincular", description="Remove o vínculo da sua conta")
@app_commands.guild_only()
async def cmd_desvincular(interaction: discord.Interaction):
    removido = store.de("vinculos", interaction.guild.id).pop(str(interaction.user.id), None)
    store.salvar()
    await interaction.response.send_message("✅ Vínculo removido." if removido else
                                            "Você não tinha conta vinculada.", ephemeral=True)


@bot.tree.command(name="ranking", description="Ranking de elo (Solo/Duo e Flex) dos membros vinculados")
@app_commands.guild_only()
@app_commands.describe(fila="Qual fila mostrar (padrão: as duas)")
@app_commands.choices(fila=[app_commands.Choice(name="Solo/Duo e Flex", value="ambas"),
                            app_commands.Choice(name="Solo/Duo", value="RANKED_SOLO_5x5"),
                            app_commands.Choice(name="Flex", value="RANKED_FLEX_SR")])
async def cmd_ranking(interaction: discord.Interaction, fila: app_commands.Choice[str] | None = None):
    await interaction.response.defer()
    vinculos = store.de("vinculos", interaction.guild.id)
    if not vinculos:
        await interaction.followup.send("Ninguém vinculou a conta ainda. Use `/vincular Nome#TAG`.")
        return

    async def buscar(uid, v):
        try:
            return uid, v["riot_id"], await riot.elo(v["puuid"])
        except RiotErro:
            return None

    resultados = [r for r in await asyncio.gather(*(buscar(u, v) for u, v in vinculos.items())) if r]
    escolha = fila.value if fila else "ambas"
    tipos = ["RANKED_SOLO_5x5", "RANKED_FLEX_SR"] if escolha == "ambas" else [escolha]
    titulos = {"RANKED_SOLO_5x5": "🏆 Ranking Solo/Duo", "RANKED_FLEX_SR": "👥 Ranking Flex"}
    medalhas = ["🥇", "🥈", "🥉"]
    embeds = []
    for tipo in tipos:
        lista = []
        sem = []
        for uid, rid, filas in resultados:
            e = next((f for f in filas if f["queueType"] == tipo), None)
            (lista if e else sem).append((uid, rid, e))
        lista.sort(key=lambda r: pontuacao_elo(r[2]), reverse=True)
        linhas = []
        for i, (uid, rid, e) in enumerate(lista[:20]):
            pos = medalhas[i] if i < 3 else f"`{i + 1}.`"
            linhas.append(f"{pos} {loja.enfeite(interaction.guild.id, uid)}**{escape_markdown(rid)}**\n　**{texto_elo(e)}** · "
                          f"{winrate(e)}% WR ({plural(e['wins'] + e['losses'], 'jogo')})")
        if not linhas:
            linhas.append("Ninguém tem classificação nessa fila ainda.")
        if sem:
            linhas.append("\n**Sem classificação:** " + ", ".join(nome(interaction.guild.id, u) for u, _, _ in sem))
        embeds.append(discord.Embed(title=f"{titulos[tipo]} — {interaction.guild.name}",
                                    description="\n".join(linhas)[:4000],
                                    color=CORES["info"] if tipo == "RANKED_SOLO_5x5" else 0x9B59B6))
    await interaction.followup.send(embeds=embeds, allowed_mentions=SEM_MENCAO)


# ================================================================ apostas
def checar_aposta(partida: dict | None, user_id: int, time_id: int) -> str | None:
    if not partida:
        return "Essa partida já terminou."
    if time.time() > partida.get("apostas_ate", 0):
        return "As apostas dessa partida já fecharam. ⏰"
    if str(user_id) in partida["apostas"]:
        return "Você já apostou nessa partida."
    jogador = partida["jogadores"].get(str(user_id))
    if jogador and jogador["time"] != time_id:
        return "Você não pode apostar contra o seu próprio time. 😅"
    return None


class ModalAposta(discord.ui.Modal):
    valor = discord.ui.TextInput(label="Quantas moedas?", placeholder="ex.: 100", max_length=9)

    def __init__(self, g: str, jogo: str, time_id: int, saldo: int):
        super().__init__(title=f"Apostar no {TIMES_PT[time_id]}")
        self.g, self.jogo, self.time_id = g, jogo, time_id
        self.valor.placeholder = f"Você tem {numero(saldo)} moedas"

    async def on_submit(self, interaction: discord.Interaction):
        partida = store.de("partidas", self.g).get(self.jogo)
        erro = checar_aposta(partida, interaction.user.id, self.time_id)
        texto = self.valor.value.strip().replace(".", "").lower()
        carteira = store.carteira(self.g, interaction.user.id)
        valor = carteira["saldo"] if texto in ("tudo", "allin", "all in", "all") else None
        if valor is None:
            valor = int(texto) if texto.isdigit() else 0
        if not erro and valor <= 0:
            erro = "Digite um número de moedas válido (ou `tudo`)."
        if not erro and valor > carteira["saldo"]:
            erro = f"Você só tem **{numero(carteira['saldo'])}** moedas. Use `/diario` para ganhar mais."
        if erro:
            await interaction.response.send_message(f"❌ {erro}", ephemeral=True)
            return
        odd = partida["odds"][str(self.time_id)]
        carteira["saldo"] -= valor
        aposta = {"time": self.time_id, "valor": valor, "odd": odd}
        usados = loja.aplicar_na_aposta(self.g, interaction.user.id, aposta)
        partida["apostas"][str(interaction.user.id)] = aposta
        store.salvar()
        emoji = "🔵" if self.time_id == 100 else "🔴"
        premio = int(valor * odd * (1.5 if aposta.get("turbo") else 1))
        extra = f" · usando {' e '.join(usados)}" if usados else ""
        await interaction.response.send_message(
            f"💰 {nome(self.g, interaction.user.id)} apostou **{numero(valor)}** moedas no {emoji} **{TIMES_PT[self.time_id]}** "
            f"(paga {odd:.2f}x → {numero(premio)}){extra}", allowed_mentions=SEM_MENCAO)


class BotaoAposta(discord.ui.DynamicItem[discord.ui.Button],
                  template=r"aposta:(?P<g>\d+):(?P<jogo>\d+):(?P<time>\d+)"):
    def __init__(self, g, jogo, time_id: int, rotulo: str | None = None):
        estilo = discord.ButtonStyle.primary if time_id == 100 else discord.ButtonStyle.danger
        super().__init__(discord.ui.Button(label=rotulo or "Apostar", emoji="💰", style=estilo,
                                           custom_id=f"aposta:{g}:{jogo}:{time_id}"))
        self.g, self.jogo, self.time_id = str(g), str(jogo), int(time_id)

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match["g"], match["jogo"], int(match["time"]))

    async def callback(self, interaction: discord.Interaction):
        partida = store.de("partidas", self.g).get(self.jogo)
        erro = checar_aposta(partida, interaction.user.id, self.time_id)
        if erro:
            await interaction.response.send_message(f"❌ {erro}", ephemeral=True)
            return
        saldo = store.carteira(self.g, interaction.user.id)["saldo"]
        await interaction.response.send_modal(ModalAposta(self.g, self.jogo, self.time_id, saldo))


async def autocompletar_vinculado(interaction: discord.Interaction, atual: str):
    """Lista todo mundo do servidor que usou /vincular (menos quem está comprando)."""
    atual = atual.strip().lower()
    opcoes = []
    for u, v in store.de("vinculos", interaction.guild.id).items():
        if u == str(interaction.user.id):
            continue
        membro = interaction.guild.get_member(int(u))
        rotulo = v.get("riot_id", u) + (f" ({membro.display_name})" if membro else "")
        if not atual or atual in rotulo.lower():
            opcoes.append(app_commands.Choice(name=rotulo[:100], value=u))
    return sorted(opcoes, key=lambda c: c.name.lower())[:25]


async def resolver_alvo(guild: discord.Guild, texto: str) -> discord.Member:
    """Transforma o valor do campo alvo (id, menção ou Nome#TAG vinculado) no membro do servidor."""
    texto = texto.strip().lstrip("<@!").rstrip(">")
    if not texto.isdigit():
        procura = texto.lower()
        texto = next((u for u, v in store.de("vinculos", guild.id).items()
                      if v.get("riot_id", "").lower() == procura
                      or v.get("riot_id", "").lower().split("#")[0] == procura), "")
    if not texto:
        raise ErroLoja("Não achei esse amigo. Escolha um nome da lista do campo `alvo`.")
    membro = guild.get_member(int(texto))
    if membro is None:
        try:
            membro = await guild.fetch_member(int(texto))
        except discord.HTTPException:
            raise ErroLoja("Esse amigo não está mais no servidor.")
    return membro


@bot.tree.command(name="carteira", description="Mostra suas moedas (ou de outro membro)")
@app_commands.guild_only()
@app_commands.describe(membro="Amigo vinculado (vazio = você)")
@app_commands.autocomplete(membro=autocompletar_vinculado)
async def cmd_carteira(interaction: discord.Interaction, membro: str | None = None):
    alvo = await resolver_alvo(interaction.guild, membro) if membro else interaction.user
    c = store.carteira(interaction.guild.id, alvo.id)
    abertas = sum(1 for p in store.de("partidas", interaction.guild.id).values() if str(alvo.id) in p["apostas"])
    store.salvar()
    texto = f"💰 **{numero(c['saldo'])}** moedas"
    if abertas:
        texto += f"\n🎲 {abertas} aposta(s) em andamento"
    inventario = loja.inventario(interaction.guild.id, alvo.id)
    if inventario:
        texto += "\n\n**🎒 Itens da loja**\n" + "\n".join(inventario)
    await interaction.response.send_message(embed=discord.Embed(
        title=f"Carteira de {loja.enfeite(interaction.guild.id, alvo.id)}{alvo.display_name}",
        description=texto, color=CORES["ouro"]))


@bot.tree.command(name="diario", description="Pega suas moedas grátis do dia")
@app_commands.guild_only()
async def cmd_diario(interaction: discord.Interaction):
    c = store.carteira(interaction.guild.id, interaction.user.id)
    espera = c["diario"] + 20 * 3600 - time.time()
    if espera > 0:
        await interaction.response.send_message(
            f"⏳ Você já pegou hoje. Volte <t:{int(time.time() + espera)}:R>.", ephemeral=True)
        return
    c["saldo"] += config.BONUS_DIARIO
    c["diario"] = time.time()
    store.salvar()
    await interaction.response.send_message(
        f"🎁 +**{config.BONUS_DIARIO}** moedas! Agora você tem **{numero(c['saldo'])}**.")


@bot.tree.command(name="top-moedas", description="Quem tem mais moedas no servidor")
@app_commands.guild_only()
async def cmd_top_moedas(interaction: discord.Interaction):
    carteiras = store.de("moedas", interaction.guild.id)
    if not carteiras:
        await interaction.response.send_message("Ninguém tem moedas ainda. Use `/vincular` ou `/diario`.")
        return
    top = sorted(carteiras.items(), key=lambda kv: -kv[1]["saldo"])[:10]
    medalhas = ["🥇", "🥈", "🥉"]
    linhas = [f"{medalhas[i] if i < 3 else f'`{i + 1}.`'} {loja.enfeite(interaction.guild.id, u)}{nome(interaction.guild.id, u)} — "
              f"**{numero(c['saldo'])}** moedas"
              for i, (u, c) in enumerate(top)]
    await interaction.response.send_message(embed=discord.Embed(
        title="💰 Mais ricos do servidor", description="\n".join(linhas), color=CORES["ouro"]),
        allowed_mentions=SEM_MENCAO)


# ================================================================ alertas: início e fim de partida
@bot.tree.command(name="config-alertas", description="Canal dos avisos de partida, resumos e apostas")
@app_commands.guild_only()
@app_commands.default_permissions(manage_guild=True)
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.describe(canal="Canal onde os avisos serão enviados")
async def cmd_config_alertas(interaction: discord.Interaction, canal: discord.TextChannel):
    perms = canal.permissions_for(interaction.guild.me)
    if not (perms.send_messages and perms.embed_links):
        await interaction.response.send_message(
            f"❌ Preciso de permissão para enviar mensagens e embeds em {canal.mention}.",
            ephemeral=True)
        return
    store.d["alertas"][str(interaction.guild.id)] = canal.id
    store.salvar()
    await interaction.response.send_message(
        f"✅ Pronto! Em {canal.mention} vou postar:\n"
        f"• 🎮 quando alguém vinculado entrar em partida (com raio-X e apostas)\n"
        f"• 🏁 o resumo quando a partida acabar (nota, MVP, PDL)\n"
        f"• 📅 o resumo da semana\nVerifico a cada {config.INTERVALO_ALERTA} min.", ephemeral=True)


@bot.tree.command(name="desativar-alertas", description="Desliga os avisos de partida neste servidor")
@app_commands.guild_only()
@app_commands.default_permissions(manage_guild=True)
@app_commands.checks.has_permissions(manage_guild=True)
async def cmd_desativar_alertas(interaction: discord.Interaction):
    store.d["alertas"].pop(str(interaction.guild.id), None)
    store.salvar()
    await interaction.response.send_message("✅ Alertas desativados.", ephemeral=True)


async def nova_partida(g: str, canal, game_id: str, jogo: dict, usuarios: list[str]):
    vinculos = store.de("vinculos", g)
    jogadores = {}
    for u in usuarios:
        v = vinculos[u]
        eu = next((p for p in jogo["participants"] if p.get("puuid") == v["puuid"]), {})
        elo_antes = {}
        try:
            for e in await riot.elo(v["puuid"]):
                elo_antes[e["queueType"]] = {k: e[k] for k in ("tier", "rank", "leaguePoints", "wins", "losses")}
        except RiotErro:
            pass
        jogadores[u] = {"puuid": v["puuid"], "riot_id": v["riot_id"], "time": eu.get("teamId", 0),
                        "campeao": eu.get("championId", 0), "elo_antes": elo_antes}

    embed, forcas = await montar_raio_x(jogo, {j["puuid"] for j in jogadores.values()})
    fila = jogo.get("gameQueueConfigId", 0)
    times = {p.get("teamId") for p in jogo["participants"]}
    pode_apostar = times == {100, 200} and fila != 0 and jogo.get("gameLength", 0) < 10 * 60
    odds = calcular_odds(forcas.get(100), forcas.get(200))
    apostas_ate = time.time() + config.TEMPO_APOSTAS_MIN * 60 if pode_apostar else 0

    view = discord.ui.View(timeout=None)
    if pode_apostar:
        embed.add_field(name="💰 Apostas abertas", inline=False,
                        value=f"Fecham <t:{int(apostas_ate)}:R>. 🔵 paga **{odds['100']:.2f}x** · "
                              f"🔴 paga **{odds['200']:.2f}x**")
        view.add_item(BotaoAposta(g, game_id, 100, f"Azul vence ({odds['100']:.2f}x)"))
        view.add_item(BotaoAposta(g, game_id, 200, f"Vermelho vence ({odds['200']:.2f}x)"))
    primeiro = next(iter(jogadores.values()))
    if riot.url_campeao(primeiro["campeao"]):
        embed.set_thumbnail(url=riot.url_campeao(primeiro["campeao"]))

    mencoes = ", ".join(f"{nome(g, u)}" for u in jogadores)
    texto = f"🎮 {mencoes} {'entrou' if len(jogadores) == 1 else 'entraram'} em partida!"
    try:
        await canal.send(content=texto, embed=embed, view=view, allowed_mentions=SEM_MENCAO)
    except discord.HTTPException as e:
        log.warning("Não consegui postar alerta: %s", e)
    store.de("partidas", g)[game_id] = {
        "jogadores": jogadores, "fila": fila, "inicio": time.time(), "odds": odds,
        "comecou": time.time() - max(jogo.get("gameLength", 0), 0),
        "apostas_ate": apostas_ate, "apostas": {}}


def liquidar_apostas(g: str, partida: dict, vencedor: int | None, remake: bool) -> list[str]:
    linhas = []
    for u, a in partida.get("apostas", {}).items():
        c = store.carteira(g, u)
        if remake or vencedor is None:
            c["saldo"] += a["valor"]
            loja.devolver_itens(g, u, a)
            linhas.append(f"↩️ {nome(g, u)} recebeu de volta {numero(a['valor'])}")
        elif a["time"] == vencedor:
            premio = int(a["valor"] * a["odd"] * (1.5 if a.get("turbo") else 1))
            c["saldo"] += premio
            linhas.append(f"🤑 {nome(g, u)} ganhou **{numero(premio)}** (+{numero(premio - a['valor'])})"
                          + (" 🚀" if a.get("turbo") else ""))
        elif a.get("seguro"):
            volta = a["valor"] // 2
            c["saldo"] += volta
            linhas.append(f"🛟 {nome(g, u)} perdeu {numero(a['valor'])}, mas o seguro devolveu {numero(volta)}")
        else:
            linhas.append(f"💸 {nome(g, u)} perdeu {numero(a['valor'])}")
    return linhas


async def postar_resumo(g: str, canal, partida_salva: dict, partida: dict, depois: dict[str, list]):
    info = partida["info"]
    ps = info["participants"]
    notas = calcular_notas(info)
    remake = info.get("gameDuration", 0) < 300 or any(p.get("gameEndedInEarlySurrender") for p in ps)
    vencedor = next((p["teamId"] for p in ps if p.get("win")), None)
    fila = info.get("queueId", 0)
    tipo = FILA_PARA_TIPO.get(fila)
    dano_time = defaultdict(int)
    abates_time = defaultdict(int)
    for p in ps:
        dano_time[p["teamId"]] += p.get("totalDamageDealtToChampions", 0)
        abates_time[p["teamId"]] += p["kills"]

    minutos = max(info.get("gameDuration", 60), 60) / 60
    resultados = []
    sequencias, duelos = [], []
    embed = discord.Embed(title=f"🏁 Fim de partida — {nome_fila(fila)}",
                          description=f"Duração: {int(minutos)}min", color=CORES["info"])
    for u, j in partida_salva["jogadores"].items():
        eu = next((p for p in ps if p["puuid"] == j["puuid"]), None)
        if not eu:
            continue
        k, d, a = eu["kills"], eu["deaths"], eu["assists"]
        champ = riot.nome_por_id_interno(eu["championName"])
        if remake:
            res = "⚪ Remake"
        elif fila == 1700 and eu.get("placement"):
            res = f"🏅 {eu['placement']}º lugar"
        else:
            res = "✅ Vitória" if eu.get("win") else "❌ Derrota"
        resultados.append(eu.get("win"))
        nota = notas.get(eu["puuid"], {})
        selo = " 🏆 **MVP**" if nota.get("mvp") else (" 🎖️ **ACE**" if nota.get("ace") else "")
        if nota.get("ntp"):
            selo += " 🤡 **NTP**"
        cs = eu.get("totalMinionsKilled", 0) + eu.get("neutralMinionsKilled", 0)
        dano = eu.get("totalDamageDealtToChampions", 0)
        pct_dano = round(dano / max(dano_time[eu["teamId"]], 1) * 100)
        kp = round((k + a) / max(abates_time[eu["teamId"]], 1) * 100)
        linhas = [f"{loja.enfeite(g, u)}{nome(g, u)} de **{champ}** — **{k}/{d}/{a}** (KDA {kda(k, d, a):.1f})",
                  f"💥 {numero(dano)} de dano ({pct_dano}% do time) · 🗡️ {kp}% de participação",
                  f"🌾 {cs} CS ({cs / minutos:.1f}/min) · 👁️ visão {eu.get('visionScore', 0)} · 💰 {numero(eu.get('goldEarned', 0))}",
                  f"⭐ Nota **{nota.get('nota', '-')}**/10{selo}"]
        for chave, texto in (("pentaKills", "🔥🔥 **PENTAKILL!!!**"), ("quadraKills", "🔥 **QUADRA KILL!**")):
            if eu.get(chave):
                linhas.append(texto)
                break
        pdl = None
        if tipo and u in depois and not remake:
            agora = next((e for e in depois[u] if e["queueType"] == tipo), None)
            antes = j["elo_antes"].get(tipo)
            atualizou = agora and (not antes or agora["wins"] + agora["losses"] != antes["wins"] + antes["losses"])
            if atualizou:
                txt, pdl = texto_variacao(antes, agora)
                linhas.append(txt)
        # moedas para quem jogou
        if not remake:
            bonus = (50 if eu.get("win") else 0) + (100 if nota.get("mvp") or nota.get("ace") else 0)
            if bonus:
                store.carteira(g, u)["saldo"] += bonus
                linhas.append(f"🪙 +{bonus} moedas")
        desafio = loja.checar_desafio(g, u, eu.get("championId", 0), bool(eu.get("win")), remake)
        if desafio:
            store.carteira(g, u)["saldo"] += desafio[1]
            linhas.append(desafio[0])
        embed.add_field(name=f"{res} · {j['riot_id']}", value="\n".join(linhas)[:1024], inline=False)
        store.historico(g).append({
            "user": u, "ts": time.time(), "campeao": champ, "vitoria": bool(eu.get("win")),
            "k": k, "d": d, "a": a, "nota": nota.get("nota", 0), "mvp": bool(nota.get("mvp")), "ntp": bool(nota.get("ntp")),
            "pdl": pdl, "fila": fila, "remake": remake, "penta": bool(eu.get("pentaKills")),
            "jogo": info.get("gameId"), "time": eu.get("teamId")})
        if not remake:
            aviso = aviso_sequencia(g, u)
            if aviso:
                sequencias.append(aviso)
            if nota.get("nota") is not None:
                duelos += registrar_nota_duelo(g, u, nota["nota"], partida_salva.get("inicio", 0))

    if resultados and not remake:
        embed.color = CORES["ok"] if all(resultados) else (CORES["erro"] if not any(resultados) else CORES["info"])
    apostas = liquidar_apostas(g, partida_salva, vencedor, remake)
    if apostas:
        embed.add_field(name="💰 Apostas", value="\n".join(apostas)[:1024], inline=False)
    if duelos:
        embed.add_field(name="⚔️ Duelos", value="\n".join(duelos)[:1024], inline=False)
    if sequencias:
        embed.add_field(name="📊 Sequências", value="\n".join(sequencias)[:1024], inline=False)
    primeiro = next(iter(partida_salva["jogadores"].values()))
    if riot.url_campeao(primeiro["campeao"]):
        embed.set_thumbnail(url=riot.url_campeao(primeiro["campeao"]))
    try:
        await canal.send(embed=embed, allowed_mentions=SEM_MENCAO)
    except discord.HTTPException as e:
        log.warning("Não consegui postar resumo: %s", e)


# Fim da partida → resumo. Roda a cada 30 s (loop_resultados), separado da checagem de partidas novas.
ESPERA_PDL_S = 4 * 60          # quanto tempo esperar a Riot atualizar o PDL depois que o resultado saiu
DESISTIR_NAO_ACHOU_S = 40 * 60  # partida que nunca aparece no Match-V5 (ex.: personalizada)
DESISTIR_ERRO_S = 20 * 60       # a Riot responde erro (ex.: 403 em modos especiais)
CHECAR_FIM_APOS_S = 14 * 60     # antes disso só acaba por remake, e o spectator percebe
_partidas_baixadas: dict[str, dict] = {}  # resultado já baixado, para não pedir de novo
_finalizadas: dict[str, float] = {}       # partidas já encerradas (o spectator às vezes ainda mostra)
_trava_resultados = asyncio.Lock()


def mover_para_pendentes(g: str, gid: str):
    p = store.de("partidas", g).pop(gid, None)
    if p is None:
        return
    p["pendente_desde"] = time.time()
    store.de("pendentes", g)[gid] = p
    _finalizadas[gid] = time.time()


async def checar_fim_antecipado(g: str):
    """Pergunta direto ao Match-V5 se a partida já tem resultado, sem esperar o spectator perceber."""
    for gid, p in list(store.de("partidas", g).items()):
        if time.time() - p.get("comecou", p["inicio"]) < CHECAR_FIM_APOS_S:
            continue
        try:
            partida = await riot.partida(f"{config.PLATFORM.upper()}_{gid}")
        except RiotErro:  # inclui "não encontrado": a partida ainda está rolando
            continue
        _partidas_baixadas[gid] = partida
        mover_para_pendentes(g, gid)
        log.info("Partida %s acabou (resultado já saiu no Match-V5)", gid)


def _desistir(g: str, game_id: str, motivo: str):
    p = store.de("pendentes", g).pop(game_id)
    for linha in liquidar_apostas(g, p, None, True):
        log.info("Reembolso: %s", linha)
    _partidas_baixadas.pop(game_id, None)
    log.info("Partida %s descartada: %s", game_id, motivo)


async def processar_pendentes(g: str, canal) -> bool:
    """Devolve True se algo mudou (para salvar o dados.json)."""
    mudou = False
    async with _trava_resultados:
        pendentes = store.de("pendentes", g)
        for game_id, p in list(pendentes.items()):
            agora = time.time()
            desde = p.setdefault("pendente_desde", agora)
            partida = _partidas_baixadas.get(game_id)
            if partida is None:
                try:
                    partida = await riot.partida(f"{config.PLATFORM.upper()}_{game_id}")
                except NaoEncontrado:
                    if agora - desde > DESISTIR_NAO_ACHOU_S:
                        _desistir(g, game_id, "a partida nunca apareceu na Riot")
                        mudou = True
                    continue
                except RiotErro as e:
                    if not p.get("erro_avisado"):
                        log.warning("Erro ao buscar partida %s: %s (tento por até %d min)",
                                    game_id, e, DESISTIR_ERRO_S // 60)
                        p["erro_avisado"] = True
                    if agora - desde > DESISTIR_ERRO_S:
                        _desistir(g, game_id, "a Riot não liberou o resultado")
                        mudou = True
                    continue
                _partidas_baixadas[game_id] = partida

            depois: dict[str, list] = {}
            tipo = FILA_PARA_TIPO.get(partida["info"].get("queueId"))
            esperar = False
            if tipo:
                for u, j in p["jogadores"].items():
                    try:
                        depois[u] = await riot.elo(j["puuid"])
                    except RiotErro:
                        continue
                    antes = j["elo_antes"].get(tipo)
                    atual = next((e for e in depois[u] if e["queueType"] == tipo), None)
                    if antes and atual and atual["wins"] + atual["losses"] == antes["wins"] + antes["losses"]:
                        esperar = True  # a Riot ainda não atualizou o PDL
            if esperar and agora - p.setdefault("achada_em", agora) < ESPERA_PDL_S:
                continue
            await postar_resumo(g, canal, p, partida, depois)
            pendentes.pop(game_id, None)
            _partidas_baixadas.pop(game_id, None)
            _finalizadas[game_id] = agora
            mudou = True
    return mudou


@tasks.loop(seconds=30)
async def loop_resultados():
    mudou = False
    for gid, quando in list(_finalizadas.items()):
        if time.time() - quando > 3 * 3600:
            _finalizadas.pop(gid, None)
    for g, canal_id in list(store.d["alertas"].items()):
        canal = bot.get_channel(int(canal_id))
        if canal is None:
            continue
        try:
            antes = len(store.de("partidas", g))
            await checar_fim_antecipado(g)
            mudou |= len(store.de("partidas", g)) != antes
            mudou |= await processar_pendentes(g, canal)
        except Exception:
            log.exception("Erro processando resultados do servidor %s", g)
    if mudou:
        store.salvar()


@loop_resultados.before_loop
async def _antes_resultados():
    await bot.wait_until_ready()


async def verificar_servidor(g: str, canal_id: int):
    canal = bot.get_channel(int(canal_id))
    if canal is None:
        return
    vinculos = store.de("vinculos", g)
    partidas = store.de("partidas", g)
    ativos: dict[str, dict] = {}
    em_jogo: dict[str, str] = {}
    checados = set()
    for u, v in list(vinculos.items()):
        try:
            jogo = await riot.partida_ao_vivo(v["puuid"])
        except RiotErro as e:
            log.warning("Erro ao checar %s: %s", v["riot_id"], e)
            continue
        checados.add(u)
        if jogo:
            gid = str(jogo["gameId"])
            ativos[gid] = jogo
            em_jogo[u] = gid

    # partidas que acabaram
    for gid, p in list(partidas.items()):
        if gid in ativos:
            continue
        acabou = all(u in checados for u in p["jogadores"]) or time.time() - p["inicio"] > 3 * 3600
        if acabou:
            mover_para_pendentes(g, gid)

    # partidas novas
    for gid, jogo in ativos.items():
        usuarios = [u for u, x in em_jogo.items() if x == gid]
        if gid in partidas or gid in store.de("pendentes", g) or gid in _finalizadas:
            continue
        await nova_partida(g, canal, gid, jogo, usuarios)


@tasks.loop(minutes=config.INTERVALO_ALERTA)
async def loop_partidas():
    for g, canal_id in list(store.d["alertas"].items()):
        try:
            await verificar_servidor(g, canal_id)
        except Exception:
            log.exception("Erro verificando partidas do servidor %s", g)
    store.salvar()


@loop_partidas.before_loop
async def _antes_partidas():
    await bot.wait_until_ready()


# ================================================================ resumo semanal
def montar_semana(g: str, dias: int = 7):
    limite = time.time() - dias * 86400
    hist = [e for e in store.historico(g) if e["ts"] >= limite and not e.get("remake")]
    if not hist:
        return None, None
    por = defaultdict(list)
    for e in hist:
        por[e["user"]].append(e)

    def media(u, campo):
        return sum(e[campo] for e in por[u]) / len(por[u])

    def wr(u):
        return sum(e["vitoria"] for e in por[u]) / len(por[u]) * 100

    linhas = []
    elegiveis = [u for u in por if len(por[u]) >= 3] or list(por)
    mvp = max(elegiveis, key=lambda u: media(u, "nota"))
    linhas.append(f"🏆 **MVP da semana:** {nome(g, mvp)} — nota média **{media(mvp, 'nota'):.1f}** "
                  f"em {plural(len(por[mvp]), 'partida')} (+500 moedas)")
    viciado = max(por, key=lambda u: len(por[u]))
    linhas.append(f"🎮 **Viciado:** {nome(g, viciado)} — {plural(len(por[viciado]), 'partida')}")
    vitorioso = max(por, key=lambda u: (sum(e["vitoria"] for e in por[u]), wr(u)))
    linhas.append(f"✅ **Mais vitórias:** {nome(g, vitorioso)} — {sum(e['vitoria'] for e in por[vitorioso])} "
                  f"({wr(vitorioso):.0f}% WR)")
    pdl = {u: sum(e["pdl"] for e in es if e.get("pdl") is not None) for u, es in por.items()
           if any(e.get("pdl") is not None for e in es)}
    if pdl:
        subiu = max(pdl, key=pdl.get)
        if pdl[subiu] > 0:
            linhas.append(f"📈 **Mais PDL ganho:** {nome(g, subiu)} — +{pdl[subiu]} PDL")
        caiu = min(pdl, key=pdl.get)
        if pdl[caiu] < 0:
            linhas.append(f"📉 **Mais PDL perdido:** {nome(g, caiu)} — {pdl[caiu]} PDL")
    morreu = max(por, key=lambda u: sum(e["d"] for e in por[u]))
    linhas.append(f"💀 **Quem mais morreu:** {nome(g, morreu)} — {sum(e['d'] for e in por[morreu])} mortes "
                  f"({media(morreu, 'd'):.1f} por jogo)")
    if len(elegiveis) > 1:
        frio = min(elegiveis, key=wr)
        if wr(frio) < 50:
            linhas.append(f"🥶 **Pé frio:** {nome(g, frio)} — {wr(frio):.0f}% de vitórias")
    melhor = max(hist, key=lambda e: e["nota"])
    linhas.append(f"\n⭐ **Melhor partida:** {nome(g, melhor['user'])} de {melhor['campeao']} "
                  f"{melhor['k']}/{melhor['d']}/{melhor['a']} (nota {melhor['nota']})")
    pentas = [e for e in hist if e.get("penta")]
    if pentas:
        linhas.append("🔥 **Pentakills:** " + ", ".join(f"{nome(g, e['user'])} de {e['campeao']}" for e in pentas))
    vit = sum(e["vitoria"] for e in hist)
    embed = discord.Embed(title="📅 Resumo da semana", description="\n".join(linhas), color=CORES["ouro"])
    embed.set_footer(text=f"{len(hist)} partidas do servidor · {vit}V {len(hist) - vit}D")
    return embed, mvp


@bot.tree.command(name="semana", description="Resumo dos últimos 7 dias do servidor")
@app_commands.guild_only()
async def cmd_semana(interaction: discord.Interaction):
    embed, _ = montar_semana(str(interaction.guild.id))
    if not embed:
        await interaction.response.send_message(
            "Ainda não tenho partidas registradas nesta semana. As partidas são registradas quando "
            "os alertas estão ligados (`/config-alertas`).", ephemeral=True)
        return
    embed.description = embed.description.replace(" (+500 moedas)", "")
    embed.title = "📅 Últimos 7 dias"
    await interaction.response.send_message(embed=embed, allowed_mentions=SEM_MENCAO)


@bot.tree.command(name="mvp", description="Quantas vezes cada um foi MVP e NTP nos últimos 7 dias")
@app_commands.guild_only()
async def cmd_mvp(interaction: discord.Interaction):
    g = str(interaction.guild.id)
    limite = time.time() - 7 * 86400
    hist = [e for e in store.historico(g) if e["ts"] >= limite and not e.get("remake")]
    mvps, ntps, jogos = defaultdict(int), defaultdict(int), defaultdict(int)
    for e in hist:
        jogos[e["user"]] += 1
        mvps[e["user"]] += 1 if e.get("mvp") else 0
        ntps[e["user"]] += 1 if e.get("ntp") else 0
    if not hist:
        await interaction.response.send_message(
            "Ainda não tenho partidas registradas nesta semana. As partidas são registradas quando "
            "os alertas estão ligados (`/config-alertas`).", ephemeral=True)
        return
    medalhas = ["🥇", "🥈", "🥉"]

    def tabela(contagem):
        lista = sorted((u for u in contagem if contagem[u]), key=lambda u: (-contagem[u], jogos[u]))
        if not lista:
            return "Ninguém ainda."
        return "\n".join(f"{medalhas[i] if i < 3 else f'`{i + 1}.`'} {loja.enfeite(g, u)}{nome(g, u)} — "
                         f"**{contagem[u]}x** em {plural(jogos[u], 'partida')}"
                         for i, u in enumerate(lista[:10]))

    embed = discord.Embed(title="🏆 MVP e 🤡 NTP da semana", color=CORES["ouro"])
    embed.add_field(name="🏆 MVP (melhor nota do time que venceu)", value=tabela(mvps)[:1024], inline=False)
    embed.add_field(name="🤡 NTP (pior nota da partida)", value=tabela(ntps)[:1024], inline=False)
    embed.set_footer(text=f"Últimos 7 dias · {plural(len(hist), 'partida')} registradas")
    await interaction.response.send_message(embed=embed, allowed_mentions=SEM_MENCAO)


@tasks.loop(minutes=20)
async def loop_semanal():
    agora = datetime.now(FUSO)
    if agora.weekday() != config.RESUMO_DIA or agora.hour < config.RESUMO_HORA:
        return
    semana = agora.strftime("%G-W%V")
    for g, canal_id in list(store.d["alertas"].items()):
        if store.d["resumo_semanal"].get(g) == semana:
            continue
        canal = bot.get_channel(int(canal_id))
        if canal is None:
            continue
        store.d["resumo_semanal"][g] = semana
        await sortear_rifa(g, canal)
        embed, mvp = montar_semana(g)
        if not embed:
            continue
        if mvp:
            store.carteira(g, mvp)["saldo"] += 500
        try:
            await canal.send(embed=embed, allowed_mentions=SEM_MENCAO)
        except discord.HTTPException as e:
            log.warning("Não consegui postar resumo semanal: %s", e)
    store.limpar_historico()
    store.salvar()


@loop_semanal.before_loop
async def _antes_semanal():
    await bot.wait_until_ready()


# ================================================================ /build (coleta própria Mestre+)
async def autocompletar_campeao(interaction: discord.Interaction, atual: str):
    return [app_commands.Choice(name=nome, value=str(key)) for key, nome in riot.sugerir_campeoes(atual)]


@bot.tree.command(name="build", description="Build mais usada de um campeão no Mestre+ (KR, EUW e BR)")
@app_commands.describe(campeao="Nome do campeão", rota="Rota (vazio = a mais jogada)",
                       modo="Solo/Duo ou Flex (padrão: Solo/Duo)")
@app_commands.autocomplete(campeao=autocompletar_campeao)
@app_commands.choices(
    rota=[app_commands.Choice(name=nome, value=r) for r, nome in ROTAS.items()],
    modo=[app_commands.Choice(name=nome, value=f) for f, nome in NOMES_FILAS.items()])
async def cmd_build(interaction: discord.Interaction, campeao: str,
                    rota: app_commands.Choice[str] | None = None,
                    modo: app_commands.Choice[int] | None = None):
    champ = riot.buscar_campeao(campeao)
    if champ is None:
        raise RiotErro(f"Não conheço o campeão **{campeao}**.")
    if not config.COLETA_BUILDS:
        raise RiotErro("A coleta de builds está desligada neste bot (COLETA_BUILDS no .env).")
    fila = modo.value if modo else 420
    b = coleta.build(champ, rota.value if rota else None, fila)

    nome = riot.nome_campeao(champ)
    onde = ROTAS.get(b["rota"], b["rota"])
    titulo = f"🛠️ Build de {nome} — {onde} · {NOMES_FILAS[fila]} Mestre+"
    partes = []
    if b["winrate"] is not None:
        partes.append(f"**{round(b['winrate'] * 100, 1):g}%** de vitórias")
    partes.append(f"{numero(b['partidas'])} partidas")
    descricao = " · ".join(partes)
    if b["partidas"] < 200:
        descricao += "\n⚠️ Poucas partidas ainda: a build pode variar bastante."
    embed = discord.Embed(title=titulo, description=descricao, color=CORES["ouro"])

    r = b["runas"]
    if r:
        embed.add_field(name="🔮 Runas", inline=False, value=(
            f"**{r['primaria']}:** {', '.join(r['primarias'])}\n**{r['secundaria']}:** {', '.join(r['secundarias'])}"))
    if b["feiticos"]:
        nomes = await riot.nomes_feiticos()
        embed.add_field(name="✨ Feitiços", value=" + ".join(nomes.get(f, f"Feitiço {f}") for f in b["feiticos"]))
    if b["ordem"]:
        valor = "Maximizar " + " → ".join(b["ordem"])
        if b["inicio"]:
            valor += f"\nComeço: {', '.join(b['inicio'])}"
        embed.add_field(name="📈 Habilidades", value=valor)
    if b["iniciais"]:
        contagem = Counter(b["iniciais"])
        embed.add_field(name="🎒 Itens iniciais", inline=False,
                        value=" + ".join(f"{n} x{q}" if q > 1 else n for n, q in contagem.items()))
    principais = ([f"👢 {b['botas']}"] if b["botas"] else []) + b["itens"]
    if principais:
        valor = " → ".join(principais)
        if b["itens_wr"] is not None and b["itens"]:
            valor += f"\n({round(b['itens_wr'] * 100, 1):g}% de vitórias com esses 3 itens)"
        embed.add_field(name="🛒 Itens principais", inline=False, value=valor)
    if b["opcoes"]:
        embed.add_field(name="🔁 Opções depois", inline=False, value=", ".join(b["opcoes"]))
    if riot.url_campeao(champ):
        embed.set_thumbnail(url=riot.url_campeao(champ))
    regioes = " · ".join(f"{sigla} {numero(n)}" for sigla, n in
                         sorted(b["regioes"].items(), key=lambda kv: kv[1], reverse=True))
    embed.set_footer(text=f"Patch {b['patch']} · partidas Mestre+ coletadas: {regioes}")
    await interaction.response.send_message(embed=embed)


# ================================================================ /ultimate-bravery
MAPAS_BRAVERY = {"11": "Summoner's Rift", "12": "Howling Abyss (ARAM)"}


@bot.tree.command(name="ultimate-bravery", description="Sorteia um campeão, 6 itens e 2 feitiços aleatórios")
@app_commands.describe(mapa="Mapa da partida (padrão: Summoner's Rift)")
@app_commands.choices(mapa=[app_commands.Choice(name=nome, value=m) for m, nome in MAPAS_BRAVERY.items()])
async def cmd_ultimate_bravery(interaction: discord.Interaction, mapa: app_commands.Choice[str] | None = None):
    await interaction.response.defer()
    mapa_id = mapa.value if mapa else "11"
    champ, build, sem_botas, feiticos = await sortear_bravery(mapa_id)
    quem = nome(interaction.guild.id, interaction.user.id) if interaction.guild else interaction.user.mention
    embed = embed_bravery(mapa_id, f"{quem}, você vai jogar de **{riot.nome_campeao(champ)}**!",
                          champ, build, sem_botas, feiticos)
    await interaction.followup.send(embed=embed, allowed_mentions=SEM_MENCAO)


async def sortear_bravery(mapa_id: str):
    if not riot.campeoes:
        raise RiotErro("Ainda não carreguei a lista de campeões. Tente de novo daqui a pouco.")
    d = await riot.dados_bravery(mapa_id)
    champ = random.choice(list(riot.campeoes))
    sem_botas = riot.campeoes[champ]["id"] == "Cassiopeia"  # ela não pode comprar botas
    build = ([] if sem_botas else [random.choice(d["botas"])]) + random.sample(d["lendarios"], 6 if sem_botas else 5)
    feiticos = random.sample(d["feiticos"], 2)
    return champ, build, sem_botas, feiticos


def embed_bravery(mapa_id: str, descricao: str, champ: int, build, sem_botas: bool, feiticos) -> discord.Embed:
    linhas = [f"`{i}.` {'👢 ' if i == 1 and not sem_botas else ''}**{nome}**"
              for i, (_, nome) in enumerate(build, start=1)]
    embed = discord.Embed(title=f"🎲 Ultimate Bravery — {MAPAS_BRAVERY[mapa_id]}", color=CORES["ouro"],
                          description=descricao)
    embed.add_field(name="✨ Feitiços", value=" + ".join(f"**{nome}**" for _, nome in feiticos), inline=False)
    embed.add_field(name="🛒 Build", value="\n".join(linhas), inline=False)
    if riot.url_campeao(champ):
        embed.set_thumbnail(url=riot.url_campeao(champ))
    embed.set_footer(text="Sem trocar nada. Boa sorte! 😅")
    return embed


# ================================================================ loja
@bot.tree.command(name="loja", description="Itens que dá para comprar com as moedas")
@app_commands.guild_only()
async def cmd_loja(interaction: discord.Interaction):
    g = interaction.guild.id
    embed = discord.Embed(title="🛒 Loja do bot", color=CORES["ouro"],
                          description="Compre com `/comprar`. As moedas são fictícias e não valem nada de verdade.")
    castigos_ligados = loja.servidor(g)["config"]["castigos"]
    for cat, titulo in CATEGORIAS.items():
        linhas = [f"{it['emoji']} **{it['nome']}** — {texto_preco(i)}\n　{it['desc']}"
                  for i, it in ITENS.items() if it["cat"] == cat]
        if cat == "castigos" and not castigos_ligados:
            titulo += " (desligados neste servidor)"
        embed.add_field(name=titulo, value="\n".join(linhas)[:1024], inline=False)
    saldo = store.carteira(g, interaction.user.id)["saldo"]
    store.salvar()
    embed.set_footer(text=f"Seu saldo: {numero(saldo)} moedas")
    await interaction.response.send_message(embed=embed, ephemeral=True)


def _checar_permissao(guild: discord.Guild, **perms):
    faltando = [nome for nome, _ in perms.items() if not getattr(guild.me.guild_permissions, nome)]
    if faltando:
        nomes = {"manage_roles": "Gerenciar Cargos", "manage_nicknames": "Gerenciar Apelidos",
                 "moderate_members": "Castigar Membros", "mute_members": "Silenciar Membros",
                 "deafen_members": "Ensurdecer Membros", "move_members": "Mover Membros"}
        raise ErroLoja("O bot não tem a permissão **" + ", ".join(nomes.get(f, f) for f in faltando)
                       + "** neste servidor. Peça para um admin liberar.")


def _na_call(guild: discord.Guild, membro: discord.Member) -> discord.Member:
    m = guild.get_member(membro.id)
    if not m or not m.voice or not m.voice.channel:
        raise ErroLoja(f"{nome(guild.id, membro.id)} não está em nenhuma call agora.")
    return m


async def _executar_compra(interaction: discord.Interaction, i: str, alvo: discord.Member | None,
                           texto: str | None, campeao: str | None, cor: str | None, minutos: int,
                           quantidade: int, custo: int) -> str:
    """Faz o efeito do item. Se der erro (ErroLoja), nada é cobrado."""
    guild, eu = interaction.guild, interaction.user
    g = str(guild.id)
    dados = loja.usuario(g, eu.id)

    if i == "titulo":
        dados["titulo"] = limpar_texto(texto, 40)
        return f"Seu `/perfil` agora mostra “{dados['titulo']}”."
    if i in ("cor", "cargo") and not cor:
        raise ErroLoja("Esse item precisa do campo `cor`.")
    if i == "cor":
        dados["cor"] = CORES_LOJA[cor][1]
        return f"Seu `/perfil` agora é {CORES_LOJA[cor][0].lower()}."
    if i == "fundo":
        champ = riot.buscar_campeao(campeao or "")
        if champ is None:
            raise ErroLoja("Escolha um campeão no campo `campeao`.")
        dados["fundo"] = champ
        return f"Seu `/perfil` agora tem o fundo de **{riot.nome_campeao(champ)}**."
    if i == "emoji":
        t = (texto or "").strip()
        if not emoji_valido(t):
            raise ErroLoja("Coloque só um emoji no campo `texto` (ex.: 🐸).")
        dados["emoji"] = t
        return f"Agora você aparece com {t} no ranking."
    if i == "coroa":
        if dados.get("coroa"):
            raise ErroLoja("Você já tem a Coroa de Magnata. 👑")
        dados["coroa"] = True
        return "👑 Agora todo mundo sabe que você é rico."
    if i == "cargo":
        _checar_permissao(guild, manage_roles=True)
        nome_cor, valor_cor = CORES_LOJA[cor]
        try:
            cargo = guild.get_role(int(dados.get("cargo", 0)))
            if cargo:
                await cargo.edit(colour=discord.Colour(valor_cor), reason="Loja do bot")
            else:
                cargo = await guild.create_role(name=f"🎨 {eu.display_name}"[:100], colour=discord.Colour(valor_cor),
                                                reason=f"Loja do bot: comprado por {eu}")
                try:  # sobe o cargo até logo abaixo do bot, para a cor aparecer
                    await cargo.edit(position=max(1, guild.me.top_role.position - 1))
                except discord.HTTPException:
                    pass
            await eu.add_roles(cargo, reason="Loja do bot")
        except discord.Forbidden:
            raise ErroLoja("O bot não conseguiu criar ou dar o cargo. O cargo do bot precisa estar acima dos outros.")
        dados["cargo"] = cargo.id
        return f"Você ganhou o cargo {cargo.mention} ({nome_cor.lower()})."
    if i in ("seguro", "turbo", "escudo"):
        dados[i] = dados.get(i, 0) + quantidade
        return f"Você tem agora **{dados[i]}** {ITENS[i]['nome'].lower()}(s)."
    if i == "rifa":
        rifa = loja.servidor(g)["rifa"]
        rifa["pote"] += custo
        rifa["bilhetes"][str(eu.id)] = rifa["bilhetes"].get(str(eu.id), 0) + quantidade
        return (f"Você tem **{rifa['bilhetes'][str(eu.id)]}** bilhete(s). O pote está em "
                f"**{numero(rifa['pote'])}** moedas e sai no domingo, junto com o resumo da semana.")
    if i == "anuncio":
        mensagem = limpar_texto(texto, 300)
        canal_id = store.d["alertas"].get(g)
        canal = bot.get_channel(int(canal_id)) if canal_id else interaction.channel
        embed = discord.Embed(title="📢 Anúncio", description=mensagem, color=CORES["ouro"])
        embed.set_author(name=eu.display_name, icon_url=eu.display_avatar.url)
        try:
            await (canal or interaction.channel).send(embed=embed, allowed_mentions=SEM_MENCAO)
        except discord.HTTPException:
            raise ErroLoja("Não consegui postar o anúncio no canal.")
        return "Seu anúncio foi postado."

    # itens com alvo
    if i == "desafio":
        if str(alvo.id) not in store.de("vinculos", g):
            raise ErroLoja(f"{nome(g, alvo.id)} precisa ter usado `/vincular` para o bot ver as partidas dele.")
        if not store.d["alertas"].get(g):
            raise ErroLoja("Os alertas precisam estar ligados (`/config-alertas`) para o bot ver o resultado.")
        atual = loja.servidor(g)["desafios"].get(str(alvo.id))
        if atual and atual["ate"] > time.time():
            raise ErroLoja(f"{nome(g, alvo.id)} já tem um Desafio Bravery valendo.")
        await interaction.response.defer()
        champ, build, sem_botas, feiticos = await sortear_bravery("11")
        ate = time.time() + DESAFIO_HORAS * 3600
        loja.servidor(g)["desafios"][str(alvo.id)] = {"de": str(eu.id), "campeao": champ, "ate": ate}
        embed = embed_bravery("11", f"{nome(g, alvo.id)}, {nome(g, eu.id)} te desafiou! Jogue de "
                                    f"**{riot.nome_campeao(champ)}** e vença até <t:{int(ate)}:f> para ganhar "
                                    f"**{numero(PREMIO_DESAFIO)}** moedas.", champ, build, sem_botas, feiticos)
        await interaction.followup.send(content=alvo.mention, embed=embed,
                                        allowed_mentions=discord.AllowedMentions(users=[alvo]))
        return f"Desafio enviado para {nome(g, alvo.id)}."

    # castigos e apelido: o escudo do alvo bloqueia (e a compra é cobrada mesmo assim)
    if loja.usar_escudo(g, alvo.id):
        return f"🛡️ {nome(g, alvo.id)} tinha um **Escudo** e bloqueou! Suas moedas foram embora."
    motivo = f"Loja do bot: comprado por {eu}"
    try:
        if i == "apelido":
            alvo_dados = loja.usuario(g, alvo.id)
            if alvo_dados.get("sem_apelido"):
                raise ErroLoja(f"{nome(g, alvo.id)} desligou o apelido forçado (`/bloquear-apelido`).")
            if any(p["tipo"] == "apelido" and p["user"] == str(alvo.id) for p in loja.servidor(g)["pendentes"]):
                raise ErroLoja(f"{nome(g, alvo.id)} já está com um apelido forçado.")
            novo = limpar_texto(texto, 32)
            _checar_permissao(guild, manage_nicknames=True)
            antigo = alvo.nick
            await alvo.edit(nick=novo, reason=motivo)
            loja.agendar(g, "apelido", alvo.id, APELIDO_HORAS * 3600, antigo=antigo)
            return f"{nome(g, alvo.id)} agora se chama **{escape_markdown(novo)}** por {APELIDO_HORAS}h. 🤡"
        if i == "castigo":
            _checar_permissao(guild, moderate_members=True)
            await alvo.timeout(timedelta(minutes=minutos), reason=motivo)
            loja.marcar_imune(g, alvo.id, minutos)
            return f"⛓️ {nome(g, alvo.id)} está de castigo por {plural(minutos, 'minuto')}."
        if i in ("mutar", "surdo"):
            membro = _na_call(guild, alvo)
            if i == "mutar":
                _checar_permissao(guild, mute_members=True)
                await membro.edit(mute=True, reason=motivo)
            else:
                _checar_permissao(guild, deafen_members=True)
                await membro.edit(deafen=True, reason=motivo)
            loja.agendar(g, i, alvo.id, minutos * 60)
            loja.marcar_imune(g, alvo.id, minutos)
            acao = "mutado" if i == "mutar" else "surdo"
            return f"{ITENS[i]['emoji']} {nome(g, alvo.id)} está {acao} por {plural(minutos, 'minuto')}."
        if i == "chutar":
            membro = _na_call(guild, alvo)
            _checar_permissao(guild, move_members=True)
            await membro.move_to(None, reason=motivo)
            loja.marcar_imune(g, alvo.id, 0)
            return f"🦶 {nome(g, alvo.id)} foi chutado da call."
    except discord.Forbidden:
        raise ErroLoja(f"O Discord não deixou o bot fazer isso com {nome(g, alvo.id)} "
                       "(ele é dono, admin ou tem cargo acima do bot).")
    except discord.HTTPException as e:
        raise ErroLoja(f"O Discord recusou ({e.status}). Tente de novo.")
    raise ErroLoja("Item desconhecido.")


@bot.tree.command(name="comprar", description="Compra um item da loja com suas moedas")
@app_commands.guild_only()
@app_commands.describe(item="O que comprar (veja os detalhes em /loja)",
                       alvo="O amigo vinculado (desafio, apelido e castigos)",
                       texto="Texto do título, emoji, anúncio ou apelido",
                       campeao="Campeão do fundo do perfil", cor="Cor do cartão ou do cargo",
                       minutos="Duração do castigo, mute ou ensurdecer (padrão: 1)",
                       quantidade="Quantos (seguro, odd turbinada, escudo e rifa)")
@app_commands.autocomplete(campeao=autocompletar_campeao, alvo=autocompletar_vinculado)
@app_commands.choices(
    item=[app_commands.Choice(name=f"{it['emoji']} {it['nome']} — {texto_preco(i)}"[:100], value=i)
          for i, it in ITENS.items()],
    cor=[app_commands.Choice(name=nome, value=c) for c, (nome, _) in CORES_LOJA.items()],
    minutos=[app_commands.Choice(name=plural(m, "minuto"), value=m) for m in (1, 5, 10)])
async def cmd_comprar(interaction: discord.Interaction, item: app_commands.Choice[str],
                      alvo: str | None = None, texto: str | None = None, campeao: str | None = None,
                      cor: app_commands.Choice[str] | None = None, minutos: app_commands.Choice[int] | None = None,
                      quantidade: app_commands.Range[int, 1, 50] = 1):
    g, i = str(interaction.guild.id), item.value
    alvo = await resolver_alvo(interaction.guild, alvo) if alvo else None
    mins = minutos.value if minutos else 1
    qtd = quantidade if i in CONTAVEIS else 1
    custo = preco(i, mins, qtd)
    carteira = store.carteira(g, interaction.user.id)
    if carteira["saldo"] < custo:
        raise ErroLoja(f"Isso custa **{numero(custo)}** moedas e você tem **{numero(carteira['saldo'])}**. "
                       "Use `/diario` e aposte para ganhar mais.")
    if i in CASTIGOS or i in ("desafio", "apelido"):
        if alvo is None:
            raise ErroLoja("Esse item precisa do campo `alvo` (o amigo).")
        if alvo.bot or alvo.id == interaction.user.id:
            raise ErroLoja("Escolha um amigo (não vale você mesmo nem bots).")
    if i in CASTIGOS:
        if not loja.servidor(g)["config"]["castigos"]:
            raise ErroLoja("Os castigos estão desligados neste servidor (um admin pode ligar com `/config-loja`).")
        loja.checar_alvo(g, alvo.id)

    resultado = await _executar_compra(interaction, i, alvo, texto, campeao, cor.value if cor else None,
                                       mins, qtd, custo)
    carteira["saldo"] -= custo
    store.salvar()
    it = ITENS[i]
    nome = it["nome"] + (f" x{qtd}" if qtd > 1 else "") + (f" ({plural(mins, 'minuto')})" if "precos" in it else "")
    embed = discord.Embed(title=f"🛒 {it['emoji']} {nome}", color=CORES["ok"],
                          description=f"{resultado}\n-{numero(custo)} moedas · saldo: **{numero(carteira['saldo'])}**")
    await responder(interaction, embed=embed, allowed_mentions=SEM_MENCAO)


@bot.tree.command(name="bloquear-apelido", description="Liga ou desliga o Apelido forçado da loja para você")
@app_commands.guild_only()
async def cmd_bloquear_apelido(interaction: discord.Interaction):
    dados = loja.usuario(interaction.guild.id, interaction.user.id)
    dados["sem_apelido"] = not dados.get("sem_apelido")
    store.salvar()
    await interaction.response.send_message(
        "🔒 Ninguém mais pode comprar Apelido forçado para você." if dados["sem_apelido"]
        else "🔓 Agora os amigos podem comprar Apelido forçado para você.", ephemeral=True)


@bot.tree.command(name="config-loja", description="Liga ou desliga os castigos da loja (admin)")
@app_commands.guild_only()
@app_commands.default_permissions(manage_guild=True)
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.describe(castigos="Permitir castigo, mutar, ensurdecer e chutar da call")
async def cmd_config_loja(interaction: discord.Interaction, castigos: bool):
    loja.servidor(interaction.guild.id)["config"]["castigos"] = castigos
    store.salvar()
    await interaction.response.send_message(
        "✅ Castigos ligados." if castigos else "✅ Castigos desligados.", ephemeral=True)


async def sortear_rifa(g: str, canal):
    resultado = loja.sortear_rifa(g)
    if not resultado:
        return
    vencedor, pote, total = resultado
    store.carteira(g, vencedor)["saldo"] += pote
    store.salvar()
    try:
        await canal.send(embed=discord.Embed(
            title="🎟️ Rifa da semana", color=CORES["ouro"],
            description=f"{loja.enfeite(g, vencedor)}{nome(g, vencedor)} ganhou o pote de **{numero(pote)}** moedas! "
                        f"({plural(total, 'bilhete')} vendidos)"), allowed_mentions=SEM_MENCAO)
    except discord.HTTPException as e:
        log.warning("Não consegui postar a rifa: %s", e)


async def desfazer_castigo(guild: discord.Guild, p: dict) -> bool:
    """Desmuta, tira o ensurdecer ou devolve o apelido. False = tentar de novo depois."""
    membro = guild.get_member(int(p["user"]))
    if membro is None:
        try:
            membro = await guild.fetch_member(int(p["user"]))
        except discord.NotFound:
            return True
        except discord.HTTPException:
            return False
    try:
        if p["tipo"] in ("mutar", "surdo"):
            if not membro.voice:
                return False  # só dá para desmutar quem está numa call; tenta quando ele entrar
            if p["tipo"] == "mutar":
                await membro.edit(mute=False, reason="Fim do castigo da loja")
            else:
                await membro.edit(deafen=False, reason="Fim do castigo da loja")
        elif p["tipo"] == "apelido":
            await membro.edit(nick=p.get("antigo"), reason="Fim do apelido forçado da loja")
    except discord.Forbidden:
        return True
    except discord.HTTPException:
        return False
    return True


@tasks.loop(seconds=20)
async def loop_loja():
    await expirar_duelos()
    agora = time.time()
    mudou = False
    for g, s in list(store.d["loja"].items()):
        pendentes = s.get("pendentes") or []
        guild = bot.get_guild(int(g))
        if not pendentes or guild is None:
            continue
        restantes = []
        for p in pendentes:
            if p["ate"] > agora:
                restantes.append(p)
            elif not await desfazer_castigo(guild, p) and agora - p["ate"] < 30 * 86400:
                restantes.append(p)
        if len(restantes) != len(pendentes):
            s["pendentes"] = restantes
            mudou = True
    if mudou:
        store.salvar()


@loop_loja.before_loop
async def _antes_loja():
    await bot.wait_until_ready()


@bot.event
async def on_voice_state_update(membro: discord.Member, antes: discord.VoiceState, depois: discord.VoiceState):
    if depois.channel is None or antes.channel is not None:
        return
    s = store.d["loja"].get(str(membro.guild.id))
    if not s or not s.get("pendentes"):
        return
    agora = time.time()
    for p in list(s["pendentes"]):
        if p["user"] == str(membro.id) and p["tipo"] in ("mutar", "surdo") and p["ate"] <= agora:
            if await desfazer_castigo(membro.guild, p):
                s["pendentes"].remove(p)
                store.salvar()


# ================================================================ sequências (tilt / on fire)
AVISOS_SEQUENCIA = {
    True: {5: "🔥 {quem} ganhou **{n} seguidas**! Está on fire.", 7: "🔥🔥 {quem} ganhou **{n} seguidas**! Alguém para essa pessoa.",
           10: "☄️ {quem} ganhou **{n} seguidas**! Isso é smurf?", 15: "👑 {quem} ganhou **{n} seguidas**!!!"},
    False: {4: "😬 {quem} perdeu **{n} seguidas**. Hora de um copo d'água?",
            6: "🥶 {quem} perdeu **{n} seguidas**. Talvez seja melhor dar uma pausa...",
            8: "💀 {quem} perdeu **{n} seguidas**. Desinstala?", 10: "🪦 {quem} perdeu **{n} seguidas**. F."},
}


def aviso_sequencia(g: str, u: str) -> str | None:
    """Avisa quando alguém chega em certas sequências de vitórias ou derrotas (sem contar remakes)."""
    hist = sorted((e for e in store.historico(g) if e["user"] == u and not e.get("remake")),
                  key=lambda e: e["ts"], reverse=True)
    if not hist:
        return None
    ultimo, n = hist[0]["vitoria"], 0
    for e in hist:
        if e["vitoria"] != ultimo:
            break
        n += 1
    modelo = AVISOS_SEQUENCIA[bool(ultimo)].get(n)
    return modelo.format(quem=nome(g, u), n=n) if modelo else None


# ================================================================ duelos
DUELO_ACEITAR_MIN = 30
DUELO_HORAS = 48


def duelo_ativo(g: str, u: str, exceto: str | None = None) -> bool:
    return any(u in (d["de"], d["para"]) and did != exceto for did, d in store.de("duelos", g).items())


def registrar_nota_duelo(g: str, u: str, nota: float, inicio: float) -> list[str]:
    linhas = []
    duelos = store.de("duelos", g)
    for did, d in list(duelos.items()):
        if d["estado"] != "aceito" or u not in (d["de"], d["para"]) or u in d["notas"] or inicio < d["aceito_em"]:
            continue
        d["notas"][u] = nota
        outro = d["para"] if u == d["de"] else d["de"]
        if outro not in d["notas"]:
            linhas.append(f"{nome(g, u)} tirou **{nota}** no duelo contra {nome(g, outro)}. Agora é a vez de {nome(g, outro)}!")
            continue
        duelos.pop(did)
        if d["notas"][u] == d["notas"][outro]:
            for x in (u, outro):
                store.carteira(g, x)["saldo"] += d["valor"]
            linhas.append(f"🤝 Duelo {nome(g, u)} x {nome(g, outro)} empatou (nota {nota}). As moedas voltaram.")
            continue
        venc, perd = sorted((u, outro), key=lambda x: d["notas"][x], reverse=True)
        store.carteira(g, venc)["saldo"] += d["valor"] * 2
        linhas.append(f"🏆 {loja.enfeite(g, venc)}{nome(g, venc)} (nota **{d['notas'][venc]}**) venceu o duelo contra "
                      f"{nome(g, perd)} (nota {d['notas'][perd]}) e levou **{numero(d['valor'] * 2)}** moedas!")
    return linhas


class BotaoDuelo(discord.ui.DynamicItem[discord.ui.Button],
                 template=r"duelo:(?P<g>\d+):(?P<id>\d+):(?P<acao>sim|nao)"):
    def __init__(self, g, did, acao: str):
        sim = acao == "sim"
        super().__init__(discord.ui.Button(
            label="Aceitar" if sim else "Recusar", emoji="⚔️" if sim else "✖️",
            style=discord.ButtonStyle.success if sim else discord.ButtonStyle.secondary,
            custom_id=f"duelo:{g}:{did}:{acao}"))
        self.g, self.did, self.acao = str(g), str(did), acao

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match["g"], match["id"], match["acao"])

    async def callback(self, interaction: discord.Interaction):
        d = store.de("duelos", self.g).get(self.did)
        uid = str(interaction.user.id)
        if not d or d["estado"] != "pendente":
            await interaction.response.send_message("❌ Esse duelo não está mais esperando resposta.", ephemeral=True)
            return
        if self.acao == "nao":
            if uid not in (d["de"], d["para"]):
                await interaction.response.send_message("❌ Só quem está no duelo pode recusar.", ephemeral=True)
                return
            store.de("duelos", self.g).pop(self.did)
            store.carteira(self.g, d["de"])["saldo"] += d["valor"]
            store.salvar()
            acao = "recusou" if uid == d["para"] else "cancelou"
            await interaction.response.edit_message(
                content=f"✖️ {nome(self.g, uid)} {acao} o duelo. As moedas voltaram para {nome(self.g, d['de'])}.",
                embed=None, view=None, allowed_mentions=SEM_MENCAO)
            return
        if uid != d["para"]:
            await interaction.response.send_message(f"❌ Só {nome(self.g, d['para'])} pode aceitar esse duelo.", ephemeral=True)
            return
        if duelo_ativo(self.g, uid, exceto=self.did):
            await interaction.response.send_message("❌ Você já está em outro duelo.", ephemeral=True)
            return
        carteira = store.carteira(self.g, uid)
        if carteira["saldo"] < d["valor"]:
            await interaction.response.send_message(
                f"❌ Você precisa de **{numero(d['valor'])}** moedas e tem **{numero(carteira['saldo'])}**.",
                ephemeral=True)
            return
        carteira["saldo"] -= d["valor"]
        d["estado"], d["aceito_em"] = "aceito", time.time()
        store.salvar()
        embed = interaction.message.embeds[0] if interaction.message and interaction.message.embeds else discord.Embed()
        embed.color = CORES["ok"]
        embed.add_field(name="✅ Duelo aceito!", inline=False, value=(
            f"Vale a próxima partida de cada um (até <t:{int(time.time() + DUELO_HORAS * 3600)}:f>). "
            f"Quem tirar a maior nota leva **{numero(d['valor'] * 2)}** moedas."))
        await interaction.response.edit_message(embed=embed, view=None)


@bot.tree.command(name="duelo", description="Desafia um amigo: quem tirar a maior nota na próxima partida leva as moedas")
@app_commands.guild_only()
@app_commands.describe(amigo="Quem você quer desafiar (amigos vinculados)", moedas="Quanto cada um aposta")
@app_commands.autocomplete(amigo=autocompletar_vinculado)
async def cmd_duelo(interaction: discord.Interaction, amigo: str,
                    moedas: app_commands.Range[int, 50, 1_000_000]):
    amigo = await resolver_alvo(interaction.guild, amigo)
    g, eu, ele = str(interaction.guild.id), str(interaction.user.id), str(amigo.id)
    if amigo.bot or ele == eu:
        raise RiotErro("Escolha um amigo (não vale você mesmo nem bots).")
    if not store.d["alertas"].get(g):
        raise RiotErro("Os alertas precisam estar ligados (`/config-alertas`) para o bot ver as notas.")
    vinculos = store.de("vinculos", g)
    for x in (eu, ele):
        if x not in vinculos:
            raise RiotErro(f"{nome(g, x)} precisa usar `/vincular` antes de duelar.")
        if duelo_ativo(g, x):
            raise RiotErro(f"{nome(g, x)} já está em um duelo. Um de cada vez!")
    carteira = store.carteira(g, eu)
    if carteira["saldo"] < moedas:
        raise RiotErro(f"Você tem só **{numero(carteira['saldo'])}** moedas.")
    carteira["saldo"] -= moedas
    did = str(int(time.time() * 1000))
    store.de("duelos", g)[did] = {"de": eu, "para": ele, "valor": moedas, "estado": "pendente",
                                  "criado": time.time(), "notas": {}}
    store.salvar()
    embed = discord.Embed(title="⚔️ Duelo de nota!", color=CORES["aviso"], description=(
        f"{nome(g, eu)} desafiou {nome(g, ele)} valendo **{numero(moedas)}** moedas de cada um.\n"
        f"Quem tirar a **maior nota** na próxima partida leva **{numero(moedas * 2)}**.\n"
        f"O convite vale até <t:{int(time.time() + DUELO_ACEITAR_MIN * 60)}:t>."))
    view = discord.ui.View(timeout=None)
    view.add_item(BotaoDuelo(g, did, "sim"))
    view.add_item(BotaoDuelo(g, did, "nao"))
    await interaction.response.send_message(content=amigo.mention, embed=embed, view=view,
                                            allowed_mentions=discord.AllowedMentions(users=[amigo]))


async def expirar_duelos():
    agora = time.time()
    for g, duelos in list(store.d["duelos"].items()):
        for did, d in list(duelos.items()):
            if d["estado"] == "pendente" and agora - d["criado"] > DUELO_ACEITAR_MIN * 60:
                store.carteira(g, d["de"])["saldo"] += d["valor"]
                texto = f"⌛ {nome(g, d['para'])} não respondeu o duelo de {nome(g, d['de'])}. As moedas voltaram."
            elif d["estado"] == "aceito" and agora - d["aceito_em"] > DUELO_HORAS * 3600:
                for x in (d["de"], d["para"]):
                    store.carteira(g, x)["saldo"] += d["valor"]
                texto = f"⌛ O duelo de {nome(g, d['de'])} e {nome(g, d['para'])} passou de {DUELO_HORAS}h sem as duas partidas. As moedas voltaram."
            else:
                continue
            duelos.pop(did)
            store.salvar()
            canal = bot.get_channel(int(store.d["alertas"].get(g, 0) or 0))
            if canal:
                try:
                    await canal.send(texto, allowed_mentions=SEM_MENCAO)
                except discord.HTTPException:
                    pass


# ================================================================ /duplas
@bot.tree.command(name="duplas", description="Quais amigos ganham mais jogando juntos (últimos 35 dias)")
@app_commands.guild_only()
async def cmd_duplas(interaction: discord.Interaction):
    g = str(interaction.guild.id)
    grupos = defaultdict(list)
    for e in store.historico(g):
        if not e.get("remake"):
            grupos[e.get("jogo") or (e.get("fila"), round(e["ts"]))].append(e)
    duplas = defaultdict(lambda: [0, 0])
    for es in grupos.values():
        for a, b in combinations(sorted(es, key=lambda e: e["user"]), 2):
            if a["user"] == b["user"]:
                continue
            mesmo_time = a["time"] == b["time"] if a.get("time") and b.get("time") else a["vitoria"] == b["vitoria"]
            if mesmo_time:
                duplas[(a["user"], b["user"])][0] += 1
                duplas[(a["user"], b["user"])][1] += a["vitoria"]
    if not duplas:
        await interaction.response.send_message(
            "Ainda não tenho partidas de amigos jogando juntos. Elas são registradas quando os alertas estão ligados.")
        return
    lista = sorted(duplas.items(), key=lambda kv: (kv[1][0], kv[1][1]), reverse=True)
    linhas = [f"{nome(g, a)} + {nome(g, b)} — {plural(j, 'jogo')} · **{round(v / j * 100)}%** de vitórias"
              for (a, b), (j, v) in lista[:12]]
    elegiveis = [kv for kv in lista if kv[1][0] >= 3]
    if len(elegiveis) >= 2:
        (a, b), (j, v) = max(elegiveis, key=lambda kv: kv[1][1] / kv[1][0])
        linhas.append(f"\n💞 **Dupla dos sonhos:** {nome(g, a)} + {nome(g, b)} ({round(v / j * 100)}% em {j})")
        (a, b), (j, v) = min(elegiveis, key=lambda kv: kv[1][1] / kv[1][0])
        linhas.append(f"💔 **Dupla do caos:** {nome(g, a)} + {nome(g, b)} ({round(v / j * 100)}% em {j})")
    embed = discord.Embed(title="👯 Duplas do servidor", description="\n".join(linhas)[:4000], color=CORES["info"])
    embed.set_footer(text="Partidas dos últimos 35 dias registradas pelos alertas")
    await interaction.response.send_message(embed=embed, allowed_mentions=SEM_MENCAO)


# ================================================================ /tierlist e /counter (coleta Mestre+)
def _checar_coleta():
    if not config.COLETA_BUILDS:
        raise RiotErro("A coleta de builds está desligada neste bot (COLETA_BUILDS no .env).")


@bot.tree.command(name="tierlist", description="Campeões mais fortes de uma rota no Mestre+ (KR, EUW e BR)")
@app_commands.describe(rota="Rota", modo="Solo/Duo ou Flex (padrão: Solo/Duo)")
@app_commands.choices(rota=[app_commands.Choice(name=nome, value=r) for r, nome in ROTAS.items()],
                      modo=[app_commands.Choice(name=nome, value=f) for f, nome in NOMES_FILAS.items()])
async def cmd_tierlist(interaction: discord.Interaction, rota: app_commands.Choice[str],
                       modo: app_commands.Choice[int] | None = None):
    _checar_coleta()
    fila = modo.value if modo else 420
    t = coleta.tierlist(rota.value, fila)
    faixas = [("S", 0.53), ("A", 0.515), ("B", 0.50), ("C", 0.485), ("D", 0.0)]
    grupos: dict[str, list[str]] = {f: [] for f, _ in faixas}
    for c in t["campeoes"][:30]:
        faixa = next(f for f, minimo in faixas if c["ajustada"] >= minimo)
        grupos[faixa].append(f"{riot.nome_campeao(c['campeao'])} ({round(c['winrate'] * 100, 1):g}%)")
    cores = {"S": "🟥", "A": "🟧", "B": "🟨", "C": "🟩", "D": "🟦"}
    linhas = [f"{cores[f]} **{f}** — {', '.join(nomes)}" for f, nomes in grupos.items() if nomes]
    melhor = t["campeoes"][0]
    embed = discord.Embed(title=f"📊 Tier list — {rota.name} · {NOMES_FILAS[fila]} Mestre+", color=CORES["ouro"],
                          description="\n".join(linhas)[:4000])
    if riot.url_campeao(melhor["campeao"]):
        embed.set_thumbnail(url=riot.url_campeao(melhor["campeao"]))
    embed.set_footer(text=f"Patch {t['patch']} · {numero(t['partidas'])} partidas · % = taxa de vitória "
                          "(campeões com poucas partidas contam mais perto de 50%)")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="counter", description="Contra quem um campeão mais ganha e perde no Mestre+")
@app_commands.describe(campeao="Nome do campeão", rota="Rota (vazio = a mais jogada)",
                       modo="Solo/Duo ou Flex (padrão: Solo/Duo)")
@app_commands.autocomplete(campeao=autocompletar_campeao)
@app_commands.choices(rota=[app_commands.Choice(name=nome, value=r) for r, nome in ROTAS.items()],
                      modo=[app_commands.Choice(name=nome, value=f) for f, nome in NOMES_FILAS.items()])
async def cmd_counter(interaction: discord.Interaction, campeao: str, rota: app_commands.Choice[str] | None = None,
                      modo: app_commands.Choice[int] | None = None):
    _checar_coleta()
    champ = riot.buscar_campeao(campeao)
    if champ is None:
        raise RiotErro(f"Não conheço o campeão **{campeao}**.")
    fila = modo.value if modo else 420
    c = coleta.counters(champ, rota.value if rota else None, fila)

    def linha(x):
        return (f"**{riot.nome_campeao(x['campeao'])}** — {round(x['winrate'] * 100, 1):g}% "
                f"em {plural(x['jogos'], 'jogo')}")

    lista = c["confrontos"]
    metade = min(5, len(lista) // 2)
    nome = riot.nome_campeao(champ)
    embed = discord.Embed(title=f"⚔️ Confrontos de {nome} — {ROTAS[c['rota']]} · {NOMES_FILAS[fila]} Mestre+",
                          color=CORES["info"])
    embed.add_field(name="✅ Ganha mais de", value="\n".join(linha(x) for x in lista[:metade]), inline=False)
    embed.add_field(name="❌ Perde mais para", value="\n".join(linha(x) for x in reversed(lista[-metade:])),
                    inline=False)
    if riot.url_campeao(champ):
        embed.set_thumbnail(url=riot.url_campeao(champ))
    embed.set_footer(text=f"% = vitórias de {nome} no confronto · {numero(c['jogos'])} partidas nos 2 últimos patches")
    await interaction.response.send_message(embed=embed)


# ================================================================ /comparar
async def resumo_jogador(conta: dict) -> dict:
    puuid = conta["puuid"]
    filas, maes, ids = await asyncio.gather(riot.elo(puuid), riot.maestrias(puuid, 3), riot.ids_partidas(puuid, 5))
    partidas = await asyncio.gather(*(riot.partida(i) for i in ids), return_exceptions=True)
    jogos = []
    for p in partidas:
        if isinstance(p, Exception):
            continue
        eu = next((x for x in p["info"]["participants"] if x["puuid"] == puuid), None)
        if not eu or eu.get("gameEndedInEarlySurrender"):
            continue
        minutos = max(p["info"].get("gameDuration", 60), 60) / 60
        jogos.append({
            "v": 1 if eu.get("win") else 0, "k": eu["kills"], "d": eu["deaths"], "a": eu["assists"],
            "cs": (eu.get("totalMinionsKilled", 0) + eu.get("neutralMinionsKilled", 0)) / minutos,
            "dano": eu.get("totalDamageDealtToChampions", 0) / minutos,
            "visao": eu.get("visionScore", 0) / minutos,
            "nota": calcular_notas(p["info"]).get(puuid, {}).get("nota")})

    def media(campo):
        valores = [j[campo] for j in jogos if j[campo] is not None]
        return sum(valores) / len(valores) if valores else None

    solo = next((f for f in filas if f["queueType"] == "RANKED_SOLO_5x5"), None)
    flex = next((f for f in filas if f["queueType"] == "RANKED_FLEX_SR"), None)
    k, d, a = (sum(j[x] for j in jogos) for x in ("k", "d", "a"))
    return {
        "nome": f"{conta['gameName']}#{conta['tagLine']}", "solo": solo, "flex": flex, "jogos": len(jogos),
        "vitorias": sum(j["v"] for j in jogos), "kda": kda(k, d, a) if jogos else None,
        "nota": media("nota"), "cs": media("cs"), "dano": media("dano"), "visao": media("visao"),
        "campeoes": [riot.nome_campeao(m["championId"]) for m in maes],
    }


@bot.tree.command(name="comparar", description="Compara dois jogadores lado a lado")
@app_commands.describe(jogador1="Riot ID com TAG, ex.: Faker#KR1",
                       jogador2="Riot ID com TAG (vazio = sua conta vinculada)")
async def cmd_comparar(interaction: discord.Interaction, jogador1: str, jogador2: str | None = None):
    await interaction.response.defer()
    contas = [await riot.conta(jogador1), await resolver_jogador(jogador2, interaction)]
    if contas[0]["puuid"] == contas[1]["puuid"]:
        raise RiotErro("Escolha dois jogadores diferentes.")
    a, b = await asyncio.gather(*(resumo_jogador(c) for c in contas))

    def elo_txt(e):
        return texto_elo(e) if e else "Sem elo"

    metricas = [  # (nome, função do valor para comparar, texto)
        ("Solo/Duo", lambda x: pontuacao_elo(x["solo"]) if x["solo"] else -1, lambda x: elo_txt(x["solo"])),
        ("Flex", lambda x: pontuacao_elo(x["flex"]) if x["flex"] else -1, lambda x: elo_txt(x["flex"])),
        ("Vitórias", lambda x: x["vitorias"] / x["jogos"] if x["jogos"] else -1,
         lambda x: f"{x['vitorias']} de {x['jogos']}" if x["jogos"] else "-"),
        ("KDA", lambda x: x["kda"] if x["kda"] is not None else -1, lambda x: f"{x['kda']:.2f}" if x["kda"] is not None else "-"),
        ("Nota média", lambda x: x["nota"] or -1, lambda x: f"{x['nota']:.1f}" if x["nota"] is not None else "-"),
        ("CS/min", lambda x: x["cs"] or -1, lambda x: f"{x['cs']:.1f}" if x["cs"] is not None else "-"),
        ("Dano/min", lambda x: x["dano"] or -1, lambda x: numero(int(x["dano"])) if x["dano"] is not None else "-"),
        ("Visão/min", lambda x: x["visao"] or -1, lambda x: f"{x['visao']:.2f}" if x["visao"] is not None else "-"),
    ]
    colunas = {0: [], 1: []}
    placar = [0, 0]
    for nome, valor, texto in metricas:
        va, vb = valor(a), valor(b)
        for i, x in enumerate((a, b)):
            melhor = (va > vb) if i == 0 else (vb > va)
            if melhor:
                placar[i] += 1
            colunas[i].append(f"**{nome}:** {texto(x)}{' ✅' if melhor else ''}")
    for i, x in enumerate((a, b)):
        if x["campeoes"]:
            colunas[i].append(f"**Favoritos:** {', '.join(x['campeoes'])}")
    embed = discord.Embed(title=f"🆚 {a['nome']} x {b['nome']}", color=CORES["info"])
    embed.add_field(name=f"🔵 {a['nome']}", value="\n".join(colunas[0])[:1024], inline=True)
    embed.add_field(name=f"🔴 {b['nome']}", value="\n".join(colunas[1])[:1024], inline=True)
    if placar[0] != placar[1]:
        vencedor = a if placar[0] > placar[1] else b
        resultado = f"🏆 {vencedor['nome']} vence em {max(placar)} de {len(metricas)} quesitos"
    else:
        resultado = "🤝 Empate técnico"
    embed.add_field(name="Resultado", value=resultado, inline=False)
    embed.set_footer(text="Médias das últimas 5 partidas de cada um (sem remakes)")
    await interaction.followup.send(embed=embed)


# ================================================================ status do servidor BR e patch novo
async def postar_em_todos(embed: discord.Embed):
    for g, canal_id in list(store.d["alertas"].items()):
        canal = bot.get_channel(int(canal_id))
        if canal:
            try:
                await canal.send(embed=embed, allowed_mentions=SEM_MENCAO)
            except discord.HTTPException as e:
                log.warning("Não consegui postar aviso no servidor %s: %s", g, e)


def _traduzir(lista: list) -> str:
    textos = {t.get("locale"): t.get("content", "") for t in lista or []}
    return textos.get("pt_BR") or textos.get("en_US") or next(iter(textos.values()), "")


@tasks.loop(minutes=10)
async def loop_status():
    if not store.d["alertas"]:
        return
    try:
        dados = await riot.status_servidor()
    except RiotErro as e:
        log.warning("Não consegui checar o status do servidor: %s", e)
        return
    ativos = store.d["geral"].setdefault("status_ativos", {})
    atuais = {}
    for tipo, chave in (("manutencao", "maintenances"), ("incidente", "incidents")):
        for item in dados.get(chave) or []:
            if item.get("maintenance_status") != "complete":
                atuais[str(item.get("id"))] = (tipo, item)
    mudou = False
    for i, (tipo, item) in atuais.items():
        if i in ativos:
            continue
        titulo = _traduzir(item.get("titles")) or "Aviso da Riot"
        atualizacoes = sorted(item.get("updates") or [], key=lambda u: u.get("created_at") or "")
        detalhe = _traduzir(atualizacoes[-1].get("translations")) if atualizacoes else ""
        if tipo == "manutencao":
            agendada = item.get("maintenance_status") == "scheduled"
            cabeca, cor = ("🗓️ Manutenção agendada" if agendada else "🚧 Manutenção"), CORES["aviso"]
        else:
            critico = item.get("incident_severity") == "critical"
            cabeca, cor = ("🚨 Problema no servidor" if critico else "⚠️ Aviso do servidor"), CORES["erro"]
        embed = discord.Embed(title=f"{cabeca} BR — {titulo}"[:256], description=detalhe[:1000] or None, color=cor)
        embed.set_footer(text="Fonte: status oficial da Riot")
        await postar_em_todos(embed)
        ativos[i] = titulo
        mudou = True
    for i in [i for i in ativos if i not in atuais]:
        await postar_em_todos(discord.Embed(title=f"✅ Resolvido — {ativos.pop(i)}"[:256], color=CORES["ok"]))
        mudou = True
    if mudou:
        store.salvar()


@loop_status.before_loop
async def _antes_status():
    await bot.wait_until_ready()


async def anunciar_patch(patch: str):
    anterior = store.d["geral"].get("patch_anunciado")
    if anterior and _ordem_patch(patch) <= _ordem_patch(anterior):
        return
    store.d["geral"]["patch_anunciado"] = patch
    store.salvar()
    embed = discord.Embed(title=f"📝 Patch novo no ar (versão {patch})", color=CORES["info"], description=(
        "As partidas do patch novo já começaram a aparecer no alto elo. O `/build`, a `/tierlist` e o "
        "`/counter` vão se atualizando conforme as partidas chegam.\n"
        "[Ler as notas do patch](https://www.leagueoflegends.com/pt-br/news/tags/patch-notes/)"))
    await postar_em_todos(embed)


# ================================================================ /ajuda
@bot.tree.command(name="ajuda", description="Lista os comandos do bot")
async def cmd_ajuda(interaction: discord.Interaction):
    embed = discord.Embed(title="📖 Comandos", color=CORES["info"])
    embed.add_field(name="🔎 Consultas", inline=False, value=(
        "`/perfil` — cartão de perfil em imagem\n"
        "`/elo` — elo, PDL e winrate\n"
        "`/historico` — últimas partidas\n"
        "`/maestria` — campeões com mais maestria\n"
        "`/aovivo` — raio-X da partida atual (elo dos 10 jogadores)\n"
        "`/build campeão` — build mais usada no Mestre+ (KR, EUW e BR)\n"
        "`/tierlist rota` · `/counter campeão` — mais fortes e confrontos no Mestre+\n"
        "`/comparar` — dois jogadores lado a lado\n"
        "`/ultimate-bravery` — sorteia campeão, itens e feitiços"))
    embed.add_field(name="👥 Servidor", inline=False, value=(
        "`/vincular Nome#TAG` — liga sua conta\n"
        "`/ranking` — ranking de elo (Solo/Duo e Flex)\n"
        "`/semana` — resumo dos últimos 7 dias\n"
        "`/mvp` — quantas vezes cada um foi MVP e NTP na semana\n"
        "`/duplas` — quem ganha mais jogando junto\n"
        "`/config-alertas #canal` — avisos, resumos e apostas (admin)"))
    embed.add_field(name="💰 Apostas (moedas fictícias)", inline=False, value=(
        "Aposte pelos botões quando alguém entrar em partida.\n"
        "`/duelo @amigo` — maior nota na próxima partida leva as moedas\n"
        "`/carteira` · `/diario` · `/top-moedas`"))
    embed.add_field(name="🛒 Loja", inline=False, value=(
        "`/loja` — itens à venda · `/comprar` — compra um item\n"
        "`/bloquear-apelido` — não deixa mudarem seu apelido · `/config-loja` — liga/desliga castigos (admin)"))
    embed.set_footer(text="Sem o Nome#TAG, os comandos usam a sua conta vinculada.")
    await interaction.response.send_message(embed=embed, ephemeral=True)


# ================================================================ iniciar
if __name__ == "__main__":
    faltando = [n for n, v in (("DISCORD_TOKEN", config.DISCORD_TOKEN), ("RIOT_API_KEY", config.RIOT_API_KEY))
                if not v or v.startswith("cole_")]
    if faltando:
        raise SystemExit(f"Preencha no arquivo .env: {', '.join(faltando)}")
    bot.run(config.DISCORD_TOKEN, log_handler=None)
