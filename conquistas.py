"""Conquistas permanentes: contadores por jogador guardados no dados.json (o histórico só guarda 35 dias)."""
import time

# id: (emoji, nome, descrição)
CONQUISTAS = {
    "primeira":   ("🎉", "Primeira de muitas", "Ganhar a primeira partida registrada"),
    "jogos100":   ("🕹️", "Sem vida social", "Jogar 100 partidas"),
    "vit50":      ("🏅", "Viciado em vitória", "Ganhar 50 partidas"),
    "seqv5":      ("🔥", "Imparável", "Ganhar 5 seguidas"),
    "seqv10":     ("☄️", "Lenda", "Ganhar 10 seguidas"),
    "seqd5":      ("🕳️", "Fundo do poço", "Perder 5 seguidas"),
    "seqd10":     ("⛏️", "Escavando o pré-sal", "Perder 10 seguidas"),
    "penta":      ("🖐️", "PENTAKILL", "Fazer um pentakill"),
    "penta3":     ("💎", "Colecionador de pentas", "Fazer 3 pentakills"),
    "mvp10":      ("🏆", "Carregador de piano", "Ser MVP 10 vezes na Flex"),
    "ntp10":      ("⚓", "Âncora", "Ser NTP 10 vezes na Flex"),
    "nota95":     ("🎓", "Aula de LoL", "Tirar nota 9,5 ou mais"),
    "abates20":   ("🗡️", "Massacre", "Fazer 20 abates numa partida"),
    "mortes15":   ("🍗", "Alimentador oficial", "Morrer 15 vezes numa partida"),
    "intocavel":  ("🛡️", "Intocável", "Ganhar sem morrer nenhuma vez"),
    "assist30":   ("🤝", "Babá do time", "Fazer 30 assistências numa partida"),
    "campeoes20": ("🎭", "Pau pra toda obra", "Jogar com 20 campeões diferentes"),
}


def _novo() -> dict:
    return {"tem": {}, "jogos": 0, "vitorias": 0, "pentas": 0, "mvps": 0, "ntps": 0, "seq": 0, "campeoes": []}


def _ganhar(c: dict, cid: str, ts: float) -> list[str]:
    if cid in c["tem"]:
        return []
    c["tem"][cid] = ts
    return [cid]


def _aplicar(c: dict, e: dict) -> list[str]:
    """Soma uma partida do histórico nos contadores e devolve as conquistas novas."""
    if e.get("remake"):
        return []
    ts = e.get("ts", time.time())
    novas = []
    c["jogos"] += 1
    if e.get("vitoria"):
        c["vitorias"] += 1
        c["seq"] = c["seq"] + 1 if c["seq"] > 0 else 1
    else:
        c["seq"] = c["seq"] - 1 if c["seq"] < 0 else -1
    if e.get("penta"):
        c["pentas"] += 1
    if e.get("mvp") and e.get("fila") == 440:
        c["mvps"] += 1
    if e.get("ntp") and e.get("fila") == 440:
        c["ntps"] += 1
    if e.get("campeao") and e["campeao"] not in c["campeoes"]:
        c["campeoes"].append(e["campeao"])
    regras = {
        "primeira": c["vitorias"] >= 1, "jogos100": c["jogos"] >= 100, "vit50": c["vitorias"] >= 50,
        "seqv5": c["seq"] >= 5, "seqv10": c["seq"] >= 10, "seqd5": c["seq"] <= -5, "seqd10": c["seq"] <= -10,
        "penta": c["pentas"] >= 1, "penta3": c["pentas"] >= 3, "mvp10": c["mvps"] >= 10, "ntp10": c["ntps"] >= 10,
        "nota95": (e.get("nota") or 0) >= 9.5, "abates20": e.get("k", 0) >= 20, "mortes15": e.get("d", 0) >= 15,
        "intocavel": bool(e.get("vitoria")) and e.get("d", 1) == 0, "assist30": e.get("a", 0) >= 30,
        "campeoes20": len(c["campeoes"]) >= 20,
    }
    for cid, ok in regras.items():
        if ok:
            novas += _ganhar(c, cid, ts)
    return novas


class Conquistas:
    def __init__(self, store):
        self.store = store

    def jogador(self, g, u) -> dict:
        """Contadores do jogador; na primeira vez, monta a partir do histórico que existe (sem anunciar)."""
        dados = self.store.d.setdefault("conquistas", {}).setdefault(str(g), {})
        u = str(u)
        if u not in dados:
            c = _novo()
            for e in sorted((e for e in self.store.historico(g) if e["user"] == u), key=lambda e: e["ts"]):
                _aplicar(c, e)
            dados[u] = c
        return dados[u]

    def registrar(self, g, u, entrada: dict) -> list[str]:
        """Chamar logo depois de gravar a partida no histórico. Devolve os textos das conquistas novas."""
        dados = self.store.d.setdefault("conquistas", {}).setdefault(str(g), {})
        if str(u) not in dados:
            self.jogador(g, u)  # já inclui a partida que acabou de entrar no histórico
            novas = [cid for cid, ts in dados[str(u)]["tem"].items() if ts == entrada.get("ts")]
        else:
            novas = _aplicar(dados[str(u)], entrada)
        return [self.texto(cid) for cid in novas]

    def ntp_extra(self, g, u, ts: float) -> list[str]:
        """NTP feito numa smurf e atribuído à main."""
        c = self.jogador(g, u)
        c["ntps"] += 1
        return [self.texto(cid) for cid in (_ganhar(c, "ntp10", ts) if c["ntps"] >= 10 else [])]

    @staticmethod
    def texto(cid: str) -> str:
        emoji, nome, desc = CONQUISTAS[cid]
        return f"{emoji} **{nome}** — {desc}"

    def lista(self, g, u) -> tuple[list[str], list[str]]:
        c = self.jogador(g, u)
        tem = sorted(c["tem"], key=c["tem"].get)
        falta = [cid for cid in CONQUISTAS if cid not in c["tem"]]
        return tem, falta
