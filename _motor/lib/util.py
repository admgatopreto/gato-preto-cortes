"""Utilidades comuns: ffmpeg/ffprobe, tempo, json, caminhos dos canais."""
import json, os, re, subprocess, sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]          # F:\CORTES
MOTOR = RAIZ / "_motor"
FONTES_DIR = MOTOR / "fontes"
MODELOS_DIR = MOTOR / "modelos"
MODELO_CANAL = MOTOR / "modelo-canal"


def log(*a):
    print(*a, flush=True)


def run(cmd, **kw):
    """Roda comando e devolve stdout (texto utf-8). Lança erro com stderr se falhar."""
    if os.name == "nt":
        kw.setdefault("creationflags", 0x08000000)   # CREATE_NO_WINDOW: sem janela piscando quando roda pelo atalho/agendador
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", **kw)
    if p.returncode != 0:
        raise RuntimeError(f"Falhou: {' '.join(map(str, cmd))[:300]}\n{p.stderr[-2000:]}")
    return p.stdout


def duracao(arquivo):
    return float(run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                      "-of", "default=nw=1:nk=1", str(arquivo)]).strip())


def info_video(arquivo):
    out = run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
               "stream=width,height,r_frame_rate", "-of", "json", str(arquivo)])
    s = json.loads(out)["streams"][0]
    n, d = s["r_frame_rate"].split("/")
    return int(s["width"]), int(s["height"]), float(n) / float(d)


def tem_nvenc():
    try:
        out = run(["ffmpeg", "-hide_banner", "-f", "lavfi", "-i", "nullsrc=s=256x256:d=0.1",
                   "-c:v", "h264_nvenc", "-f", "null", "-"])
        return True
    except Exception:
        return False


def args_encoder_video(qualidade="alta"):
    if tem_nvenc():
        return ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "20" if qualidade == "alta" else "24",
                "-b:v", "0", "-pix_fmt", "yuv420p"]
    return ["-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p"]


def para_seg(t):
    """'01:02:03.5' | '02:03' | 123.4 -> segundos"""
    if isinstance(t, (int, float)):
        return float(t)
    partes = [float(x) for x in str(t).strip().replace(",", ".").split(":")]
    s = 0.0
    for p in partes:
        s = s * 60 + p
    return s


def fmt_tempo(s, ms=False):
    s = max(0.0, s)
    h, r = divmod(s, 3600)
    m, r = divmod(r, 60)
    if ms:
        return f"{int(h):02d}:{int(m):02d}:{r:06.3f}"
    return f"{int(h):02d}:{int(m):02d}:{int(r):02d}"


def ler_json(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def salvar_json(p, dados):
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)


def slug_arquivo(txt, maxlen=70):
    txt = re.sub(r'[<>:"/\\|?*\n\r\t]', "", txt).strip()
    txt = re.sub(r"\s+", " ", txt)
    return txt[:maxlen].rstrip(" .")


def pasta_canal(canal):
    p = RAIZ / canal
    if not (p / "canal.json").exists():
        sys.exit(f"Canal '{canal}' não existe em {RAIZ} (falta canal.json). Use: cortes novo-canal {canal}")
    return p


def config_canal(canal):
    return ler_json(pasta_canal(canal) / "canal.json")
