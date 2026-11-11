"""
Monta o bot-discloud.zip para ATUALIZAR o bot na Discloud (página Commit).

Rode com:  python montar_zip.py

O zip NÃO leva o dados.json de propósito: a Discloud só troca os arquivos que estão
no zip, então o dados.json de lá (moedas, apostas, vínculos, histórico) fica intacto.
Se o dados.json do seu PC fosse junto, ele apagaria tudo o que o bot juntou na Discloud.
"""
import zipfile
from pathlib import Path

PASTA = Path(__file__).resolve().parent
DESTINO = PASTA / "bot-discloud.zip"
FIXOS = ["discloud.config", ".env", "requirements.txt"]
FORA = {"montar_zip.py"}  # não precisa ir para a Discloud


def main():
    arquivos = [PASTA / n for n in FIXOS] + sorted(p for p in PASTA.glob("*.py") if p.name not in FORA)
    faltando = [p.name for p in arquivos if not p.exists()]
    if faltando:
        raise SystemExit(f"Faltam arquivos: {', '.join(faltando)}")

    with zipfile.ZipFile(DESTINO, "w", zipfile.ZIP_DEFLATED) as z:
        for p in arquivos:
            z.write(p, p.name)

    print(f"Pronto: {DESTINO.name} com {len(arquivos)} arquivos (sem o dados.json):")
    for p in arquivos:
        print(f"  - {p.name}")
    print("\nAgora arraste o zip na página Commit do bot na Discloud.")


if __name__ == "__main__":
    main()
