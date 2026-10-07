"""Transcrição com timestamps por palavra (faster-whisper na GPU)."""
import time
from pathlib import Path
from gpu import preparar_cuda, tem_gpu
from util import log, run, salvar_json, fmt_tempo, duracao

MODELO = "large-v3-turbo"


def transcrever(pasta_ep, modelo=MODELO, idioma="pt"):
    pasta_ep = Path(pasta_ep)
    video = pasta_ep / "video.mp4"
    wav = pasta_ep / "audio16k.wav"
    if not wav.exists():
        run(["ffmpeg", "-y", "-v", "error", "-i", str(video), "-ac", "1", "-ar", "16000", str(wav)])
    gpu = tem_gpu()
    preparar_cuda()
    from faster_whisper import WhisperModel
    m = WhisperModel(modelo, device="cuda" if gpu else "cpu",
                     compute_type="int8_float16" if gpu else "int8")
    total = duracao(wav)
    log(f"Transcrevendo {total/60:.0f} min com {modelo} ({'GPU' if gpu else 'CPU'})...")
    t0 = time.time()
    hot = termos_do_episodio(pasta_ep)
    segs = None
    if gpu:
        try:   # modo em lote: 2-3x mais rápido na GPU
            from faster_whisper import BatchedInferencePipeline
            segs, _ = BatchedInferencePipeline(model=m).transcribe(
                str(wav), language=idioma, word_timestamps=True, batch_size=8, hotwords=hot,
                vad_parameters={"min_silence_duration_ms": 400}, beam_size=5)
            log("  (modo em lote)")
        except Exception as ex:
            log(f"  modo em lote indisponível ({str(ex)[:80]}), usando o normal")
            segs = None
    if segs is None:
        segs, _ = m.transcribe(str(wav), language=idioma, word_timestamps=True, vad_filter=True,
                               hotwords=hot, vad_parameters={"min_silence_duration_ms": 400}, beam_size=5,
                               condition_on_previous_text=False)
    saida, ult = [], 0
    for s in segs:
        palavras = [{"w": w.word.strip(), "s": round(w.start, 3), "e": round(w.end, 3), "p": round(w.probability, 3)}
                    for w in (s.words or []) if w.word.strip()]
        saida.append({"s": round(s.start, 3), "e": round(s.end, 3), "t": s.text.strip(), "words": palavras})
        if s.end - ult > 300:
            ult = s.end
            log(f"  {fmt_tempo(s.end)} / {fmt_tempo(total)}  ({time.time()-t0:.0f}s)")
    salvar_json(pasta_ep / "transcricao.json", {"modelo": modelo, "segmentos": saida})
    escrever_leitura(pasta_ep, saida)
    wav.unlink(missing_ok=True)
    log(f"OK em {(time.time()-t0)/60:.1f} min — {sum(len(s['words']) for s in saida)} palavras")


def termos_do_episodio(pasta_ep):
    """Nomes próprios do título/descrição viram 'hotwords' — Whisper erra menos nome de convidado/podcast."""
    import json, re
    info = Path(pasta_ep) / "info.json"
    if not info.exists():
        return None
    i = json.loads(info.read_text(encoding="utf-8"))
    texto = f"{i.get('title', '')} {i.get('channel', '')} {(i.get('description') or '')[:600]}"
    nomes = re.findall(r"\b[A-ZÀ-Ý][a-zà-ÿA-ZÀ-Ý]+(?:\s+[A-ZÀ-Ý][a-zà-ÿA-ZÀ-Ý]+)*", texto)
    vistos = list(dict.fromkeys(n for n in nomes if len(n) > 3 and not n.isupper()))
    return ", ".join(vistos[:40]) or None


def escrever_leitura(pasta_ep, segs, bloco=20.0):
    """Texto compacto pra leitura/curadoria: parágrafos de ~20s com o tempo de início."""
    linhas, buf, ini = [], [], None
    for s in segs:
        if ini is None:
            ini = s["s"]
        buf.append(s["t"])
        if s["e"] - ini >= bloco or s["t"].endswith(("?", "!")) and s["e"] - ini >= bloco / 2:
            linhas.append(f"[{fmt_tempo(ini)}] {' '.join(buf)}")
            buf, ini = [], None
    if buf:
        linhas.append(f"[{fmt_tempo(ini)}] {' '.join(buf)}")
    (Path(pasta_ep) / "leitura.txt").write_text("\n".join(linhas), encoding="utf-8")
