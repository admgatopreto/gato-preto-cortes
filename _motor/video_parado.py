"""Detecta episódio de "imagem parada" (podcast só áudio com capa fixa): compara quadros espalhados pelo vídeo.
Uso: python video_parado.py <video.mp4> [...]   → imprime % de quadros quase iguais ao anterior e a variação média.
Também importável: medir(caminho) -> {"parado": bool, "iguais": 0..1, "variacao": float}"""
import sys
import cv2
import numpy as np


def medir(caminho, amostras=60):
    cap = cv2.VideoCapture(str(caminho))
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    if n <= 0:
        return None
    quadros = []
    for i in range(amostras):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(n * (i + 0.5) / amostras))
        ok, f = cap.read()
        if ok:
            quadros.append(cv2.resize(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY), (64, 36), interpolation=cv2.INTER_AREA).astype(np.float32))
    cap.release()
    if len(quadros) < 5:
        return None
    difs = [float(np.mean(np.abs(a - b))) for a, b in zip(quadros, quadros[1:])]
    iguais = sum(d < 2.0 for d in difs) / len(difs)
    return {"parado": iguais >= 0.8, "iguais": round(iguais, 2), "variacao": round(float(np.median(difs)), 1)}


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    for c in sys.argv[1:]:
        print(medir(c), c, flush=True)
