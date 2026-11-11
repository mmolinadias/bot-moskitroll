"""Gera as imagens do cartão de perfil e da build (Pillow)."""
import asyncio
import io
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from analise import ROTAS_PT, compacto, tier_curto, winrate

BRANCO = (240, 242, 248)
CINZA = (160, 166, 182)
VERDE = (72, 199, 116)
VERMELHO = (232, 84, 84)
NEUTRO = (120, 125, 140)
DOURADO = (226, 184, 92)
CORES_TIER = {
    "IRON": (128, 116, 110), "BRONZE": (186, 125, 84), "SILVER": (176, 190, 202),
    "GOLD": (232, 192, 92), "PLATINUM": (78, 204, 190), "EMERALD": (64, 204, 124),
    "DIAMOND": (118, 156, 255), "MASTER": (196, 104, 234), "GRANDMASTER": (234, 84, 84),
    "CHALLENGER": (244, 214, 128),
}


@lru_cache(maxsize=64)
def fonte(tamanho: int, negrito: bool = False):
    nomes = (["segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf", "Arial Bold.ttf"] if negrito
             else ["segoeui.ttf", "arial.ttf", "DejaVuSans.ttf", "Arial.ttf"])
    for nome in nomes:
        try:
            return ImageFont.truetype(nome, tamanho)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=tamanho)
    except TypeError:
        return ImageFont.load_default()


def abrir(dados: bytes | None, tamanho: tuple[int, int] | None = None) -> Image.Image | None:
    if not dados:
        return None
    try:
        im = Image.open(io.BytesIO(dados)).convert("RGBA")
    except Exception:
        return None
    return im.resize(tamanho, Image.LANCZOS) if tamanho else im


def cobrir(im: Image.Image, w: int, h: int) -> Image.Image:
    escala = max(w / im.width, h / im.height)
    im = im.resize((int(im.width * escala) + 1, int(im.height * escala) + 1), Image.LANCZOS)
    x, y = (im.width - w) // 2, (im.height - h) // 4
    return im.crop((x, y, x + w, y + h))


def arredondar(im: Image.Image, raio: int) -> Image.Image:
    mascara = Image.new("L", im.size, 0)
    ImageDraw.Draw(mascara).rounded_rectangle((0, 0, im.width - 1, im.height - 1), raio, fill=255)
    out = im.copy()
    out.putalpha(Image.composite(im.getchannel("A"), mascara, mascara))
    return out


def fundo(splash: Image.Image | None, w: int, h: int) -> Image.Image:
    base = Image.new("RGBA", (w, h), (16, 18, 26, 255))
    if splash:
        base.alpha_composite(cobrir(splash, w, h).filter(ImageFilter.GaussianBlur(1.5)))
    gradiente = Image.new("L", (w, 1))
    for x in range(w):
        gradiente.putpixel((x, 0), int(238 - 120 * (x / w)))
    sombra = Image.new("RGBA", (w, h), (12, 14, 22, 255))
    sombra.putalpha(gradiente.resize((w, h)))
    base.alpha_composite(sombra)
    return base


def painel(img: Image.Image, caixa, raio: int = 16, cor=(255, 255, 255, 20)):
    camada = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(camada).rounded_rectangle(caixa, raio, fill=cor)
    img.alpha_composite(camada)


def colar(img: Image.Image, icone: Image.Image | None, xy, tamanho: int, raio: int = 10,
          borda=None, placeholder=(60, 64, 80, 255)):
    x, y = xy
    if borda:
        ImageDraw.Draw(img).rounded_rectangle((x - 3, y - 3, x + tamanho + 2, y + tamanho + 2),
                                              raio + 3, fill=borda)
    if icone is None:
        ImageDraw.Draw(img).rounded_rectangle((x, y, x + tamanho - 1, y + tamanho - 1), raio,
                                              fill=placeholder)
        return
    ic = arredondar(icone.resize((tamanho, tamanho), Image.LANCZOS), raio)
    img.alpha_composite(ic, (x, y))


def cortar_texto(texto: str, f, largura: int) -> str:
    if f.getlength(texto) <= largura:
        return texto
    while texto and f.getlength(texto + "…") > largura:
        texto = texto[:-1]
    return texto + "…"


def png(img: Image.Image) -> io.BytesIO:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG", optimize=True)
    buf.seek(0)
    return buf


# ================================================================ PERFIL
def desenhar_perfil(d: dict, imgs: dict) -> io.BytesIO:
    W, H = 1000, 500
    img = fundo(imgs.get("splash"), W, H)
    dr = ImageDraw.Draw(img)
    principal = d.get("solo") or d.get("flex")
    cor_tier = CORES_TIER.get(principal["tier"], NEUTRO) if principal else NEUTRO

    # ícone e nível
    colar(img, imgs.get("icone"), (40, 40), 132, raio=24, borda=cor_tier)
    nivel = str(d["nivel"])
    fn = fonte(18, True)
    lw = fn.getlength(nivel) + 24
    dr.rounded_rectangle((106 - lw / 2, 160, 106 + lw / 2, 188), 14, fill=(18, 20, 28), outline=cor_tier, width=2)
    dr.text((106, 174), nivel, font=fn, fill=BRANCO, anchor="mm")

    # nome
    f_nome = fonte(46, True)
    nome = cortar_texto(d["nome"], f_nome, 560)
    dr.text((200, 44), nome, font=f_nome, fill=BRANCO)
    dr.text((200 + f_nome.getlength(nome) + 10, 62), f"#{d['tag']}", font=fonte(26), fill=CINZA)
    sub = [f"Nível {d['nivel']}"]
    if d.get("rota"):
        sub.append(f"Rota principal: {ROTAS_PT.get(d['rota'], d['rota'])}")
    sub.append(d.get("servidor", "BR").upper())
    dr.text((202, 112), "  •  ".join(sub), font=fonte(20), fill=CINZA)

    # ranqueadas
    for i, (titulo, e) in enumerate((("RANQUEADA SOLO/DUO", d.get("solo")), ("RANQUEADA FLEX", d.get("flex")))):
        x0 = 40 + i * 470
        painel(img, (x0, 205, x0 + 450, 330))
        dr.text((x0 + 20, 218), titulo, font=fonte(15, True), fill=CINZA)
        if not e:
            dr.text((x0 + 20, 252), "Sem classificação", font=fonte(30, True), fill=NEUTRO)
            continue
        cor = CORES_TIER.get(e["tier"], BRANCO)
        dr.text((x0 + 20, 242), tier_curto(e), font=fonte(36, True), fill=cor)
        dr.text((x0 + 430, 262), f"{e['leaguePoints']} PDL", font=fonte(24, True), fill=BRANCO, anchor="rm")
        wr = winrate(e)
        dr.text((x0 + 20, 292), f"{e['wins']}V {e['losses']}D  ·  {wr}%", font=fonte(19), fill=CINZA)
        bx = x0 + 230
        dr.rounded_rectangle((bx, 300, x0 + 430, 312), 6, fill=(70, 74, 92))
        if wr:
            dr.rounded_rectangle((bx, 300, bx + int(200 * wr / 100), 312), 6,
                                 fill=VERDE if wr >= 50 else VERMELHO)

    # campeões favoritos
    painel(img, (40, 350, 560, 470))
    dr.text((60, 362), "CAMPEÕES FAVORITOS", font=fonte(15, True), fill=CINZA)
    for i, m in enumerate(d.get("maestrias", [])[:3]):
        x = 60 + i * 160
        colar(img, imgs.get(f"camp{i}"), (x, 390), 62, raio=12)
        dr.text((x + 72, 394), cortar_texto(m["nome"], fonte(18, True), 84), font=fonte(18, True), fill=BRANCO)
        dr.text((x + 72, 422), f"M{m['nivel']} · {compacto(m['pontos'])}", font=fonte(16), fill=CINZA)

    # últimas partidas
    painel(img, (580, 350, 960, 470))
    rec = d.get("recentes", [])
    dr.text((600, 362), f"ÚLTIMAS {len(rec)} PARTIDAS" if rec else "ÚLTIMAS PARTIDAS",
            font=fonte(15, True), fill=CINZA)
    if not rec:
        dr.text((600, 400), "Nenhuma partida recente", font=fonte(20), fill=NEUTRO)
    else:
        for i, r in enumerate(rec[:10]):
            cor = {"V": VERDE, "D": VERMELHO}.get(r["res"], NEUTRO)
            dr.rounded_rectangle((600 + i * 34, 390, 626 + i * 34, 416), 6, fill=cor)
            dr.text((613 + i * 34, 403), r["res"], font=fonte(14, True), fill=(15, 15, 20), anchor="mm")
        validas = [r for r in rec if r["res"] != "R"]
        if validas:
            v = sum(1 for r in validas if r["res"] == "V")
            k = sum(r["k"] for r in validas) / len(validas)
            m = sum(r["d"] for r in validas) / len(validas)
            a = sum(r["a"] for r in validas) / len(validas)
            dr.text((600, 428), f"{round(v / len(validas) * 100)}% de vitórias  ·  KDA {(k + a) / max(m, 1):.2f}",
                    font=fonte(18, True), fill=BRANCO)
            dr.text((600, 450), f"{k:.1f} / {m:.1f} / {a:.1f} em média", font=fonte(15), fill=CINZA)
    return png(img)


async def gerar_cartao_perfil(riot, d: dict) -> io.BytesIO:
    urls = {"icone": riot.url_icone_perfil(d["icone"])}
    maes = d.get("maestrias", [])
    if maes:
        urls["splash"] = riot.url_splash(maes[0]["key"])
    for i, m in enumerate(maes[:3]):
        urls[f"camp{i}"] = riot.url_campeao(m["key"])
    chaves = list(urls)
    baixados = await asyncio.gather(*(riot.imagem(urls[k]) for k in chaves))
    imgs = {k: abrir(b) for k, b in zip(chaves, baixados)}
    return await asyncio.to_thread(desenhar_perfil, d, imgs)


# ================================================================ BUILD
def desenhar_build(b: dict, nomes: dict, imgs: dict) -> io.BytesIO:
    W, H = 1000, 480
    img = fundo(imgs.get("splash"), W, H)
    dr = ImageDraw.Draw(img)

    colar(img, imgs.get("campeao"), (40, 34), 96, raio=18, borda=DOURADO)
    dr.text((156, 36), f"{nomes['campeao']}", font=fonte(44, True), fill=BRANCO)
    dr.text((158, 96), f"{ROTAS_PT.get(b['rota'], b['rota'])}  ·  {b['jogos']} partidas no alto elo  ·  "
                       f"{b['wr']}% de vitórias", font=fonte(20), fill=CINZA)

    # runas
    painel(img, (40, 160, 520, 445))
    dr.text((60, 172), "RUNAS", font=fonte(15, True), fill=CINZA)
    r = b.get("runas")
    if r:
        colar(img, imgs.get("keystone"), (60, 200), 84, raio=42, placeholder=(40, 44, 58, 255))
        colar(img, imgs.get("arvore_p"), (164, 198), 24, raio=12)
        dr.text((194, 199), nomes["arvore_p"], font=fonte(17, True), fill=BRANCO)
        for i in range(3):
            colar(img, imgs.get(f"runa{i + 1}"), (164 + i * 56, 230), 46, raio=23, placeholder=(40, 44, 58, 255))
        colar(img, imgs.get("arvore_s"), (60, 300), 24, raio=12)
        dr.text((90, 301), nomes["arvore_s"], font=fonte(17, True), fill=BRANCO)
        for i in range(2):
            colar(img, imgs.get(f"runa{i + 4}"), (60 + i * 56, 332), 46, raio=23, placeholder=(40, 44, 58, 255))
        dr.text((200, 336), cortar_texto(nomes["keystone"], fonte(22, True), 300), font=fonte(22, True), fill=DOURADO)
        dr.text((200, 366), f"Usada em {r['pct']}% · {r['wr']}% WR", font=fonte(17), fill=CINZA)
    else:
        dr.text((60, 210), "Sem dados de runas", font=fonte(20), fill=NEUTRO)

    # feitiços e botas
    painel(img, (540, 160, 960, 445))
    dr.text((560, 172), "FEITIÇOS", font=fonte(15, True), fill=CINZA)
    f = b.get("feiticos")
    if f:
        for i in range(2):
            colar(img, imgs.get(f"feitico{i}"), (560 + i * 60, 200), 52, raio=10)
        dr.text((686, 214), f"{f['pct']}%", font=fonte(20, True), fill=BRANCO)
    dr.text((770, 172), "BOTAS", font=fonte(15, True), fill=CINZA)
    bt = b.get("botas")
    if bt:
        colar(img, imgs.get("botas"), (770, 200), 52, raio=10)
        dr.text((834, 214), f"{bt['pct']}%", font=fonte(20, True), fill=BRANCO)

    # itens
    dr.text((560, 276), "ITENS MAIS USADOS", font=fonte(15, True), fill=CINZA)
    for i, it in enumerate(b.get("itens", [])[:6]):
        x = 560 + i * 66
        colar(img, imgs.get(f"item{i}"), (x, 304), 58, raio=10)
        dr.text((x + 29, 378), f"{it['pct']}%", font=fonte(17, True), fill=BRANCO, anchor="mm")
        dr.text((x + 29, 400), f"{it['wr']}% WR", font=fonte(13), fill=VERDE if it["wr"] >= 50 else VERMELHO,
                anchor="mm")
    dr.text((40, 460), "Dados de partidas ranqueadas Desafiante e Grão-Mestre coletadas pelo bot",
            font=fonte(14), fill=CINZA)
    return png(img)


async def gerar_cartao_build(riot, b: dict) -> io.BytesIO:
    urls = {"campeao": riot.url_campeao(b["campeao"]), "splash": riot.url_splash(b["campeao"])}
    nomes = {"campeao": riot.nome_campeao(b["campeao"])}
    r = b.get("runas")
    if r:
        urls["keystone"] = riot.url_runa(r["perks"][0])
        urls["arvore_p"] = riot.url_runa(r["primaria"])
        urls["arvore_s"] = riot.url_runa(r["secundaria"])
        for i, p in enumerate(r["perks"][1:6], start=1):
            urls[f"runa{i}"] = riot.url_runa(p)
        nomes.update(keystone=riot.nome_runa(r["perks"][0]), arvore_p=riot.nome_runa(r["primaria"]),
                     arvore_s=riot.nome_runa(r["secundaria"]))
    if b.get("feiticos"):
        for i, fid in enumerate(b["feiticos"]["ids"]):
            urls[f"feitico{i}"] = riot.url_feitico(fid)
    if b.get("botas"):
        urls["botas"] = riot.url_item(b["botas"]["id"])
    for i, it in enumerate(b.get("itens", [])[:6]):
        urls[f"item{i}"] = riot.url_item(it["id"])
    chaves = list(urls)
    baixados = await asyncio.gather(*(riot.imagem(urls[k]) for k in chaves))
    imgs = {k: abrir(v) for k, v in zip(chaves, baixados)}
    return await asyncio.to_thread(desenhar_build, b, nomes, imgs)
