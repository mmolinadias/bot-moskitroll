"""Lê as configurações do arquivo .env."""
import os
from pathlib import Path

from dotenv import load_dotenv

PASTA = Path(__file__).resolve().parent
load_dotenv(PASTA / ".env")


def _int(nome: str, padrao: int) -> int:
    try:
        return int(os.getenv(nome, "") or padrao)
    except ValueError:
        return padrao


def _bool(nome: str, padrao: bool) -> bool:
    valor = os.getenv(nome, "").strip().lower()
    if not valor:
        return padrao
    return valor not in ("0", "nao", "não", "false", "off", "n")


DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
RIOT_API_KEY = os.getenv("RIOT_API_KEY", "").strip()
PLATFORM = os.getenv("RIOT_PLATFORM", "br1").strip().lower()
REGION = os.getenv("RIOT_REGION", "americas").strip().lower()
GUILD_ID = os.getenv("GUILD_ID", "").strip()

INTERVALO_ALERTA = max(1, _int("INTERVALO_ALERTA_MIN", 2))
COLETAR_BUILDS = _bool("COLETAR_BUILDS", True)

# Limites da chave (dev e personal: 20 por segundo e 100 a cada 2 minutos)
LIMITE_SEG = _int("RIOT_LIMITE_POR_SEGUNDO", 20)
LIMITE_2MIN = _int("RIOT_LIMITE_POR_2MIN", 100)

# Resumo semanal: 0 = segunda ... 6 = domingo
FUSO = os.getenv("FUSO_HORARIO", "America/Sao_Paulo").strip()
RESUMO_DIA = _int("RESUMO_SEMANAL_DIA", 6)
RESUMO_HORA = _int("RESUMO_SEMANAL_HORA", 20)

# Moedas fictícias das apostas
SALDO_INICIAL = _int("MOEDAS_INICIAIS", 1000)
BONUS_DIARIO = _int("MOEDAS_DIARIO", 250)
TEMPO_APOSTAS_MIN = _int("TEMPO_APOSTAS_MIN", 8)
