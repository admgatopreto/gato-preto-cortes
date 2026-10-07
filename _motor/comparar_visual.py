"""Renderiza Shorts já prontos no VISUAL NOVO e monta um vídeo lado a lado (atual × novo) pra comparar.
Saída: F:\\CORTES\\_comparacao\\  (novo_*.mp4 e lado_a_lado_*.mp4).  Não mexe nos Shorts originais.
Uso: python comparar_visual.py canal:id:NN [canal:id:NN ...]"""
import json, shutil, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "lib"))
sys.path.insert(0, str(Path(__file__).parent))
sys.stdout.reconfigure(encoding="utf-8")
import render as R                                    # noqa: E402
from util import RAIZ, run, ler_json, FONTES_DIR      # noqa: E402
import cortes as K                                    # noqa: E402

VISUAL_NOVO = {}   # usa o padrão do canal.json (aplicar_visual.py)
OPC_ENQ = {"falante_ativo": True}
SAIDA = RAIZ / "_comparacao"
SAIDA.mkdir(exist_ok=True)


def um(canal, vid, corte_id):
    base = RAIZ / canal
    ep = base / "episodios" / vid
    cfg = ler_json(base / "canal.json")
    plano = ler_json(ep / "cortes.json")
    info = ler_json(ep / "info.json")
    c = next(x for x in plano["cortes"] if x["id"] == corte_id)
    palavras = R.aplicar_correcoes(R.palavras_da_transcricao(ler_json(ep / "transcricao.json")),
                                   {**cfg.get("correcoes", {}), **plano.get("correcoes", {})})
    est = {**cfg.get("estilo", {}), **VISUAL_NOVO}
    trechos, ws = R.planejar_trechos(palavras, c, cfg.get("short", {}))
    bruto = ep / "trabalho" / f"{corte_id}_short_bruto.mkv"
    dur = R.montar_bruto(ep / "video.mp4", trechos, bruto) if not bruto.exists() else R.duracao(bruto)
    enq = R.planejar_enquadramento(bruto, {**OPC_ENQ, "janela": plano.get("janela_original")})
    ass = ep / "trabalho" / f"{corte_id}_short_v2.ass"
    R.gerar_ass(ws, ass, est, "short", c.get("gancho"), K._preencher_credito(cfg, c, info), enq["planos"], dur,
                nome=c.get("convidado"))
    cor = est.get("cor_destaque", "#FFD400").lstrip("#")
    barra = (int(cor[4:6], 16), int(cor[2:4], 16), int(cor[0:2], 16))   # BGR
    nome = f"{canal.split('-', 2)[2]}_{vid}_{corte_id}"
    novo = SAIDA / f"novo_{nome}.mp4"
    if "--so-juntar" not in sys.argv or not novo.exists():
      R.render_short(bruto, enq, ass, novo, zooms=R.zooms_de_enfase(ws), barra=barra,
                     esconder=c.get("esconder"), cortar_embaixo=c.get("cortar_embaixo"), encerramento=0.45,
                     logo=(RAIZ / est["logo_marca"]) if est.get("logo_marca") else None)
    atual = sorted((sorted((base / "prontos").glob(f"*_{vid}"))[-1] / "shorts").glob(f"{corte_id} - *.mp4"))[0]
    lado = SAIDA / f"lado_a_lado_{nome}.mp4"
    # fonte copiada pra pasta de saída e usada com caminho relativo (o "F:" quebra o filtro do ffmpeg no Windows)
    if not (SAIDA / "Anton-Regular.ttf").exists():
        shutil.copy(FONTES_DIR / "Anton-Regular.ttf", SAIDA / "Anton-Regular.ttf")
    rot = lambda txt: (f",drawtext=text={txt}:fontfile=Anton-Regular.ttf:fontsize=34:fontcolor=white:box=1:"
                       f"boxcolor=black@0.6:boxborderw=10:x=(w-tw)/2:y=h-60")
    run(["ffmpeg", "-y", "-v", "error", "-i", str(atual), "-i", str(novo), "-filter_complex",
         f"[0:v]scale=540:960{rot('ATUAL')}[a];[1:v]scale=540:960{rot('NOVO')}[b];[a][b]hstack=inputs=2[v]",
         "-map", "[v]", "-map", "1:a", "-c:v", "libx264", "-crf", "21", "-preset", "veryfast", "-c:a", "aac", "-shortest",
         str(lado)], cwd=str(SAIDA))
    modos = {}
    for q in enq["planos"]:
        chave = "falante" if q.get("falante") else q.get("modo")
        modos[chave] = modos.get(chave, 0) + q["t1"] - q["t0"]
    print(f"OK {nome}: {dur:.0f}s | enquadramento {', '.join(f'{k} {v:.0f}s' for k, v in modos.items())} | "
          f"esconder: {c.get('esconder')} cortar_embaixo: {c.get('cortar_embaixo')} | zooms: {len(R.zooms_de_enfase(ws)) - 1}", flush=True)
    return lado


if __name__ == "__main__":
    for arg in [a for a in sys.argv[1:] if not a.startswith("--")]:
        canal, vid, corte_id = arg.split(":")
        try:
            um(canal, vid, corte_id)
        except Exception as e:
            import traceback
            print("ERRO", arg, traceback.format_exc()[-1500:], flush=True)
