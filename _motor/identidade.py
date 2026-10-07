"""Identidade visual "Gato Preto": aplica nome/@/cor em cada canal.json e gera logo, avatar e banner de cada tema.
Saída: F:\\CORTES\\_identidade\\  (logo-gatopreto.png, avatar-<tema>.png 800x800, banner-<tema>.png 2560x1440, paleta.html)
Uso: python identidade.py"""
import json, sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

sys.stdout.reconfigure(encoding="utf-8")
RAIZ = Path(__file__).resolve().parents[1]
SAIDA = RAIZ / "_identidade"
SAIDA.mkdir(exist_ok=True)
FONTE = str(RAIZ / "_motor" / "fontes" / "Anton-Regular.ttf")
MARCA = "Gato Preto"
PRETO, BRANCO, GRAFITE = (17, 17, 17), (245, 243, 238), (30, 30, 27)

TEMAS = {  # pasta: (nome do tema, @, cor de destaque)
    "canal-tema1-negocios": ("Negócios", "@gatopretonegocios", "#3DDC84"),
    "canal-tema2-ciencia":  ("Ciência", "@gatopretociencia", "#3FB6FF"),
    "canal-tema3-misterio": ("Mistério", "@gatopretomisterio", "#A970FF"),
    "canal-tema4-historia": ("História", "@gatopretohistoria", "#E8B25A"),
    "canal-tema5-fe":       ("Fé", "@gatopretofe", "#FFD24A"),
    "canal-tema6-esporte":  ("Esporte", "@gatopretoesporte", "#FF7A3D"),
    "canal-tema7-politica": ("Política", "@gatopretopolitica", "#4FD1C5"),
    "canal-tema8-games":    ("Games", "@gatopreto.games", "#FF4FD8"),
}


def rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def gato(tam, cor_olho, fundo=None, contorno=None):
    """Cabeça de gato preto (silhueta) com olhos de fenda na cor do tema. Desenha 4x maior e reduz (borda lisa)."""
    S = tam * 4
    im = Image.new("RGBA", (S, S), fundo or (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    u = S / 100
    corpo = PRETO
    if contorno:   # aro claro em volta (pra aparecer em fundo escuro)
        for dx in (-1.6, 1.6):
            pass
        d.polygon([(17 * u, 50 * u), (20 * u, 9 * u), (44 * u, 30 * u)], fill=contorno)
        d.polygon([(83 * u, 50 * u), (80 * u, 9 * u), (56 * u, 30 * u)], fill=contorno)
        d.ellipse([12.5 * u, 24.5 * u, 87.5 * u, 91.5 * u], fill=contorno)
    # orelhas
    d.polygon([(20 * u, 48 * u), (22.5 * u, 13 * u), (43 * u, 31 * u)], fill=corpo)
    d.polygon([(80 * u, 48 * u), (77.5 * u, 13 * u), (57 * u, 31 * u)], fill=corpo)
    # cabeça
    d.ellipse([15 * u, 27 * u, 85 * u, 89 * u], fill=corpo)
    # olhos (amêndoa) + pupila de fenda
    for cx in (36, 64):
        d.ellipse([(cx - 9) * u, 51 * u, (cx + 9) * u, 63 * u], fill=cor_olho)
        d.ellipse([(cx - 1.6) * u, 51.5 * u, (cx + 1.6) * u, 62.5 * u], fill=corpo)
    # nariz
    d.polygon([(47 * u, 70 * u), (53 * u, 70 * u), (50 * u, 73.5 * u)], fill=(60, 60, 60))
    return im.resize((tam, tam), Image.LANCZOS)


def avatar(tema, cor, saida):
    """800x800: círculo na cor do tema, gato preto no meio (o YouTube corta em círculo)."""
    S = 800
    im = Image.new("RGB", (S, S), rgb(cor))
    g = gato(640, BRANCO)
    im.paste(g, ((S - 640) // 2, 70), g)
    im.save(saida)


def banner(tema, cor, handle, saida):
    """2560x1440 com tudo dentro da área segura central (1546x423, que aparece em qualquer tela)."""
    W, H = 2560, 1440
    im = Image.new("RGB", (W, H), GRAFITE)
    d = ImageDraw.Draw(im)
    c = rgb(cor)
    # faixa diagonal sutil na cor do tema
    d.polygon([(0, H * 0.80), (W, H * 0.66), (W, H * 0.70), (0, H * 0.84)], fill=tuple(int(v * 0.35) for v in c))
    g = gato(360, c)
    x0 = (W - 1546) // 2 + 40
    im.paste(g, (x0, (H - 360) // 2 - 10), g)
    f1 = ImageFont.truetype(FONTE, 150)
    f2 = ImageFont.truetype(FONTE, 96)
    f3 = ImageFont.truetype(FONTE, 44)
    tx = x0 + 400
    d.text((tx, H // 2 - 175), MARCA.upper(), font=f1, fill=BRANCO)
    d.text((tx, H // 2 - 5), tema.upper(), font=f2, fill=c)
    d.text((tx + 4, H // 2 + 115), f"OS MELHORES MOMENTOS DOS PODCASTS  ·  {handle}", font=f3, fill=(170, 166, 158))
    im.save(saida)


def logo_mini(cor, saida, tam=160):
    """Logo discreto pro canto do Short: círculo na cor do tema com o gato preto, fundo transparente."""
    S = tam * 4
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(im).ellipse([0, 0, S - 1, S - 1], fill=rgb(cor) + (255,))
    g = gato(int(S * 0.8), BRANCO)
    im.paste(g, (int(S * 0.1), int(S * 0.1)), g)
    im.resize((tam, tam), Image.LANCZOS).save(saida)


def logo_mestre(saida):
    W, H = 1600, 600
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    g = gato(520, (240, 191, 42), contorno=(245, 243, 238))
    im.paste(g, (20, 40), g)
    d = ImageDraw.Draw(im)
    d.text((600, 120), MARCA.upper(), font=ImageFont.truetype(FONTE, 230), fill=(245, 243, 238))
    d.text((606, 400), "CORTES DE PODCAST", font=ImageFont.truetype(FONTE, 80), fill=(240, 191, 42))
    im.save(saida)


def main():
    logo_mestre(SAIDA / "logo-gatopreto.png")
    resumo = {"marca": MARCA, "fonte": "Anton", "base": {"preto": "#111111", "branco": "#F5F3EE", "grafite": "#1E1E1B"},
              "canais": {}}
    for pasta, (tema, handle, cor) in TEMAS.items():
        slug = pasta.split("-", 2)[2]
        avatar(tema, cor, SAIDA / f"avatar-{slug}.png")
        banner(tema, cor, handle, SAIDA / f"banner-{slug}.png")
        cj = RAIZ / pasta / "canal.json"
        cfg = json.loads(cj.read_text(encoding="utf-8"))
        cfg["nome"] = f"{MARCA} {tema}"
        cfg["handle"] = handle
        est = cfg.setdefault("estilo", {})
        est["cor_destaque"] = cor
        est.pop("marca_rotulo", None)          # usuário preferiu só o logo, discreto (sem texto em cima do gancho)
        logo_mini(cor, SAIDA / f"logo-mini-{slug}.png")
        est["logo_marca"] = f"_identidade/logo-mini-{slug}.png"
        cj.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        resumo["canais"][pasta] = {"nome": cfg["nome"], "handle": handle, "cor": cor,
                                   "avatar": f"avatar-{slug}.png", "banner": f"banner-{slug}.png"}
        print(f"{cfg['nome']:<22} {handle:<22} {cor}", flush=True)
    (SAIDA / "identidade.json").write_text(json.dumps(resumo, ensure_ascii=False, indent=2), encoding="utf-8")
    # ícone do painel: o gato com olho amarelo
    ic = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
    ImageDraw.Draw(ic).rounded_rectangle([16, 16, 496, 496], radius=110, fill=(240, 191, 42))
    g = gato(430, BRANCO)
    ic.paste(g, (41, 40), g)
    pai = RAIZ / "_motor" / "painel"
    ic.save(pai / "icone.png")
    ic.save(pai / "icone.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("ok →", SAIDA)


if __name__ == "__main__":
    main()
