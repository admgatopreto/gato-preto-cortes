"""Textos de upload (Título/Descrição/Tags), referências de thumbnail e verificação objetiva."""
import subprocess
from pathlib import Path
from util import run, duracao, info_video, log


def _preencher(modelo, dados):
    out = modelo
    for k, v in dados.items():
        out = out.replace("{" + k + "}", str(v or ""))
    return out.strip()


def texto_upload(cfg, corte, ep_info, formato):
    pub = cfg.get("publicacao", {})
    dados = {
        "descricao": corte.get("descricao", ""),
        "podcast": corte.get("podcast") or ep_info.get("channel", ""),
        "episodio_titulo": ep_info.get("title", ""),
        "episodio_url": ep_info.get("webpage_url") or f"https://youtu.be/{ep_info['id']}",
        "canal_nome": cfg.get("nome", ""),
        "convidado": corte.get("convidado", ""),
    }
    if formato == "short":
        titulo = corte.get("titulo_short") or corte["titulo"]
        if "#shorts" not in titulo.lower() and len(titulo) + 8 <= 100:
            titulo += " #Shorts"
        desc = _preencher(pub.get("descricao_short", "{descricao}\n\n🎙️ Episódio completo: {episodio_url}\n#Shorts"), dados)
    else:
        titulo = corte["titulo"]
        desc = _preencher(pub.get("descricao_horizontal", "{descricao}\n\n🎙️ Episódio completo: {episodio_url}"), dados)
    tags = list(dict.fromkeys(corte.get("tags", []) + pub.get("tags_fixas", [])))
    while len(",".join(tags)) > 480:
        tags.pop()
    problemas = []
    if len(titulo) > 100:
        problemas.append(f"título com {len(titulo)} caracteres (máx 100)")
    if len(desc) > 4900:
        problemas.append("descrição longa demais")
    if "episódio completo" not in desc.lower() and dados["episodio_url"] not in desc:
        problemas.append("descrição sem link do episódio completo (crédito obrigatório)")
    txt = f"TÍTULO\n{titulo}\n---\nDESCRIÇÃO\n{desc}\n---\nTAGS (campo Tags do YouTube, não a descrição)\n{', '.join(tags)}\n"
    return txt, problemas


def mosaico(video, saida, n=12, colunas=4, largura=270):
    d = duracao(video)
    W, H, fps = info_video(video)
    passo = max(1, int(d * fps / n))
    run(["ffmpeg", "-y", "-v", "error", "-i", str(video), "-vf",
         f"select='not(mod(n\\,{passo}))',scale={largura}:-2,tile={colunas}x{(n + colunas - 1) // colunas}:padding=4",
         "-frames:v", "1", "-update", "1", str(saida)])


def verificar_video(video, dur_esperada, formato):
    probs = []
    W, H, _ = info_video(video)
    alvo = (1080, 1920) if formato == "short" else (1920, 1080)
    if (W, H) != alvo:
        probs.append(f"resolução {W}x{H}, esperado {alvo[0]}x{alvo[1]}")
    d = duracao(video)
    if abs(d - dur_esperada) > 0.25:
        probs.append(f"duração {d:.2f}s, esperado {dur_esperada:.2f}s")
    a = run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=codec_name",
             "-of", "csv=p=0", str(video)]).strip()
    if not a:
        probs.append("sem áudio")
    if formato == "short" and d > 180:
        probs.append(f"Short com {d:.0f}s (limite do YouTube 3 min)")
    return d, probs


def extrair_quadro(video, t, saida):
    run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.2f}", "-i", str(video), "-frames:v", "1",
         "-q:v", "2", str(saida)])
