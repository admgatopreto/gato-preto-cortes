"""Gera icone.ico / icone.png do painel (retângulo amarelo de Short com botão de play)."""
from pathlib import Path
from PIL import Image, ImageDraw

AQUI = Path(__file__).resolve().parent
N = 512
im = Image.new("RGBA", (N, N), (0, 0, 0, 0))
d = ImageDraw.Draw(im)
d.rounded_rectangle([16, 16, N - 16, N - 16], radius=110, fill=(30, 30, 27, 255))
# "Short" vertical amarelo
w, h = 230, 380
x0, y0 = (N - w) // 2, (N - h) // 2
d.rounded_rectangle([x0, y0, x0 + w, y0 + h], radius=36, fill=(240, 191, 42, 255))
# play
cx, cy, r = N // 2 + 12, N // 2, 70
d.polygon([(cx - r * 0.75, cy - r), (cx - r * 0.75, cy + r), (cx + r, cy)], fill=(30, 30, 27, 255))
# barrinhas de "corte" (tesoura de edição) embaixo
for i, larg in enumerate((150, 100)):
    yy = y0 + h - 70 + i * 30
    d.rounded_rectangle([x0 + 40, yy, x0 + 40 + larg, yy + 14], radius=7, fill=(30, 30, 27, 200))
im.save(AQUI / "icone.png")
im.save(AQUI / "icone.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("ok")
