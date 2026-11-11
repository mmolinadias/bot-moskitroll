"""Guarda os dados do bot (vínculos, partidas, moedas, histórico) em dados.json."""
import json
import logging
import time
from pathlib import Path

import config

log = logging.getLogger("bot-lol.dados")

CHAVES = {
    "vinculos": {},        # {guild: {user: {"puuid", "riot_id"}}}
    "alertas": {},         # {guild: channel_id}
    "partidas": {},        # {guild: {game_id: {...}}}  partidas acontecendo
    "pendentes": {},       # {guild: {game_id: {...}}}  partidas que acabaram, esperando resultado
    "historico": {},       # {guild: [ {...}, ... ]}
    "moedas": {},          # {guild: {user: {"saldo", "diario"}}}
    "resumo_semanal": {},  # {guild: "2026-W45"}
    "loja": {},            # {guild: {"usuarios", "rifa", "desafios", "pendentes", "config"}}
}


class Dados:
    def __init__(self, caminho: Path):
        self.caminho = caminho
        self.d = self._carregar()

    def _carregar(self) -> dict:
        dados = {}
        if self.caminho.exists():
            try:
                dados = json.loads(self.caminho.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                log.error("dados.json corrompido; guardei uma cópia em dados.json.bak")
                self.caminho.rename(self.caminho.with_suffix(".json.bak"))
                dados = {}
        dados.pop("ultimo_jogo", None)  # campo da versão antiga
        for chave, padrao in CHAVES.items():
            dados.setdefault(chave, type(padrao)())
        return dados

    def salvar(self):
        tmp = self.caminho.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.d, indent=1, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.caminho)

    def de(self, chave: str, guild_id) -> dict:
        return self.d[chave].setdefault(str(guild_id), {})

    def historico(self, guild_id) -> list:
        return self.d["historico"].setdefault(str(guild_id), [])

    def carteira(self, guild_id, user_id) -> dict:
        return self.de("moedas", guild_id).setdefault(
            str(user_id), {"saldo": config.SALDO_INICIAL, "diario": 0})

    def limpar_historico(self, dias: int = 35):
        limite = time.time() - dias * 86400
        for g, lista in self.d["historico"].items():
            self.d["historico"][g] = [e for e in lista if e.get("ts", 0) >= limite]
