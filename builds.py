"""
Coleta partidas ranqueadas do alto elo (Desafiante e Grão-Mestre) aos poucos,
respeitando o limite da chave, e calcula as builds mais usadas por campeão e rota.
"""
import json
import logging
import random
import time
from pathlib import Path

import config
from riot import NaoEncontrado, RiotAPI, RiotErro

log = logging.getLogger("bot-lol.builds")
ROTAS = ("TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY")
MINIMO_JOGOS = 3


def _somar(d: dict, chave: str, vitoria: int):
    v = d.setdefault(chave, [0, 0])
    v[0] += 1
    v[1] += vitoria


class Builds:
    def __init__(self, riot: RiotAPI, caminho: Path):
        self.riot = riot
        self.caminho = caminho
        self.dados = {"vistas": [], "campeoes": {}}
        if caminho.exists():
            try:
                self.dados = json.loads(caminho.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                log.warning("builds.json corrompido, começando do zero")
        self._vistas = set(self.dados["vistas"])
        self._fila_jogadores: list[str] = []
        self._fila_atualizada = 0.0
        self._mudou = False

    def salvar(self):
        if not self._mudou:
            return
        self.dados["vistas"] = self.dados["vistas"][-30000:]
        self._vistas = set(self.dados["vistas"])
        tmp = self.caminho.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.dados, separators=(",", ":")), encoding="utf-8")
        tmp.replace(self.caminho)
        self._mudou = False

    def total_partidas(self) -> int:
        return len(self.dados["vistas"])

    # ------------------------------------------------------------ coleta
    def registrar_partida(self, partida: dict) -> bool:
        match_id = partida["metadata"]["matchId"]
        if match_id in self._vistas:
            return False
        self._vistas.add(match_id)
        self.dados["vistas"].append(match_id)
        self._mudou = True
        info = partida["info"]
        if info.get("queueId") != 420 or info.get("gameDuration", 0) < 900:
            return False  # ignora outras filas e partidas curtas (remake/surrender cedo)

        for p in info["participants"]:
            rota = p.get("teamPosition")
            if rota not in ROTAS:
                continue
            c = self.dados["campeoes"].setdefault(f"{p['championId']}:{rota}", {
                "jogos": 0, "vitorias": 0, "itens": {}, "botas": {}, "runas": {}, "feiticos": {}})
            v = 1 if p.get("win") else 0
            c["jogos"] += 1
            c["vitorias"] += v

            for iid in {p.get(f"item{i}", 0) for i in range(6)} - {0}:
                item = self.riot.itens.get(iid)
                if not item:
                    continue
                if item["botas"]:
                    _somar(c["botas"], str(iid), v)
                elif item["final"]:
                    _somar(c["itens"], str(iid), v)

            estilos = p.get("perks", {}).get("styles", [])
            prim = next((s for s in estilos if s.get("description") == "primaryStyle"), None)
            sec = next((s for s in estilos if s.get("description") == "subStyle"), None)
            if prim and sec:
                perks = [s["perk"] for s in prim["selections"]] + [s["perk"] for s in sec["selections"]]
                _somar(c["runas"], f"{prim['style']}|{sec['style']}|" + ",".join(map(str, perks)), v)

            feiticos = sorted([p.get("summoner1Id", 0), p.get("summoner2Id", 0)])
            _somar(c["feiticos"], f"{feiticos[0]}|{feiticos[1]}", v)
        return True

    async def _atualizar_fila(self):
        jogadores = []
        for tier in ("CHALLENGER", "GRANDMASTER"):
            try:
                jogadores += [e["puuid"] for e in await self.riot.liga_alto_elo(tier) if e.get("puuid")]
            except RiotErro as e:
                log.warning("Não consegui buscar a liga %s: %s", tier, e)
        random.shuffle(jogadores)
        self._fila_jogadores = jogadores
        self._fila_atualizada = time.time()
        log.info("Coleta de builds: %d jogadores do alto elo na fila", len(jogadores))

    async def ciclo(self):
        """Um passo da coleta. Só roda quando a chave está com folga."""
        if self.riot.limitador.uso(120) > config.LIMITE_2MIN * 0.4:
            return
        if not self._fila_jogadores or time.time() - self._fila_atualizada > 6 * 3600:
            await self._atualizar_fila()
            if not self._fila_jogadores:
                return
        novas = 0
        for _ in range(2):
            if not self._fila_jogadores:
                break
            puuid = self._fila_jogadores.pop()
            try:
                ids = await self.riot.ids_partidas(puuid, 5, fila=420)
            except NaoEncontrado:
                continue
            for mid in [i for i in ids if i not in self._vistas][:4]:
                try:
                    if self.registrar_partida(await self.riot.partida(mid)):
                        novas += 1
                except NaoEncontrado:
                    continue
        if novas:
            log.info("Coleta de builds: +%d partidas (total %d)", novas, self.total_partidas())
        self.salvar()

    # ------------------------------------------------------------ consulta
    def rotas_do_campeao(self, champ: int) -> dict[str, int]:
        rotas = {}
        for rota in ROTAS:
            c = self.dados["campeoes"].get(f"{champ}:{rota}")
            if c:
                rotas[rota] = c["jogos"]
        return dict(sorted(rotas.items(), key=lambda kv: -kv[1]))

    def consultar(self, champ: int, rota: str | None = None) -> dict | None:
        rotas = self.rotas_do_campeao(champ)
        if not rotas:
            return None
        if rota is None:
            rota = next(iter(rotas))
        c = self.dados["campeoes"].get(f"{champ}:{rota}")
        if not c or c["jogos"] < MINIMO_JOGOS:
            return None
        jogos = c["jogos"]

        def top(d: dict, n: int):
            ordenado = sorted(d.items(), key=lambda kv: (-kv[1][0], -kv[1][1]))[:n]
            return [{"chave": k, "pct": round(v[0] / jogos * 100), "wr": round(v[1] / v[0] * 100),
                     "jogos": v[0]} for k, v in ordenado]

        runas = top(c["runas"], 1)
        pagina = None
        if runas:
            prim, sec, perks = runas[0]["chave"].split("|")
            pagina = {"primaria": int(prim), "secundaria": int(sec),
                      "perks": [int(x) for x in perks.split(",")],
                      "pct": runas[0]["pct"], "wr": runas[0]["wr"]}
        feit = top(c["feiticos"], 1)
        botas = top(c["botas"], 1)
        return {
            "campeao": champ, "rota": rota, "rotas": rotas, "jogos": jogos,
            "wr": round(c["vitorias"] / jogos * 100),
            "runas": pagina,
            "feiticos": ({"ids": [int(x) for x in feit[0]["chave"].split("|")],
                          "pct": feit[0]["pct"], "wr": feit[0]["wr"]} if feit else None),
            "botas": ({"id": int(botas[0]["chave"]), "pct": botas[0]["pct"], "wr": botas[0]["wr"]}
                      if botas else None),
            "itens": [{"id": int(i["chave"]), "pct": i["pct"], "wr": i["wr"]} for i in top(c["itens"], 6)],
        }
