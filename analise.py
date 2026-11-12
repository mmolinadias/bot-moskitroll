"""Cálculos e textos: elo, notas de desempenho, MVP, odds das apostas."""

TIERS = ["IRON", "BRONZE", "SILVER", "GOLD", "PLATINUM", "EMERALD",
         "DIAMOND", "MASTER", "GRANDMASTER", "CHALLENGER"]
TIER_PT = {
    "IRON": "Ferro", "BRONZE": "Bronze", "SILVER": "Prata", "GOLD": "Ouro",
    "PLATINUM": "Platina", "EMERALD": "Esmeralda", "DIAMOND": "Diamante",
    "MASTER": "Mestre", "GRANDMASTER": "Grão-Mestre", "CHALLENGER": "Desafiante",
}
DIVISOES = {"IV": 0, "III": 1, "II": 2, "I": 3}
DIV_NOMES = ["IV", "III", "II", "I"]
SEM_DIVISAO = ("MASTER", "GRANDMASTER", "CHALLENGER")
FILAS_RANK = {"RANKED_SOLO_5x5": "Solo/Duo", "RANKED_FLEX_SR": "Flex"}
FILA_PARA_TIPO = {420: "RANKED_SOLO_5x5", 440: "RANKED_FLEX_SR"}
FILAS = {
    400: "Normal (Escolha)", 420: "Ranqueada Solo/Duo", 430: "Normal (Às cegas)",
    440: "Ranqueada Flex", 450: "ARAM", 480: "Partida Rápida", 490: "Partida Rápida",
    700: "Clash", 720: "Clash ARAM", 900: "URF", 1700: "Arena", 1900: "URF",
    0: "Personalizada",
}
ROTAS_PT = {"TOP": "Topo", "JUNGLE": "Selva", "MIDDLE": "Meio",
            "BOTTOM": "Atirador", "UTILITY": "Suporte"}
TIMES_PT = {100: "Time Azul", 200: "Time Vermelho"}


def nome_fila(queue_id) -> str:
    return FILAS.get(queue_id, f"Fila {queue_id}")


def numero(n) -> str:
    return f"{int(n):,}".replace(",", ".")


def compacto(n) -> str:
    n = int(n)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f} mi".replace(".", ",")
    if n >= 1_000:
        return f"{round(n / 1000)} mil"
    return str(n)


def tier_curto(entry: dict) -> str:
    tier = entry["tier"]
    if tier in SEM_DIVISAO:
        return TIER_PT.get(tier, tier)
    return f"{TIER_PT.get(tier, tier)} {entry['rank']}"


def texto_elo(entry: dict) -> str:
    return f"{tier_curto(entry)} — {entry['leaguePoints']} PDL"


def pontuacao_elo(entry: dict) -> int:
    """Número para comparar elos. 100 pontos = 1 divisão, então a diferença ≈ PDL."""
    tier = TIERS.index(entry["tier"]) if entry["tier"] in TIERS else 0
    if entry["tier"] in SEM_DIVISAO:
        return TIERS.index("MASTER") * 400 + entry["leaguePoints"]
    return tier * 400 + DIVISOES.get(entry.get("rank", "IV"), 0) * 100 + entry["leaguePoints"]


def texto_pontuacao(p: float) -> str:
    """Converte uma pontuação (ex.: média do time) de volta para um elo aproximado."""
    master = TIERS.index("MASTER") * 400
    if p >= master:
        return "Mestre+"
    tier = max(0, int(p // 400))
    div = max(0, min(3, int((p % 400) // 100)))
    return f"{TIER_PT[TIERS[tier]]} {DIV_NOMES[div]}"


def melhor_fila(entries: list[dict]) -> dict | None:
    for tipo in ("RANKED_SOLO_5x5", "RANKED_FLEX_SR"):
        for e in entries:
            if e.get("queueType") == tipo:
                return e
    return None


def winrate(e: dict) -> int:
    total = e["wins"] + e["losses"]
    return round(e["wins"] / total * 100) if total else 0


def kda(k, d, a) -> float:
    return (k + a) / max(d, 1)


def texto_variacao(antes: dict | None, agora: dict) -> tuple[str, int | None]:
    """Texto de PDL ganho/perdido e o número (para estatísticas)."""
    if antes is None:
        return f"🆕 Classificado em **{texto_elo(agora)}**", None
    delta = pontuacao_elo(agora) - pontuacao_elo(antes)
    sinal = "+" if delta >= 0 else ""
    mudou_tier = (antes["tier"], antes.get("rank")) != (agora["tier"], agora.get("rank"))
    if mudou_tier and delta > 0:
        return f"⬆️ **{sinal}{delta} PDL — SUBIU para {tier_curto(agora)}!** 🎉", delta
    if mudou_tier and delta < 0:
        return f"⬇️ **{delta} PDL — caiu para {tier_curto(agora)}** 😢", delta
    return f"{'📈' if delta >= 0 else '📉'} **{sinal}{delta} PDL** → {texto_elo(agora)}", delta


# --------------------------------------------------------------- desempenho
def calcular_notas(info: dict) -> dict[str, dict]:
    """
    Dá uma nota de 0 a 10 para cada jogador comparando com os outros 9:
    KDA, participação em abates, dano a campeões, ouro e placar de visão.
    MVP = maior nota do time vencedor; ACE = maior nota do time perdedor;
    NTP = menor nota da partida (o inverso do MVP).
    """
    ps = info.get("participants", [])
    if not ps:
        return {}
    minutos = max(info.get("gameDuration", 60), 60) / 60
    abates_time: dict[int, int] = {}
    for p in ps:
        abates_time[p["teamId"]] = abates_time.get(p["teamId"], 0) + p["kills"]

    metricas = {}
    for p in ps:
        metricas[p["puuid"]] = [
            kda(p["kills"], p["deaths"], p["assists"]),
            (p["kills"] + p["assists"]) / max(abates_time[p["teamId"]], 1),
            p.get("totalDamageDealtToChampions", 0),
            p.get("goldEarned", 0),
            p.get("visionScore", 0) / minutos,
        ]

    n = len(ps)
    notas = {}
    for p in ps:
        minhas = metricas[p["puuid"]]
        percentis = []
        for i, valor in enumerate(minhas):
            outros = [metricas[o["puuid"]][i] for o in ps if o is not p]
            menores = sum(1 for o in outros if o < valor)
            iguais = sum(1 for o in outros if o == valor)
            percentis.append((menores + 0.5 * iguais) / max(n - 1, 1))
        base = sum(percentis) / len(percentis)
        nota = 2 + 7.5 * base + (0.5 if p.get("win") else 0)
        notas[p["puuid"]] = {"nota": round(max(0, min(10, nota)), 1), "mvp": False, "ace": False, "ntp": False}

    vencedores = [p for p in ps if p.get("win")]
    perdedores = [p for p in ps if not p.get("win")]
    if vencedores:
        notas[max(vencedores, key=lambda p: notas[p["puuid"]]["nota"])["puuid"]]["mvp"] = True
    if perdedores:
        notas[max(perdedores, key=lambda p: notas[p["puuid"]]["nota"])["puuid"]]["ace"] = True
    notas[min(ps, key=lambda p: notas[p["puuid"]]["nota"])["puuid"]]["ntp"] = True
    return notas


# --------------------------------------------------------------- apostas
def calcular_odds(forca_azul: float | None, forca_vermelho: float | None) -> dict[str, float]:
    """Odds de cada time a partir da média de elo (quem é mais forte paga menos)."""
    if forca_azul is None or forca_vermelho is None:
        return {"100": 1.9, "200": 1.9}
    chance_azul = 1 / (1 + 10 ** ((forca_vermelho - forca_azul) / 600))

    def odd(p):
        return round(max(1.15, min(5.0, 0.95 / max(p, 0.01))), 2)

    return {"100": odd(chance_azul), "200": odd(1 - chance_azul)}
