"""Loja de itens comprados com as moedas fictícias das apostas.

Aqui fica o catálogo e as regras que não dependem do Discord (preços, validações, rifa,
seguro/odd turbinada nas apostas e o desafio do Ultimate Bravery). Os comandos ficam no bot.py.
As moedas não valem nada de verdade e a loja nunca vende nada com valor real.
"""
import random
import re
import time

from riot import RiotErro

# id -> dados do item. "precos" = preço por duração (minutos) nos castigos.
ITENS = {
    # visual
    "titulo": {"nome": "Título no perfil", "emoji": "🏷️", "cat": "visual", "preco": 1500,
               "desc": "Uma frase embaixo do seu nome no `/perfil` (use `texto`)"},
    "cor": {"nome": "Cor do cartão", "emoji": "🎨", "cat": "visual", "preco": 2500,
            "desc": "Muda a cor de destaque do seu `/perfil` (use `cor`)"},
    "fundo": {"nome": "Fundo com campeão", "emoji": "🖼️", "cat": "visual", "preco": 3000,
              "desc": "Imagem de um campeão no fundo do seu `/perfil` (use `campeao`)"},
    "emoji": {"nome": "Emoji no ranking", "emoji": "😎", "cat": "visual", "preco": 1000,
              "desc": "Um emoji ao lado do seu nome no `/ranking` e no `/top-moedas` (use `texto`)"},
    "cargo": {"nome": "Cargo colorido", "emoji": "🌈", "cat": "visual", "preco": 5000,
              "desc": "Um cargo com a cor que você quiser no servidor (use `cor`)"},
    "coroa": {"nome": "Coroa de Magnata", "emoji": "👑", "cat": "visual", "preco": 20000,
              "desc": "👑 fixa ao lado do seu nome em todo lugar"},
    # apostas
    "seguro": {"nome": "Seguro de aposta", "emoji": "🛟", "cat": "apostas", "preco": 300,
               "desc": "Na sua próxima aposta, se perder, recebe metade de volta"},
    "turbo": {"nome": "Odd turbinada", "emoji": "🚀", "cat": "apostas", "preco": 500,
              "desc": "Na sua próxima aposta, se ganhar, recebe 1,5x o prêmio"},
    "rifa": {"nome": "Bilhete da rifa", "emoji": "🎟️", "cat": "apostas", "preco": 100,
             "desc": "Concorre ao pote da semana, sorteado no domingo junto com o resumo"},
    # zoeira
    "desafio": {"nome": "Desafio Bravery", "emoji": "🎲", "cat": "zoeira", "preco": 800,
                "desc": "Sorteia um Ultimate Bravery para um amigo. Se ele jogar e ganhar com o campeão "
                        "em até 2 dias, leva 1.600 moedas (use `alvo`)"},
    "anuncio": {"nome": "Anúncio", "emoji": "📢", "cat": "zoeira", "preco": 500,
                "desc": "O bot posta sua mensagem em destaque no canal dos alertas (use `texto`)"},
    "apelido": {"nome": "Apelido forçado", "emoji": "🤡", "cat": "zoeira", "preco": 2000,
                "desc": "Muda o apelido de um amigo por 24h (use `alvo` e `texto`)"},
    # castigos
    "castigo": {"nome": "Castigo", "emoji": "⛓️", "cat": "castigos", "precos": {1: 300, 5: 1200, 10: 2000},
                "desc": "Deixa o amigo de castigo (sem falar nem entrar em call) (use `alvo` e `minutos`)"},
    "mutar": {"nome": "Mutar microfone", "emoji": "🔇", "cat": "castigos", "precos": {1: 200, 5: 800, 10: 1500},
              "desc": "Muta o microfone do amigo na call (use `alvo` e `minutos`)"},
    "surdo": {"nome": "Ensurdecer", "emoji": "🙉", "cat": "castigos", "precos": {1: 200, 5: 800, 10: 1500},
              "desc": "O amigo para de ouvir a call (use `alvo` e `minutos`)"},
    "chutar": {"nome": "Chutar da call", "emoji": "🦶", "cat": "castigos", "preco": 400,
               "desc": "Desconecta o amigo da call (use `alvo`)"},
    "escudo": {"nome": "Escudo", "emoji": "🛡️", "cat": "castigos", "preco": 1500,
               "desc": "Bloqueia o próximo castigo, mute, ensurdecer, chute ou apelido contra você"},
}
CATEGORIAS = {"visual": "🎨 Visual", "apostas": "🎲 Apostas", "zoeira": "😂 Zoeira",
              "castigos": "⛓️ Castigos (para os amigos)"}
CASTIGOS = {"castigo", "mutar", "surdo", "chutar"}
CONTAVEIS = {"seguro", "turbo", "escudo", "rifa"}   # itens que dá para comprar vários de uma vez
CORES = {
    "vermelho": ("Vermelho", 0xE74C3C), "laranja": ("Laranja", 0xE67E22), "dourado": ("Dourado", 0xF1C40F),
    "verde": ("Verde", 0x2ECC71), "ciano": ("Ciano", 0x1ABC9C), "azul": ("Azul", 0x3498DB),
    "roxo": ("Roxo", 0x9B59B6), "rosa": ("Rosa", 0xFF6EC7), "branco": ("Branco", 0xECF0F1),
}
IMUNIDADE_MIN = 10        # depois de um castigo, o alvo fica protegido por mais 10 minutos
DESAFIO_HORAS = 48
PREMIO_DESAFIO = 1600
APELIDO_HORAS = 24
_EMOJI_DISCORD = re.compile(r"^<a?:\w{2,32}:\d{15,22}>$")


class ErroLoja(RiotErro):
    """Erro com mensagem amigável (a compra não é cobrada)."""


def preco(item: str, minutos: int | None = None, quantidade: int = 1) -> int:
    it = ITENS[item]
    if "precos" in it:
        return it["precos"][minutos or 1]
    return it["preco"] * quantidade


def texto_preco(item: str) -> str:
    it = ITENS[item]
    if "precos" in it:
        return " · ".join(f"{m} min: {v:,}".replace(",", ".") for m, v in it["precos"].items())
    return f"{it['preco']:,}".replace(",", ".")


def emoji_valido(texto: str) -> bool:
    texto = texto.strip()
    if _EMOJI_DISCORD.match(texto):
        return True
    return (0 < len(texto) <= 8 and not any(c.isascii() and (c.isalnum() or c in "@#`<>*_~|:") for c in texto)
            and not texto.isspace())


def limpar_texto(texto: str | None, limite: int) -> str:
    texto = " ".join((texto or "").split())
    if not texto:
        raise ErroLoja("Esse item precisa do campo `texto`.")
    if len(texto) > limite:
        raise ErroLoja(f"O texto pode ter no máximo {limite} letras.")
    return texto


# ---------------------------------------------------------------- dados
class DadosLoja:
    """Acesso à parte "loja" do dados.json: {guild: {"usuarios", "rifa", "desafios", "pendentes", "config"}}."""

    def __init__(self, store):
        self.store = store

    def servidor(self, g) -> dict:
        s = self.store.de("loja", g)
        s.setdefault("usuarios", {})
        s.setdefault("rifa", {"pote": 0, "bilhetes": {}})
        s.setdefault("desafios", {})
        s.setdefault("pendentes", [])
        s.setdefault("config", {"castigos": True})
        return s

    def usuario(self, g, u) -> dict:
        return self.servidor(g)["usuarios"].setdefault(str(u), {})

    def enfeite(self, g, u) -> str:
        """Prefixo com a coroa e o emoji comprados, ex.: '👑 🐸 '."""
        d = self.servidor(g)["usuarios"].get(str(u), {})
        partes = (["👑"] if d.get("coroa") else []) + ([d["emoji"]] if d.get("emoji") else [])
        return " ".join(partes) + " " if partes else ""

    def inventario(self, g, u) -> list[str]:
        d = self.servidor(g)["usuarios"].get(str(u), {})
        linhas = []
        for item in ("seguro", "turbo", "escudo"):
            if d.get(item):
                linhas.append(f"{ITENS[item]['emoji']} {ITENS[item]['nome']} x{d[item]}")
        bilhetes = self.servidor(g)["rifa"]["bilhetes"].get(str(u), 0)
        if bilhetes:
            linhas.append(f"🎟️ {bilhetes} bilhete(s) da rifa")
        if d.get("titulo"):
            linhas.append(f"🏷️ Título: “{d['titulo']}”")
        if d.get("coroa"):
            linhas.append("👑 Coroa de Magnata")
        return linhas

    # ------------------------------------------------------------ castigos
    def checar_alvo(self, g, alvo_id) -> None:
        d = self.usuario(g, alvo_id)
        ate = d.get("imune_ate", 0)
        if ate > time.time():
            raise ErroLoja(f"<@{alvo_id}> acabou de levar um castigo e está protegido até <t:{int(ate)}:t>.")

    def usar_escudo(self, g, alvo_id) -> bool:
        d = self.usuario(g, alvo_id)
        if d.get("escudo", 0) > 0:
            d["escudo"] -= 1
            return True
        return False

    def marcar_imune(self, g, alvo_id, minutos: float):
        self.usuario(g, alvo_id)["imune_ate"] = time.time() + (minutos + IMUNIDADE_MIN) * 60

    def agendar(self, g, tipo: str, alvo_id, segundos: float, **extra):
        """Guarda algo para desfazer depois (desmutar, devolver apelido...)."""
        self.servidor(g)["pendentes"].append({"tipo": tipo, "user": str(alvo_id),
                                              "ate": time.time() + segundos, **extra})

    # ------------------------------------------------------------ apostas
    def aplicar_na_aposta(self, g, u, aposta: dict) -> list[str]:
        """Gasta o seguro e a odd turbinada (se a pessoa tiver) numa aposta nova."""
        d = self.usuario(g, u)
        usados = []
        for item in ("seguro", "turbo"):
            if d.get(item, 0) > 0:
                d[item] -= 1
                aposta[item] = True
                usados.append(f"{ITENS[item]['emoji']} {ITENS[item]['nome']}")
        return usados

    def devolver_itens(self, g, u, aposta: dict):
        """Remake: devolve o seguro e a odd turbinada que foram usados."""
        d = self.usuario(g, u)
        for item in ("seguro", "turbo"):
            if aposta.get(item):
                d[item] = d.get(item, 0) + 1

    # ------------------------------------------------------------ rifa
    def sortear_rifa(self, g) -> tuple[str, int, int] | None:
        """Sorteia o pote da semana. Devolve (vencedor, pote, total de bilhetes) e zera a rifa."""
        rifa = self.servidor(g)["rifa"]
        bilhetes = {u: n for u, n in rifa["bilhetes"].items() if n > 0}
        if not bilhetes:
            return None
        vencedor = random.choices(list(bilhetes), weights=list(bilhetes.values()))[0]
        pote, total = rifa["pote"], sum(bilhetes.values())
        self.servidor(g)["rifa"] = {"pote": 0, "bilhetes": {}}
        return vencedor, pote, total

    # ------------------------------------------------------------ desafio Bravery
    def checar_desafio(self, g, u, champ_id: int, venceu: bool, remake: bool) -> tuple[str, int] | None:
        """Chamado no fim de cada partida de um membro. Devolve (texto, prêmio) se havia desafio com esse campeão."""
        desafios = self.servidor(g)["desafios"]
        d = desafios.get(str(u))
        if not d:
            return None
        if d["ate"] < time.time():
            desafios.pop(str(u))
            return None
        if remake or int(champ_id) != d["campeao"]:
            return None
        desafios.pop(str(u))
        if venceu:
            return f"🎲 Cumpriu o **Desafio Bravery** de <@{d['de']}>: +{PREMIO_DESAFIO:,} moedas!".replace(",", "."), \
                PREMIO_DESAFIO
        return f"🎲 Perdeu o **Desafio Bravery** de <@{d['de']}>. Sem prêmio dessa vez.", 0
