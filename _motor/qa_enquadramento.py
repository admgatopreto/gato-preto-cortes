"""Auditoria automática do enquadramento dos Shorts JÁ renderizados: 1 quadro por segundo, detector de rosto no
próprio Short (9:16) e regras objetivas. Gera _pesquisa/qa_enquadramento.json e imprime os piores.
Problemas por quadro:
  cortado   rosto saindo pela borda esquerda/direita (mais de 20% da largura do rosto pra fora)
  pequeno   maior rosto com menos de 13% da largura do Short (plano aberto / janela miúda)
  gancho    centro do rosto acima de 17% da altura (fica atrás do gancho/logo)
  sem_rosto nenhum rosto (pode ser legítimo: slide, mão, objeto — só pesa se for muito tempo)
Uso: python qa_enquadramento.py [pasta prontos ou canal ...]   (sem argumento: todos os canais)"""
import json, sys
from pathlib import Path
import cv2, numpy as np

sys.stdout.reconfigure(encoding="utf-8")
RAIZ = Path(__file__).resolve().parents[1]
MODELO = RAIZ / "_motor" / "modelos" / "face_detection_yunet_2023mar.onnx"
LW, LH = 360, 640


def detector():
    return cv2.FaceDetectorYN.create(str(MODELO), "", (LW, LH), 0.7, 0.3, 5000)


def auditar_mp4(mp4, det, passo=1.0):
    """Lê 1 quadro/s em sequência com o ffmpeg (pular com OpenCV em vídeo 60 fps levava 20 s por Short)."""
    import subprocess
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(mp4)],
                               capture_output=True, text=True, creationflags=0x08000000).stdout.strip() or 0)
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-ss", "0.5", "-i", str(mp4), "-vf", f"fps={1 / passo},scale={LW}:{LH}",
                          "-f", "rawvideo", "-pix_fmt", "bgr24", "-"], stdout=subprocess.PIPE, creationflags=0x08000000)
    res, t = [], 0.5
    while True:
        buf = p.stdout.read(LW * LH * 3)
        if len(buf) < LW * LH * 3:
            break
        if t >= dur - 0.6:          # pula o encerramento (escurece no fim)
            t += passo
            continue
        f = np.frombuffer(buf, np.uint8).reshape(LH, LW, 3).copy()
        _, faces = det.detect(f)
        probs = []
        if faces is None or len(faces) == 0:
            probs.append("sem_rosto")
        else:
            x, y, w, h = max(faces, key=lambda r: r[2] * r[3])[:4]
            if w / LW < 0.13:
                probs.append("pequeno")
            fora = max(0 - x, (x + w) - LW, 0)
            if fora > 0.2 * w:
                probs.append("cortado")
            if (y + h / 2) / LH < 0.17:
                probs.append("gancho")
        res.append({"t": round(t, 1), "p": probs})
        t += passo
    p.wait()
    tot = max(1, len(res))
    cont = {k: sum(k in r["p"] for r in res) for k in ("cortado", "pequeno", "gancho", "sem_rosto")}
    # nota de problema: cortado/gancho pesam mais; sem rosto só conta acima de 40% do Short
    # sem rosto NÃO pesa: é imagem de apoio (foto, mapa, slide) — conteúdo legítimo, não erro de enquadramento
    nota = (2 * cont["cortado"] + 2 * cont["gancho"] + cont["pequeno"]) / tot
    trechos = [r["t"] for r in res if set(r["p"]) & {"cortado", "gancho", "pequeno"}]
    return {"dur": round(dur, 1), "amostras": tot, **{k: round(v / tot, 2) for k, v in cont.items()},
            "nota_problema": round(nota, 2), "tempos": trechos[:20]}


def auditar_pasta(saida, det):
    out = {}
    for mp4 in sorted((saida / "shorts").glob("*.mp4")):
        out[mp4.name[:2]] = {"arquivo": mp4.name, **auditar_mp4(mp4, det)}
    return out


def main():
    alvos = [Path(a) for a in sys.argv[1:]] or sorted(RAIZ.glob("canal-tema*"))
    pastas = []
    for a in alvos:
        a = a if a.is_absolute() else RAIZ / a
        pastas += [a] if (a / "shorts").exists() else sorted((a / "prontos").glob("*_*"))
    det = detector()
    arq = RAIZ / "_pesquisa" / "qa_enquadramento.json"
    tudo = json.loads(arq.read_text(encoding="utf-8")) if arq.exists() else {}
    for s in pastas:
        chave = f"{s.parents[1].name}/{s.name.split('_', 1)[1]}"
        tudo[chave] = auditar_pasta(s, det)
        ep_qa = s.parents[1] / "episodios" / s.name.split("_", 1)[1] / "qa.json"   # o painel lê daqui
        if ep_qa.parent.exists():
            ep_qa.write_text(json.dumps({k: {x: y for x, y in v.items() if x != "arquivo"} for k, v in tudo[chave].items()},
                                        ensure_ascii=False, indent=1), encoding="utf-8")
        ruins = {k: v for k, v in tudo[chave].items() if v["nota_problema"] >= 0.25}
        print(f"{chave}: {len(tudo[chave])} Shorts, {len(ruins)} com problema "
              + " ".join(f"{k}({v['nota_problema']})" for k, v in ruins.items()), flush=True)
    arq.write_text(json.dumps(tudo, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
