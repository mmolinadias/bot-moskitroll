"""
Coleta partidas ranqueadas de jogadores Mestre+ (Mestre, Grão-Mestre e Desafiante) de várias
regiões e calcula as builds mais usadas por campeão e rota, para o /build.

Limite da chave da Riot: 20 pedidos por segundo e 100 a cada 2 minutos, contados separadamente
em cada região. Por isso:
- KR e EUW usam um limitador próprio, um pouco abaixo do limite.
- BR divide o limite com os alertas do bot. A coleta só usa o BR quando os alertas gastaram pouco
  e nunca passa de metade do limite de 2 minutos.

A coleta também tem um ritmo máximo (COLETA_PARTIDAS_HORA por região) para não gastar
internet à toa: cada partida com a linha do tempo baixa cerca de 85 KB (medido num jogo do KR).

Guarda só os totais (nada de partidas inteiras) em builds.json, mantendo os 2 patches mais novos.
"""
import asyncio
import json
import logging
import random
import time
from collections import Counter, deque
from pathlib import Path

import config
from riot import Limitador, NaoEncontrado, RiotAPI, RiotErro

log = logging.getLogger("bot-lol.coleta")

# região -> (servidor da liga, roteamento das partidas, nome curto)
REGIOES = {
    "kr": ("kr", "asia", "KR"),
    "euw": ("euw1", "europe", "EUW"),
    "br": ("br1", "americas", "BR"),
}
FILAS = {420: "RANKED_SOLO_5x5", 440: "RANKED_FLEX_SR"}
NOMES_FILAS = {420: "Solo/Duo", 440: "Flex"}
LIGAS = ("challengerleagues", "grandmasterleagues", "masterleagues")
ROTAS = {"TOP": "Topo", "JUNGLE": "Selva", "MIDDLE": "Meio", "BOTTOM": "Atirador", "UTILITY": "Suporte"}

DURACAO_MINIMA = 15 * 60       # ignora remakes e rendições muito cedo
INICIAIS_ATE_MS = 90_000       # compras até 1:30 contam como itens iniciais
MINIMO_JOGOS = 20              # menos que isso não mostra build
MINIMO_CONFRONTO = 8          # partidas contra um campeão para entrar no /counter
MAX_VISTAS = 300_000           # partidas já contadas (para não contar duas vezes)
ATUALIZAR_JOGADORES_H = 6
SALVAR_MIN = 5
PARTE_BR = 0.5                 # no BR, a coleta só usa até metade do limite de 2 minutos


def _patch(versao: str) -> str:
    return ".".join(versao.split(".")[:2])


def _ordem_patch(patch: str) -> tuple:
    try:
        return tuple(int(x) for x in patch.split("."))
    except ValueError:
        return (0,)


def _somar(d: dict, chave: str, vitoria: int):
    v = d.get(chave)
    if v is None:
        d[chave] = [1, vitoria]
    else:
        v[0] += 1
        v[1] += vitoria


def _mais_usado(d: dict) -> tuple[str, list] | tuple[None, None]:
    if not d:
        return None, None
    chave = max(d, key=lambda k: d[k][0])
    return chave, d[chave]


class Coleta:
    def __init__(self, riot: RiotAPI, caminho: Path):
        self.riot = riot
        self.caminho = caminho
        self.dados: dict = {"versao": 2, "patches": {}, "vistas": []}
        self._carregar()
        self._vistas_fila: deque[str] = deque(self.dados.pop("vistas", []), maxlen=MAX_VISTAS)
        self._vistas: set[str] = set(self._vistas_fila)
        self.itens: dict[int, dict] = {}     # id -> {"nome", "tipo": lendario/botas/outro/sentinela}
        self.runas: dict[int, str] = {}      # id da runa ou da árvore -> nome
        self._versao_itens = ""
        self._mudou = False
        self._tarefas: list[asyncio.Task] = []
        self.ao_patch_novo = None  # função async(patch) chamada quando aparece um patch mais novo

    # ------------------------------------------------------------ arquivo
    def _carregar(self):
        if not self.caminho.exists():
            return
        try:
            d = json.loads(self.caminho.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            log.warning("builds.json corrompido, começando do zero")
            return
        if d.get("versao") == 2:
            self.dados = d
        else:
            log.info("builds.json de uma versão antiga do bot, começando do zero")

    def salvar(self):
        if not self._mudou:
            return
        self._enxugar()
        dados = dict(self.dados, vistas=list(self._vistas_fila))
        tmp = self.caminho.with_suffix(".tmp")
        tmp.write_text(json.dumps(dados, separators=(",", ":")), encoding="utf-8")
        tmp.replace(self.caminho)
        self._mudou = False

    def _enxugar(self):
        """Corta as combinações raras para o arquivo e a memória não crescerem sem parar."""
        for patch in self.dados["patches"].values():
            for fila in patch["filas"].values():
                for c in fila.values():
                    for nome in ("runas", "feiticos", "iniciais", "botas", "core", "opcoes", "ordem", "inicio"):
                        d = c[nome]
                        if len(d) > 60:
                            manter = sorted(d.items(), key=lambda kv: kv[1][0], reverse=True)[:30]
                            c[nome] = dict(manter)
                    contra = c.get("contra", {})
                    if len(contra) > 120:  # confrontos: guarda os 80 mais comuns
                        c["contra"] = dict(sorted(contra.items(), key=lambda kv: kv[1][0], reverse=True)[:80])

    # ------------------------------------------------------------ ciclo de vida
    def iniciar(self):
        regioes = [r for r in config.COLETA_REGIOES if r in REGIOES]
        if not regioes:
            log.warning("Nenhuma região válida em COLETA_REGIOES; a coleta de builds ficou desligada")
            return
        self._tarefas.append(asyncio.create_task(self._loop_salvar()))
        for regiao in regioes:
            self._tarefas.append(asyncio.create_task(self._loop_regiao(regiao)))
        log.info("Coleta de builds Mestre+ ligada: %s", ", ".join(REGIOES[r][2] for r in regioes))

    def parar(self):
        for t in self._tarefas:
            t.cancel()
        self.salvar()

    async def _loop_salvar(self):
        while True:
            await asyncio.sleep(SALVAR_MIN * 60)
            try:
                self.salvar()
            except Exception:
                log.exception("Erro ao salvar builds.json")

    # ------------------------------------------------------------ dados do jogo (Data Dragon)
    async def carregar_itens(self):
        """Itens e runas em português. Recarrega quando sai versão nova do Data Dragon."""
        if self._versao_itens == self.riot.versao and self.itens:
            return
        base = f"/cdn/{self.riot.versao}/data/pt_BR"
        itens, runas = await asyncio.gather(self.riot._json_dd(f"{base}/item.json"),
                                            self.riot._json_dd(f"{base}/runesReforged.json"))
        novos: dict[int, dict] = {}
        for iid, it in itens["data"].items():
            tags = it.get("tags", [])
            ouro = it.get("gold", {})
            if "Trinket" in tags:
                tipo = "sentinela"
            elif "Boots" in tags and "1001" in it.get("from", []):
                tipo = "botas"
            elif (not it.get("into") and "Boots" not in tags and "Consumable" not in tags
                  and ouro.get("purchasable") and ouro.get("total", 0) >= 2000):
                tipo = "lendario"
            else:
                tipo = "outro"
            novos[int(iid)] = {"nome": it["name"], "tipo": tipo}
        nomes_runas: dict[int, str] = {}
        for arvore in runas:
            nomes_runas[arvore["id"]] = arvore["name"]
            for fileira in arvore["slots"]:
                for r in fileira["runes"]:
                    nomes_runas[r["id"]] = r["name"]
        self.itens, self.runas, self._versao_itens = novos, nomes_runas, self.riot.versao
        log.info("Coleta: %d itens e %d runas carregados (versão %s)", len(novos), len(nomes_runas),
                 self.riot.versao)

    # ------------------------------------------------------------ coleta por região
    async def _loop_regiao(self, regiao: str):
        plataforma, roteamento, sigla = REGIOES[regiao]
        base_plat = f"https://{plataforma}.api.riotgames.com"
        base_reg = f"https://{roteamento}.api.riotgames.com"
        if regiao == "br":
            limitador = None  # usa o limitador principal, dividido com os alertas
        else:
            limitador = Limitador([(max(1, config.LIMITE_SEG - 2), 1), (max(1, config.LIMITE_2MIN - 5), 120)])
        ultimo_check: dict[str, int] = {}
        intervalo = 3600 / max(1, config.COLETA_PARTIDAS_HORA)  # segundos entre uma partida e outra
        proxima = [0.0]

        async def no_ritmo():
            espera = proxima[0] - time.monotonic()
            if espera > 0:
                await asyncio.sleep(espera)
            proxima[0] = max(proxima[0], time.monotonic() - intervalo) + intervalo

        jogadores: list[tuple[str, int]] = []
        atualizado = 0.0

        async def pedir(url: str, params: dict | None = None):
            if limitador is None:
                teto = int(config.LIMITE_2MIN * PARTE_BR)
                while self.riot.limitador.uso(120) >= teto:
                    await asyncio.sleep(5)
            return await self.riot._get(url, params, limitador)

        await asyncio.sleep(30)  # deixa o bot terminar de ligar antes
        while True:
            try:
                if not jogadores or time.time() - atualizado > ATUALIZAR_JOGADORES_H * 3600:
                    await self._atualizar_versao()
                    jogadores = await self._buscar_jogadores(pedir, base_plat)
                    random.shuffle(jogadores)
                    atualizado = time.time()
                    log.info("Coleta %s: %d jogadores Mestre+ na fila", sigla, len(jogadores))
                    if not jogadores:
                        await asyncio.sleep(600)
                        continue
                await self._carregar_itens_seguro()
                for puuid, fila in list(jogadores):
                    if time.time() - atualizado > ATUALIZAR_JOGADORES_H * 3600:
                        break
                    await self._jogador(pedir, no_ritmo, base_reg, sigla, puuid, fila, ultimo_check)
            except asyncio.CancelledError:
                raise
            except RiotErro as e:
                log.warning("Coleta %s: %s (tentando de novo em 2 min)", sigla, e)
                await asyncio.sleep(120)
            except Exception:
                log.exception("Coleta %s: erro inesperado (tentando de novo em 2 min)", sigla)
                await asyncio.sleep(120)

    async def _atualizar_versao(self):
        try:
            versao = (await self.riot._json_dd("/api/versions.json"))[0]
        except Exception:
            return
        if versao != self.riot.versao:
            log.info("Versão nova do jogo: %s", versao)
            await self.riot.carregar_estaticos()

    async def _carregar_itens_seguro(self):
        while True:
            try:
                await self.carregar_itens()
                return
            except Exception as e:
                log.warning("Coleta: não consegui baixar itens/runas (%s); tentando em 5 min", e)
                await asyncio.sleep(300)

    async def _buscar_jogadores(self, pedir, base_plat: str) -> list[tuple[str, int]]:
        jogadores: dict[tuple[str, int], None] = {}
        for fila, nome_fila in FILAS.items():
            for liga in LIGAS:
                try:
                    d = await pedir(f"{base_plat}/lol/league/v4/{liga}/by-queue/{nome_fila}")
                except NaoEncontrado:
                    continue
                for e in d.get("entries", []):
                    if e.get("puuid"):
                        jogadores[(e["puuid"], fila)] = None
        return list(jogadores)

    async def _jogador(self, pedir, no_ritmo, base_reg: str, sigla: str, puuid: str, fila: int,
                       ultimo_check: dict[str, int]):
        chave = f"{puuid}:{fila}"
        agora = int(time.time())
        inicio = ultimo_check.get(chave, agora - 3 * 86400)
        try:
            ids = await pedir(f"{base_reg}/lol/match/v5/matches/by-puuid/{puuid}/ids",
                              {"queue": fila, "startTime": inicio, "count": 20})
        except NaoEncontrado:
            return
        ultimo_check[chave] = agora
        for match_id in ids:
            if match_id in self._vistas:
                continue
            await no_ritmo()
            self._marcar_vista(match_id)
            try:
                partida = await pedir(f"{base_reg}/lol/match/v5/matches/{match_id}")
            except NaoEncontrado:
                continue
            info = partida.get("info", {})
            if (info.get("queueId") not in FILAS or info.get("gameDuration", 0) < DURACAO_MINIMA
                    or not self._patch_aceito(_patch(info.get("gameVersion", "0.0")))):
                continue
            try:
                linha = await pedir(f"{base_reg}/lol/match/v5/matches/{match_id}/timeline")
            except NaoEncontrado:
                continue
            self.registrar(partida, linha, sigla)

    def _marcar_vista(self, match_id: str):
        if len(self._vistas_fila) == self._vistas_fila.maxlen:
            self._vistas.discard(self._vistas_fila[0])
        self._vistas_fila.append(match_id)
        self._vistas.add(match_id)
        self._mudou = True

    # ------------------------------------------------------------ contagem
    def _patch_aceito(self, patch: str) -> bool:
        patches = sorted(self.dados["patches"], key=_ordem_patch)
        return len(patches) < 2 or _ordem_patch(patch) >= _ordem_patch(patches[-2])

    def _balde(self, patch: str) -> dict | None:
        patches = self.dados["patches"]
        if patch not in patches:
            if not self._patch_aceito(patch):
                return None
            anteriores = list(patches)
            patches[patch] = {"filas": {}, "partidas": {}}
            if anteriores and _ordem_patch(patch) > max(_ordem_patch(x) for x in anteriores) and self.ao_patch_novo:
                asyncio.get_running_loop().create_task(self.ao_patch_novo(patch))
            for velho in sorted(patches, key=_ordem_patch)[:-2]:
                del patches[velho]
                log.info("Patch %s saiu das builds", velho)
            if patch not in patches:
                return None
            log.info("Patch novo nas builds: %s", patch)
        return patches[patch]

    def registrar(self, partida: dict, linha: dict, sigla: str):
        info = partida["info"]
        balde = self._balde(_patch(info.get("gameVersion", "0.0")))
        if balde is None:
            return
        fila = str(info["queueId"])
        contagem = balde["partidas"].setdefault(fila, {})
        contagem[sigla] = contagem.get(sigla, 0) + 1
        por_fila = balde["filas"].setdefault(fila, {})

        compras: dict[int, list[tuple[int, int]]] = {}
        habilidades: dict[int, list[int]] = {}
        for quadro in linha.get("info", {}).get("frames", []):
            for ev in quadro.get("events", []):
                tipo, pid = ev.get("type"), ev.get("participantId")
                if tipo == "ITEM_PURCHASED":
                    compras.setdefault(pid, []).append((ev.get("timestamp", 0), ev.get("itemId", 0)))
                elif tipo == "ITEM_UNDO" and ev.get("beforeId"):
                    lista = compras.get(pid, [])
                    for i in range(len(lista) - 1, -1, -1):
                        if lista[i][1] == ev["beforeId"]:
                            del lista[i]
                            break
                elif tipo == "SKILL_LEVEL_UP" and ev.get("levelUpType") == "NORMAL":
                    habilidades.setdefault(pid, []).append(ev.get("skillSlot", 0))

        oponentes = {(p.get("teamId"), p.get("teamPosition")): p["championId"] for p in info["participants"]}
        for p in info["participants"]:
            rota = p.get("teamPosition")
            if rota not in ROTAS:
                continue
            v = 1 if p.get("win") else 0
            c = por_fila.setdefault(f"{p['championId']}:{rota}", {
                "jogos": 0, "vitorias": 0, "runas": {}, "feiticos": {}, "iniciais": {}, "botas": {},
                "core": {}, "opcoes": {}, "ordem": {}, "inicio": {}})
            c["jogos"] += 1
            c["vitorias"] += v
            inimigo = oponentes.get((300 - p.get("teamId", 0), rota))  # times são 100 e 200
            if inimigo:
                _somar(c.setdefault("contra", {}), str(inimigo), v)

            estilos = (p.get("perks") or {}).get("styles") or []
            if len(estilos) == 2:
                pagina = "|".join(f"{e['style']}:" + ",".join(str(s["perk"]) for s in e.get("selections", []))
                                  for e in estilos)
                _somar(c["runas"], pagina, v)
            _somar(c["feiticos"], ",".join(sorted(str(p.get(f"summoner{i}Id", 0)) for i in (1, 2))), v)

            pid = p.get("participantId")
            lista = compras.get(pid, [])
            iniciais = sorted(i for t, i in lista if t <= INICIAIS_ATE_MS
                              and self.itens.get(i, {}).get("tipo") != "sentinela")
            if iniciais:
                _somar(c["iniciais"], ",".join(map(str, iniciais)), v)
            botas = next((i for _, i in lista if self.itens.get(i, {}).get("tipo") == "botas"), 0)
            _somar(c["botas"], str(botas), v)
            lendarios: list[int] = []
            for _, i in lista:
                if self.itens.get(i, {}).get("tipo") == "lendario" and i not in lendarios:
                    lendarios.append(i)
            if len(lendarios) >= 3:
                _somar(c["core"], ",".join(map(str, lendarios[:3])), v)
            for i in lendarios[3:6]:
                _somar(c["opcoes"], str(i), v)

            pontos = habilidades.get(pid, [])
            if len(pontos) >= 3:
                letras = {1: "Q", 2: "W", 3: "E", 4: "R"}
                _somar(c["inicio"], "".join(letras.get(s, "?") for s in pontos[:3]), v)
                nivel = Counter()
                ordem: list[str] = []
                for s in pontos:
                    if s in (1, 2, 3):
                        nivel[s] += 1
                        if nivel[s] == 5:
                            ordem.append(letras[s])
                for s, _ in nivel.most_common():  # quem não chegou no 5: pela quantidade de pontos
                    if letras[s] not in ordem:
                        ordem.append(letras[s])
                if len(ordem) == 3:
                    _somar(c["ordem"], "".join(ordem), v)
        self._mudou = True

    # ------------------------------------------------------------ consulta (/build)
    def total_partidas(self, fila: int) -> int:
        return sum(sum(p["partidas"].get(str(fila), {}).values()) for p in self.dados["patches"].values())

    def build(self, champ: int, rota: str | None, fila: int) -> dict:
        patches = sorted(self.dados["patches"], key=_ordem_patch, reverse=True)
        if not patches or not self.total_partidas(fila):
            raise RiotErro("Ainda estou juntando partidas do alto elo (a coleta começou há pouco). "
                           "Tente de novo daqui a algumas horas.")
        nome = self.riot.nome_campeao(champ)

        def rotas_do_patch(patch: str) -> dict[str, dict]:
            por_fila = self.dados["patches"][patch]["filas"].get(str(fila), {})
            return {r: por_fila[f"{champ}:{r}"] for r in ROTAS if f"{champ}:{r}" in por_fila}

        escolha = None
        for patch in patches:
            rotas = rotas_do_patch(patch)
            if rota is None and rotas:
                r = max(rotas, key=lambda k: rotas[k]["jogos"])
            else:
                r = rota
            if r in rotas and rotas[r]["jogos"] >= MINIMO_JOGOS:
                escolha = (patch, r, rotas[r])
                break
        if escolha is None:
            onde = f" de {ROTAS[rota]}" if rota else ""
            raise RiotErro(f"Ainda não tenho partidas suficientes de **{nome}**{onde} no "
                           f"{NOMES_FILAS[fila]} Mestre+. Tente outra rota ou mais tarde.")
        patch, r, c = escolha

        def nome_item(i) -> str:
            return self.itens.get(int(i), {}).get("nome", f"Item {i}")

        runas = None
        pagina, _ = _mais_usado(c["runas"])
        if pagina:
            (prim, prims), (sec, secs) = (parte.split(":") for parte in pagina.split("|"))
            runas = {
                "primaria": self.runas.get(int(prim), prim),
                "primarias": [self.runas.get(int(x), x) for x in prims.split(",") if x],
                "secundaria": self.runas.get(int(sec), sec),
                "secundarias": [self.runas.get(int(x), x) for x in secs.split(",") if x],
            }
        feiticos, _ = _mais_usado(c["feiticos"])
        iniciais, _ = _mais_usado(c["iniciais"])
        botas, _ = _mais_usado(c["botas"])
        core, core_jv = _mais_usado(c["core"])
        opcoes = [nome_item(i) for i, _ in sorted(c["opcoes"].items(), key=lambda kv: kv[1][0], reverse=True)
                  if not core or i not in core.split(",")][:6]
        ordem, _ = _mais_usado(c["ordem"])
        inicio, _ = _mais_usado(c["inicio"])
        return {
            "rota": r,
            "patch": patch,
            "partidas": c["jogos"],
            "winrate": c["vitorias"] / c["jogos"] if c["jogos"] else None,
            "regioes": self.dados["patches"][patch]["partidas"].get(str(fila), {}),
            "runas": runas,
            "feiticos": [int(x) for x in feiticos.split(",")] if feiticos else [],
            "iniciais": [nome_item(i) for i in iniciais.split(",")] if iniciais else [],
            "botas": nome_item(botas) if botas and botas != "0" else None,
            "itens": [nome_item(i) for i in core.split(",")] if core else [],
            "itens_wr": core_jv[1] / core_jv[0] if core_jv else None,
            "opcoes": opcoes,
            "ordem": list(ordem) if ordem else [],
            "inicio": list(inicio) if inicio else [],
        }

    def _patch_principal(self, fila: int) -> str | None:
        """O patch mais novo que já tem partidas suficientes (senão, o que tiver mais)."""
        patches = sorted(self.dados["patches"], key=_ordem_patch, reverse=True)
        total = {pt: sum(self.dados["patches"][pt]["partidas"].get(str(fila), {}).values()) for pt in patches}
        for pt in patches:
            if total[pt] >= 1000:
                return pt
        return max(patches, key=lambda pt: total[pt]) if patches and any(total.values()) else None

    def tierlist(self, rota: str, fila: int) -> dict:
        """Campeões da rota com a taxa de vitória ajustada (puxada para 50% quando há poucas partidas)."""
        patch = self._patch_principal(fila)
        if not patch:
            raise RiotErro("Ainda estou juntando partidas do alto elo. Tente de novo daqui a algumas horas.")
        partidas = sum(self.dados["patches"][patch]["partidas"].get(str(fila), {}).values())
        por_fila = self.dados["patches"][patch]["filas"].get(str(fila), {})
        minimo = max(MINIMO_JOGOS, int(partidas * 0.005))
        lista = []
        for chave, c in por_fila.items():
            champ, r = chave.split(":")
            if r != rota or c["jogos"] < minimo:
                continue
            ajustada = (c["vitorias"] + 25) / (c["jogos"] + 50)
            lista.append({"campeao": int(champ), "winrate": c["vitorias"] / c["jogos"], "ajustada": ajustada,
                          "jogos": c["jogos"], "pickrate": c["jogos"] / partidas})
        if len(lista) < 5:
            raise RiotErro(f"Ainda não tenho partidas suficientes de {ROTAS[rota]} no {NOMES_FILAS[fila]} Mestre+.")
        lista.sort(key=lambda x: x["ajustada"], reverse=True)
        return {"patch": patch, "partidas": partidas, "campeoes": lista}

    def counters(self, champ: int, rota: str | None, fila: int) -> dict:
        """Contra quem o campeão mais ganha e perde na rota (somando os 2 patches guardados)."""
        nome = self.riot.nome_campeao(champ)
        jogos_rota: Counter = Counter()
        contra: dict[str, list] = {}
        for patch in self.dados["patches"].values():
            por_fila = patch["filas"].get(str(fila), {})
            for r in ROTAS:
                c = por_fila.get(f"{champ}:{r}")
                if c:
                    jogos_rota[r] += c["jogos"]
        if not jogos_rota:
            raise RiotErro(f"Ainda não tenho partidas de **{nome}** no {NOMES_FILAS[fila]} Mestre+.")
        r = rota or jogos_rota.most_common(1)[0][0]
        for patch in self.dados["patches"].values():
            c = patch["filas"].get(str(fila), {}).get(f"{champ}:{r}")
            for inimigo, (j, v) in (c or {}).get("contra", {}).items():
                soma = contra.setdefault(inimigo, [0, 0])
                soma[0] += j
                soma[1] += v
        lista = [{"campeao": int(i), "jogos": j, "winrate": v / j} for i, (j, v) in contra.items()
                 if j >= MINIMO_CONFRONTO]
        if len(lista) < 4:
            raise RiotErro(f"Ainda não tenho confrontos suficientes de **{nome}** ({ROTAS[r]}). "
                           "Os confrontos começam a ser contados agora; tente de novo daqui a um ou dois dias.")
        lista.sort(key=lambda x: x["winrate"], reverse=True)
        return {"rota": r, "jogos": jogos_rota[r], "confrontos": lista}
