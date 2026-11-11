"""Conexão com a API da Riot e com o Data Dragon (nomes e imagens do jogo)."""
import asyncio
import hashlib
import logging
import time
import unicodedata
from collections import OrderedDict, deque
from urllib.parse import quote

import aiohttp

import config

log = logging.getLogger("bot-lol.riot")
DD = "https://ddragon.leagueoflegends.com"


class RiotErro(Exception):
    """Erro com mensagem amigável para mostrar no Discord."""


class NaoEncontrado(RiotErro):
    pass


def normalizar(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return "".join(c for c in t.lower() if c.isalnum())


class Limitador:
    """Garante que o bot não passe do limite de requisições da chave."""

    def __init__(self, limites: list[tuple[int, float]]):
        self.limites = limites
        self.historico: deque[float] = deque()
        self.lock = asyncio.Lock()

    def uso(self, janela: float) -> int:
        agora = time.monotonic()
        return sum(1 for t in self.historico if agora - t < janela)

    async def esperar(self):
        async with self.lock:
            while True:
                agora = time.monotonic()
                maior = max(s for _, s in self.limites)
                while self.historico and agora - self.historico[0] >= maior:
                    self.historico.popleft()
                espera = 0.0
                for qtd, seg in self.limites:
                    dentro = [t for t in self.historico if agora - t < seg]
                    if len(dentro) >= qtd:
                        espera = max(espera, seg - (agora - dentro[-qtd]) + 0.05)
                if espera <= 0:
                    self.historico.append(agora)
                    return
                await asyncio.sleep(espera)


class RiotAPI:
    def __init__(self):
        self.chave = config.RIOT_API_KEY
        self.base_plat = f"https://{config.PLATFORM}.api.riotgames.com"
        self.base_reg = f"https://{config.REGION}.api.riotgames.com"
        self.session: aiohttp.ClientSession | None = None
        self.limitador = Limitador([(config.LIMITE_SEG, 1), (config.LIMITE_2MIN, 120)])
        self.versao = "15.1.1"
        self.campeoes: dict[int, dict] = {}       # 103 -> {"id": "Ahri", "nome": "Ahri"}
        self.campeao_por_id: dict[str, int] = {}  # "MonkeyKing" -> 62
        self.itens: dict[int, dict] = {}
        self.runas: dict[int, dict] = {}          # runa ou árvore -> {"nome", "icone"}
        self.feiticos: dict[int, dict] = {}
        self._imagens: OrderedDict[str, bytes] = OrderedDict()
        self._bravery: dict | None = None  # itens e feitiços do /ultimate-bravery (baixados no 1º uso)
        self.pasta_cache = config.PASTA / "cache"

    # ------------------------------------------------------------ ciclo de vida
    async def iniciar(self):
        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20))
        self.pasta_cache.mkdir(exist_ok=True)
        await self.carregar_estaticos()

    async def fechar(self):
        if self.session:
            await self.session.close()

    async def _json_dd(self, caminho: str):
        async with self.session.get(f"{DD}{caminho}") as r:
            r.raise_for_status()
            return await r.json(content_type=None)

    async def carregar_estaticos(self):
        """Baixa os nomes dos campeões em português."""
        try:
            self.versao = (await self._json_dd("/api/versions.json"))[0]
            base = f"/cdn/{self.versao}/data/pt_BR"
            camps = await self._json_dd(f"{base}/champion.json")
        except Exception as e:
            log.warning("Não consegui carregar dados do Data Dragon: %s", e)
            return

        for c in camps["data"].values():
            self.campeoes[int(c["key"])] = {"id": c["id"], "nome": c["name"]}
            self.campeao_por_id[c["id"]] = int(c["key"])

        log.info("Data Dragon %s: %d campeões", self.versao, len(self.campeoes))

    async def dados_bravery(self, mapa: str = "11") -> dict:
        """Itens lendários, botas e feitiços de um mapa ("11" = Summoner's Rift, "12" = Howling Abyss),
        só com id e nome. Baixa na primeira vez que alguém usa o /ultimate-bravery, para não gastar
        memória à toa."""
        if not self._bravery or self._bravery["versao"] != self.versao:
            self._bravery = await self._baixar_bravery()
        return self._bravery[mapa]

    async def _baixar_bravery(self) -> dict:
        base = f"/cdn/{self.versao}/data/pt_BR"
        try:
            itens, feiticos = await asyncio.gather(self._json_dd(f"{base}/item.json"),
                                                   self._json_dd(f"{base}/summoner.json"))
        except Exception as e:
            log.warning("Não consegui baixar itens/feitiços do Data Dragon: %s", e)
            raise RiotErro("Não consegui carregar os itens do jogo agora. Tente de novo daqui a pouco.")

        resultado: dict = {"versao": self.versao}
        for mapa, modo in (("11", "CLASSIC"), ("12", "ARAM")):
            lendarios: dict[str, int] = {}
            botas: dict[str, int] = {}
            for iid, it in itens["data"].items():
                # IDs com 5+ dígitos são cópias de outros modos (Arena, eventos, itens antigos)
                if int(iid) >= 10000:
                    continue
                ouro = it.get("gold", {})
                tags = it.get("tags", [])
                if (not it.get("maps", {}).get(mapa) or not ouro.get("purchasable") or it.get("inStore") is False
                        or it.get("requiredChampion") or it.get("requiredAlly") or it.get("hideFromAll")
                        or "Consumable" in tags or "Trinket" in tags):
                    continue
                if "Boots" in tags:
                    if "1001" in it.get("from", []):  # botas de nível 2 (feitas a partir das Botas)
                        botas.setdefault(it["name"], int(iid))
                elif not it.get("into") and ouro.get("total", 0) >= 2200:  # item lendário (final)
                    lendarios.setdefault(it["name"], int(iid))

            magias = {f["name"]: f["id"] for f in feiticos["data"].values() if modo in f.get("modes", [])}
            if len(lendarios) < 6 or not botas or len(magias) < 2:
                raise RiotErro("Os dados de itens do jogo vieram incompletos. Tente de novo mais tarde.")
            resultado[mapa] = {
                "lendarios": [(i, n) for n, i in lendarios.items()],
                "botas": [(i, n) for n, i in botas.items()],
                "feiticos": [(i, n) for n, i in magias.items()],
            }
            log.info("Ultimate Bravery (mapa %s): %d itens lendários, %d botas, %d feitiços",
                     mapa, len(lendarios), len(botas), len(magias))
        return resultado

    # ------------------------------------------------------------ nomes e imagens
    def nome_campeao(self, key: int) -> str:
        c = self.campeoes.get(int(key or 0))
        return c["nome"] if c else f"Campeão {key}"

    def nome_por_id_interno(self, champion_name: str) -> str:
        key = self.campeao_por_id.get(champion_name)
        return self.campeoes[key]["nome"] if key else champion_name

    def nome_item(self, iid: int) -> str:
        return self.itens.get(int(iid), {}).get("nome", f"Item {iid}")

    def nome_runa(self, rid: int) -> str:
        return self.runas.get(int(rid), {}).get("nome", f"Runa {rid}")

    def nome_feitico(self, fid: int) -> str:
        return self.feiticos.get(int(fid), {}).get("nome", f"Feitiço {fid}")

    def buscar_campeao(self, texto: str) -> int | None:
        if texto.isdigit() and int(texto) in self.campeoes:
            return int(texto)
        alvo = normalizar(texto)
        if not alvo:
            return None
        for regra in (lambda n: n == alvo, lambda n: n.startswith(alvo), lambda n: alvo in n):
            for key, c in self.campeoes.items():
                if regra(normalizar(c["nome"])) or regra(normalizar(c["id"])):
                    return key
        return None

    def sugerir_campeoes(self, texto: str, limite: int = 25) -> list[tuple[int, str]]:
        alvo = normalizar(texto)
        lista = sorted(self.campeoes.items(), key=lambda kv: kv[1]["nome"])
        if alvo:
            comeca = [kv for kv in lista if normalizar(kv[1]["nome"]).startswith(alvo)]
            contem = [kv for kv in lista if alvo in normalizar(kv[1]["nome"]) and kv not in comeca]
            lista = comeca + contem
        return [(k, c["nome"]) for k, c in lista[:limite]]

    def url_icone_perfil(self, icon_id: int) -> str:
        return f"{DD}/cdn/{self.versao}/img/profileicon/{icon_id}.png"

    def url_campeao(self, key: int) -> str | None:
        c = self.campeoes.get(int(key or 0))
        return f"{DD}/cdn/{self.versao}/img/champion/{c['id']}.png" if c else None

    def url_splash(self, key: int) -> str | None:
        c = self.campeoes.get(int(key or 0))
        return f"{DD}/cdn/img/champion/splash/{c['id']}_0.jpg" if c else None

    def url_item(self, iid: int) -> str:
        return f"{DD}/cdn/{self.versao}/img/item/{iid}.png"

    def url_runa(self, rid: int) -> str | None:
        r = self.runas.get(int(rid))
        return f"{DD}/cdn/img/{r['icone']}" if r else None

    def url_feitico(self, fid: int) -> str | None:
        f = self.feiticos.get(int(fid))
        return f"{DD}/cdn/{self.versao}/img/spell/{f['id']}.png" if f else None

    def slug_campeao(self, key: int) -> str:
        c = self.campeoes.get(int(key or 0))
        return c["id"].lower() if c else ""

    async def imagem(self, url: str | None) -> bytes | None:
        """Baixa uma imagem do Data Dragon, guardando em cache (memória e disco)."""
        if not url:
            return None
        if url in self._imagens:
            self._imagens.move_to_end(url)
            return self._imagens[url]
        arquivo = self.pasta_cache / (hashlib.sha1(url.encode()).hexdigest() + ".img")
        dados = None
        if arquivo.exists():
            dados = arquivo.read_bytes()
        else:
            try:
                async with self.session.get(url) as r:
                    if r.status == 200:
                        dados = await r.read()
                        arquivo.write_bytes(dados)
            except Exception as e:
                log.debug("Falha ao baixar %s: %s", url, e)
        if dados:
            self._imagens[url] = dados
            if len(self._imagens) > 100:
                self._imagens.popitem(last=False)
        return dados

    # ------------------------------------------------------------ requisições
    async def _get(self, url: str, params: dict | None = None):
        for tentativa in range(4):
            await self.limitador.esperar()
            async with self.session.get(url, params=params,
                                        headers={"X-Riot-Token": self.chave}) as r:
                if r.status == 200:
                    return await r.json()
                if r.status == 404:
                    raise NaoEncontrado("Não encontrado.")
                if r.status == 429:
                    espera = int(r.headers.get("Retry-After", "5"))
                    log.warning("Limite da Riot atingido, esperando %ss", espera)
                    await asyncio.sleep(espera)
                    continue
                if r.status in (401, 403):
                    raise RiotErro("A chave da Riot é inválida ou expirou. Gere outra no "
                                   "developer.riotgames.com, coloque no arquivo .env e reinicie o bot.")
                if r.status >= 500:
                    await asyncio.sleep(1 + tentativa)
                    continue
                raise RiotErro(f"A API da Riot respondeu com erro {r.status}.")
        raise RiotErro("A API da Riot não está respondendo. Tente de novo daqui a pouco.")

    async def conta(self, riot_id: str) -> dict:
        if "#" not in riot_id:
            raise RiotErro("Use o Riot ID completo, com a TAG. Exemplo: `Faker#KR1`")
        nome, tag = (x.strip() for x in riot_id.rsplit("#", 1))
        if not nome or not tag:
            raise RiotErro("Use o Riot ID completo, com a TAG. Exemplo: `Faker#KR1`")
        try:
            return await self._get(
                f"{self.base_reg}/riot/account/v1/accounts/by-riot-id/{quote(nome)}/{quote(tag)}")
        except NaoEncontrado:
            raise RiotErro(f"Não achei o jogador **{nome}#{tag}**. Confira o nome e a TAG.")

    async def conta_por_puuid(self, puuid: str) -> dict:
        return await self._get(f"{self.base_reg}/riot/account/v1/accounts/by-puuid/{puuid}")

    async def invocador(self, puuid: str) -> dict:
        try:
            return await self._get(f"{self.base_plat}/lol/summoner/v4/summoners/by-puuid/{puuid}")
        except NaoEncontrado:
            raise RiotErro(f"Essa conta não tem perfil de LoL no servidor `{config.PLATFORM}`.")

    async def elo(self, puuid: str) -> list[dict]:
        return await self._get(f"{self.base_plat}/lol/league/v4/entries/by-puuid/{puuid}")

    async def liga_alto_elo(self, tier: str) -> list[dict]:
        nome = {"CHALLENGER": "challengerleagues", "GRANDMASTER": "grandmasterleagues",
                "MASTER": "masterleagues"}[tier]
        dados = await self._get(f"{self.base_plat}/lol/league/v4/{nome}/by-queue/RANKED_SOLO_5x5")
        return dados.get("entries", [])

    async def ids_partidas(self, puuid: str, quantidade: int, fila: int | None = None) -> list[str]:
        params = {"start": 0, "count": quantidade}
        if fila:
            params["queue"] = fila
        return await self._get(f"{self.base_reg}/lol/match/v5/matches/by-puuid/{puuid}/ids", params)

    async def partida(self, match_id: str) -> dict:
        return await self._get(f"{self.base_reg}/lol/match/v5/matches/{match_id}")

    async def maestrias(self, puuid: str, quantidade: int) -> list[dict]:
        return await self._get(
            f"{self.base_plat}/lol/champion-mastery/v4/champion-masteries/by-puuid/{puuid}/top",
            {"count": quantidade})

    async def maestria_campeao(self, puuid: str, champion_id: int) -> dict | None:
        try:
            return await self._get(f"{self.base_plat}/lol/champion-mastery/v4/champion-masteries/"
                                   f"by-puuid/{puuid}/by-champion/{champion_id}")
        except NaoEncontrado:
            return None

    async def partida_ao_vivo(self, puuid: str) -> dict | None:
        try:
            return await self._get(
                f"{self.base_plat}/lol/spectator/v5/active-games/by-summoner/{puuid}")
        except NaoEncontrado:
            return None
