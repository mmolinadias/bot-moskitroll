"""Builds dos campeões vindas do OP.GG (serviço público MCP deles, sem chave).

Não é uma API oficial para bots: se o OP.GG mudar o formato, o /build mostra um erro
amigável e o resto do bot continua funcionando.
"""
import json
import logging
import re
import time
from collections import OrderedDict

import aiohttp

from riot import RiotErro

log = logging.getLogger("bot-lol.opgg")
URL = "https://mcp-api.op.gg/mcp"
CACHE_HORAS = 6
CACHE_MAX = 40
ROTAS_OPGG = {"top": "Topo", "jungle": "Selva", "mid": "Meio", "adc": "Atirador", "support": "Suporte"}
MODOS_OPGG = {"ranked": "Solo/Duo", "flex": "Flex", "aram": "ARAM"}
# Sem filtro, o OP.GG usa Esmeralda+ nas ranqueadas e todos os elos no ARAM.
ELOS_OPGG = {
    "all": "Todos os elos", "gold_plus": "Ouro+", "platinum_plus": "Platina+", "emerald_plus": "Esmeralda+",
    "diamond_plus": "Diamante+", "master_plus": "Mestre+",
    "iron": "Ferro", "bronze": "Bronze", "silver": "Prata", "gold": "Ouro", "platinum": "Platina",
    "emerald": "Esmeralda", "diamond": "Diamante", "master": "Mestre", "grandmaster": "Grão-Mestre",
    "challenger": "Desafiante",
}
CAMPOS = [
    "data.summary.positions[].name",
    "data.summary.average_stats.{play,win_rate,tier}",
    "data.starter_items.{ids_names[]}",
    "data.boots.{ids_names[]}",
    "data.core_items.{ids_names[],pick_rate,win,play}",
    "data.fourth_items[].{ids_names[]}",
    "data.fifth_items[].{ids_names[]}",
    "data.sixth_items[].{ids_names[]}",
    "data.summoner_spells.{ids[]}",
    "data.runes.{primary_page_name,primary_rune_names[],secondary_page_name,secondary_rune_names[]}",
    "data.skill_masteries.{ids[]}",
]
ERRO = "Não consegui pegar a build no OP.GG agora. Tente de novo daqui a pouco."


class FormatoInvalido(Exception):
    pass


# ---------------------------------------------------------------- leitura da resposta
def ler_resposta(texto: str):
    """O OP.GG responde num formato próprio, por exemplo:
        class Runes: primary_page_name,play
        Data(Runes("Dominação",123))
    Esta função transforma isso em dicionários: {"primary_page_name": "Dominação", "play": 123}."""
    classes: dict[str, list[str]] = {}
    corpo = ""
    for linha in texto.splitlines():
        linha = linha.strip()
        if linha.startswith("class ") and ":" in linha:
            nome, campos = linha[6:].split(":", 1)
            classes[nome.strip()] = [c.strip() for c in campos.split(",") if c.strip()]
        elif linha:
            corpo = linha
    if not corpo:
        raise FormatoInvalido("resposta vazia")
    valor, fim = _ler_valor(corpo, 0, classes)
    if corpo[fim:].strip():
        raise FormatoInvalido("sobrou texto no fim")
    return valor


_NUMERO = re.compile(r"-?\d+(\.\d+)?([eE][-+]?\d+)?")
_NOME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _ler_valor(s: str, i: int, classes: dict):
    while i < len(s) and s[i] == " ":
        i += 1
    if i >= len(s):
        raise FormatoInvalido("fim inesperado")
    c = s[i]
    if c == '"':
        j = i + 1
        while j < len(s):
            if s[j] == "\\":
                j += 2
                continue
            if s[j] == '"':
                return json.loads(s[i:j + 1]), j + 1
            j += 1
        raise FormatoInvalido("texto sem fim")
    if c == "[":
        itens, i = _ler_lista(s, i + 1, "]", classes)
        return itens, i
    m = _NUMERO.match(s, i)
    if m:
        txt = m.group(0)
        return (float(txt) if m.group(1) or m.group(2) else int(txt)), m.end()
    m = _NOME.match(s, i)
    if m:
        nome = m.group(0)
        if nome in ("true", "false", "null"):
            return {"true": True, "false": False, "null": None}[nome], m.end()
        if m.end() < len(s) and s[m.end()] == "(":
            args, j = _ler_lista(s, m.end() + 1, ")", classes)
            campos = classes.get(nome)
            if campos is None:
                return args, j
            return dict(zip(campos, args)), j
    raise FormatoInvalido(f"não entendi o trecho: {s[i:i + 20]!r}")


def _ler_lista(s: str, i: int, fecha: str, classes: dict):
    itens = []
    while True:
        while i < len(s) and s[i] == " ":
            i += 1
        if i < len(s) and s[i] == fecha:
            return itens, i + 1
        valor, i = _ler_valor(s, i, classes)
        itens.append(valor)
        while i < len(s) and s[i] == " ":
            i += 1
        if i < len(s) and s[i] == ",":
            i += 1
        elif i < len(s) and s[i] == fecha:
            return itens, i + 1
        else:
            raise FormatoInvalido("lista mal formada")


def nome_opgg(id_riot: str) -> str:
    """'MissFortune' -> 'MISS_FORTUNE' (formato que o OP.GG pede)."""
    return re.sub(r"(?<=[a-z])(?=[A-Z])", "_", id_riot).upper()


# ---------------------------------------------------------------- cliente
class OPGG:
    def __init__(self, riot):
        self.riot = riot  # reaproveita a sessão HTTP do riot.py
        self._sessao: str | None = None
        self._id = 0
        self._cache: OrderedDict[tuple, tuple[float, dict]] = OrderedDict()
        self._rota_principal: dict[str, str] = {}

    async def _post(self, corpo: dict) -> tuple[dict | None, str | None]:
        cab = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if self._sessao:
            cab["Mcp-Session-Id"] = self._sessao
        async with self.riot.session.post(URL, json=corpo, headers=cab,
                                          timeout=aiohttp.ClientTimeout(total=25)) as r:
            if r.status in (400, 404) and self._sessao:
                raise ConnectionResetError("sessão do OP.GG expirou")
            if r.status >= 400:
                raise RiotErro(ERRO)
            texto = await r.text()
            sessao = r.headers.get("Mcp-Session-Id")
        if not texto.strip():
            return None, sessao
        if "data:" in texto[:200]:  # resposta em formato de evento (SSE)
            texto = "\n".join(l[5:].strip() for l in texto.splitlines() if l.startswith("data:"))
        return json.loads(texto), sessao

    async def _iniciar(self):
        self._sessao = None
        self._id += 1
        resp, sessao = await self._post({
            "jsonrpc": "2.0", "id": self._id, "method": "initialize",
            "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                       "clientInfo": {"name": "bot-lol-discord", "version": "1.0"}}})
        if not resp or "result" not in resp:
            raise RiotErro(ERRO)
        self._sessao = sessao
        await self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})

    async def _ferramenta(self, nome: str, argumentos: dict) -> str:
        for tentativa in range(2):
            try:
                if not self._sessao:
                    await self._iniciar()
                self._id += 1
                resp, _ = await self._post({"jsonrpc": "2.0", "id": self._id, "method": "tools/call",
                                            "params": {"name": nome, "arguments": argumentos}})
                resultado = (resp or {}).get("result") or {}
                if resp and "error" in resp and tentativa == 0:
                    raise ConnectionResetError(str(resp["error"]))
                if resultado.get("isError") or not resultado.get("content"):
                    raise RiotErro(ERRO)
                return resultado["content"][0].get("text", "")
            except ConnectionResetError as e:
                log.info("Reconectando ao OP.GG: %s", e)
                self._sessao = None
            except (aiohttp.ClientError, TimeoutError, json.JSONDecodeError) as e:
                log.warning("OP.GG falhou: %s", e)
                raise RiotErro(ERRO)
        raise RiotErro(ERRO)

    async def _analise(self, campeao: str, rota: str, modo: str, elo: str | None) -> dict:
        argumentos = {"champion": campeao, "position": rota, "game_mode": modo, "lang": "pt_BR",
                      "desired_output_fields": CAMPOS}
        if elo:
            argumentos["tier"] = elo
        texto = await self._ferramenta("lol_get_champion_analysis", argumentos)
        try:
            dados = ler_resposta(texto)
        except FormatoInvalido as e:
            log.warning("Formato do OP.GG mudou (%s): %s", e, texto[:300])
            raise RiotErro("O OP.GG mudou o formato das builds e o bot ainda não entende o novo. "
                           "Use o botão do OP.GG enquanto isso.")
        if not isinstance(dados, dict) or not isinstance(dados.get("data"), dict):
            raise RiotErro(ERRO)
        return dados["data"]

    async def build(self, id_riot: str, rota: str | None, modo: str, elo: str | None = None) -> dict:
        """Build mais usada. rota: top/jungle/mid/adc/support ou None (= rota principal).
        modo: 'ranked', 'flex' ou 'aram' (no ARAM a rota não importa).
        elo: uma chave de ELOS_OPGG ou None (= padrão do OP.GG)."""
        campeao = nome_opgg(id_riot)
        if modo == "aram":
            rota = "mid"
        pedida = rota or self._rota_principal.get(campeao, "mid")
        chave = (campeao, pedida, modo, elo)
        guardado = self._cache.get(chave)
        if guardado and time.time() - guardado[0] < CACHE_HORAS * 3600:
            self._cache.move_to_end(chave)
            return guardado[1]

        d = await self._analise(campeao, pedida, modo, elo)
        if modo != "aram":
            rotas = [p.get("name", "").lower() for p in (d.get("summary") or {}).get("positions") or []
                     if isinstance(p, dict)]
            rotas = [r for r in rotas if r in ROTAS_OPGG]
            if rotas:
                self._rota_principal[campeao] = rotas[0]
            if rota is None and rotas and rotas[0] != pedida:  # adivinhou errado: pede a rota principal
                pedida = rotas[0]
                d = await self._analise(campeao, pedida, modo, elo)
            elif rota is not None and rotas and rota not in rotas:
                raise RiotErro(f"Quase ninguém joga com esse campeão nessa rota. Rotas comuns: "
                               f"{', '.join(ROTAS_OPGG[r] for r in rotas)}.")

        build = _resumir(d, pedida, modo)
        build["elo"] = elo
        if not build["itens"] and not build["runas"]:
            raise RiotErro("O OP.GG ainda não tem dados suficientes desse campeão nesse filtro.")
        self._cache[(campeao, pedida, modo, elo)] = (time.time(), build)
        if rota is None:
            self._cache[chave] = (time.time(), build)
        while len(self._cache) > CACHE_MAX:
            self._cache.popitem(last=False)
        return build


def _nomes(bloco) -> list[str]:
    if isinstance(bloco, dict):
        return [str(n) for n in bloco.get("ids_names") or [] if isinstance(n, str)]
    return []


def _resumir(d: dict, rota: str, modo: str) -> dict:
    stats = (d.get("summary") or {}).get("average_stats") or {}
    principais = _nomes(d.get("core_items"))
    opcoes: list[str] = []
    for chave in ("fourth_items", "fifth_items", "sixth_items"):
        for bloco in (d.get(chave) or [])[:3]:
            for nome in _nomes(bloco):
                if nome not in principais and nome not in opcoes:
                    opcoes.append(nome)
    runas = d.get("runes") or {}
    nucleo = d.get("core_items") or {}
    return {
        "rota": rota,
        "modo": modo,
        "partidas": stats.get("play"),
        "winrate": stats.get("win_rate"),
        "tier": stats.get("tier"),
        "iniciais": _nomes(d.get("starter_items")),
        "botas": (_nomes(d.get("boots")) or [None])[0],
        "itens": principais,
        "itens_wr": (nucleo.get("win") / nucleo["play"]) if nucleo.get("play") and nucleo.get("win") else None,
        "opcoes": opcoes[:6],
        "feiticos": [i for i in (d.get("summoner_spells") or {}).get("ids") or [] if isinstance(i, int)],
        "runas": {
            "primaria": runas.get("primary_page_name"),
            "primarias": [r for r in runas.get("primary_rune_names") or [] if isinstance(r, str)],
            "secundaria": runas.get("secondary_page_name"),
            "secundarias": [r for r in runas.get("secondary_rune_names") or [] if isinstance(r, str)],
        } if runas.get("primary_page_name") else None,
        "habilidades": [h for h in (d.get("skill_masteries") or {}).get("ids") or [] if isinstance(h, str)],
    }
