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
# Quesitos da nota e o peso de cada um por rota (cada linha soma 1).
# O suporte é avaliado mais por visão, assistências, cura/escudo nos aliados e controle de grupo;
# atirador, meio e topo mais por dano e ouro. Sem rota (ARAM etc.) usa os 5 quesitos com o mesmo peso.
QUESITOS = ("kda", "participacao", "dano", "ouro", "visao", "assistencias", "cura_escudo", "controle")
PESOS_ROTA = {
    "TOP":     {"kda": .20, "participacao": .15, "dano": .25, "ouro": .20, "visao": .10, "controle": .10},
    "JUNGLE":  {"kda": .20, "participacao": .25, "dano": .15, "ouro": .15, "visao": .15, "controle": .10},
    "MIDDLE":  {"kda": .20, "participacao": .20, "dano": .25, "ouro": .20, "visao": .10, "controle": .05},
    "BOTTOM":  {"kda": .20, "participacao": .20, "dano": .30, "ouro": .20, "visao": .10},
    "UTILITY": {"kda": .15, "participacao": .20, "visao": .20, "assistencias": .15, "cura_escudo": .15,
                "controle": .15},
}
PESOS_PADRAO = {"kda": .2, "participacao": .2, "dano": .2, "ouro": .2, "visao": .2}

# Posição "normal" de cada rota em cada quesito (0 = pior dos 10, 1 = melhor). Um suporte quase sempre
# tem a maior visão e o menor ouro; um atirador, o contrário. A nota compara o jogador com o normal da
# rota dele, então ninguém ganha ou perde ponto só por causa da função. Estes valores são um chute
# inicial: a coleta de builds recalcula com as partidas de verdade (definir_esperado).
ESPERADO_PADRAO = {
    "TOP":     {"kda": .45, "participacao": .35, "dano": .60, "ouro": .65, "visao": .30, "assistencias": .30,
                "cura_escudo": .30, "controle": .50},
    "JUNGLE":  {"kda": .55, "participacao": .70, "dano": .40, "ouro": .55, "visao": .60, "assistencias": .60,
                "cura_escudo": .35, "controle": .50},
    "MIDDLE":  {"kda": .55, "participacao": .55, "dano": .80, "ouro": .75, "visao": .30, "assistencias": .45,
                "cura_escudo": .30, "controle": .50},
    "BOTTOM":  {"kda": .60, "participacao": .60, "dano": .80, "ouro": .85, "visao": .25, "assistencias": .45,
                "cura_escudo": .30, "controle": .30},
    "UTILITY": {"kda": .55, "participacao": .65, "dano": .15, "ouro": .05, "visao": .95, "assistencias": .85,
                "cura_escudo": .80, "controle": .65},
}
ESPERADO = {rota: dict(v) for rota, v in ESPERADO_PADRAO.items()}


def definir_esperado(novos: dict[str, dict[str, float]]):
    """Atualiza a posição normal de cada rota (vinda da coleta de builds)."""
    for rota, valores in novos.items():
        ESPERADO.setdefault(rota, {}).update(valores)


def percentis(ps: list[dict], minutos: float) -> dict[str, dict[str, float]]:
    """Para cada jogador e quesito: quantos dos outros 9 ficaram abaixo dele (0 a 1; empate vale meio)."""
    abates_time: dict[int, int] = {}
    for p in ps:
        abates_time[p["teamId"]] = abates_time.get(p["teamId"], 0) + p["kills"]
    metricas = {}
    for p in ps:
        metricas[p["puuid"]] = {
            "kda": kda(p["kills"], p["deaths"], p["assists"]),
            "participacao": (p["kills"] + p["assists"]) / max(abates_time[p["teamId"]], 1),
            "dano": p.get("totalDamageDealtToChampions", 0),
            "ouro": p.get("goldEarned", 0),
            "visao": p.get("visionScore", 0) / minutos,
            "assistencias": p["assists"],
            "cura_escudo": p.get("totalHealsOnTeammates", 0) + p.get("totalDamageShieldedOnTeammates", 0),
            "controle": p.get("timeCCingOthers", 0),
        }
    n = len(ps)
    resultado = {}
    for p in ps:
        minhas = metricas[p["puuid"]]
        resultado[p["puuid"]] = {}
        for q in QUESITOS:
            outros = [metricas[o["puuid"]][q] for o in ps if o is not p]
            menores = sum(1 for o in outros if o < minhas[q])
            iguais = sum(1 for o in outros if o == minhas[q])
            resultado[p["puuid"]][q] = (menores + 0.5 * iguais) / max(n - 1, 1)
    return resultado


def calcular_notas(info: dict) -> dict[str, dict]:
    """
    Dá uma nota de 0 a 10 para cada jogador comparando com os outros 9 em cada quesito
    (KDA, participação em abates, dano a campeões, ouro, visão, assistências, cura/escudo
    nos aliados e controle de grupo). Cada rota tem pesos próprios (PESOS_ROTA) e é comparada
    com a posição normal dela em cada quesito (ESPERADO), para não favorecer nenhuma função.
    MVP = maior nota do time vencedor; ACE = maior nota do time perdedor;
    NTP = menor nota da partida (o inverso do MVP).
    """
    ps = info.get("participants", [])
    if not ps:
        return {}
    minutos = max(info.get("gameDuration", 60), 60) / 60
    pcts = percentis(ps, minutos)

    notas = {}
    for p in ps:
        rota = p.get("teamPosition") or ""
        pesos = PESOS_ROTA.get(rota, PESOS_PADRAO)
        esperado = ESPERADO.get(rota) if rota in PESOS_ROTA else None
        base = 0.0
        for q, peso in pesos.items():
            pct = pcts[p["puuid"]][q]
            if esperado:  # acima do normal da rota sobe, abaixo desce (0,5 = exatamente o normal)
                pct = max(0.0, min(1.0, pct - esperado.get(q, 0.5) + 0.5))
            base += peso * pct
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
