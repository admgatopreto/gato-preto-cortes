"""Vídeo de demonstração das animações de entrada de texto (legenda e gancho), no mesmo trecho de um Short.
Saída: F:\\CORTES\\_comparacao\\demo_animacoes.mp4 (cada animação ~5 s, com o nome em cima).
Uso: python demo_animacoes.py [canal:id:NN]"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "lib"))
sys.stdout.reconfigure(encoding="utf-8")
import render as R                       # noqa: E402
from util import RAIZ, run, ler_json     # noqa: E402

alvo = sys.argv[1] if len(sys.argv) > 1 else "canal-tema7-politica:nTIHNnYxQCA:03"
canal, vid, cid = alvo.split(":")
base = RAIZ / canal
ep = base / "episodios" / vid
cfg, plano = ler_json(base / "canal.json"), ler_json(ep / "cortes.json")
c = next(x for x in plano["cortes"] if x["id"] == cid)
palavras = R.aplicar_correcoes(R.palavras_da_transcricao(ler_json(ep / "transcricao.json")),
                               {**cfg.get("correcoes", {}), **plano.get("correcoes", {})})
_, ws = R.planejar_trechos(palavras, c, cfg.get("short", {}))
SAIDA = RAIZ / "_comparacao" / "demo"
SAIDA.mkdir(parents=True, exist_ok=True)
DUR = 5.0
trecho = SAIDA / "trecho.mkv"
run(["ffmpeg", "-y", "-v", "error", "-i", str(ep / "trabalho" / f"{cid}_short_bruto.mkv"), "-t", f"{DUR}",
     "-c:v", "copy", "-c:a", "copy", str(trecho)])
enq = R.planejar_enquadramento(trecho, {"falante_ativo": True})
ws5 = [w for w in ws if w["s"] < DUR - 0.2]
base_est = {**cfg.get("estilo", {}), "encerramento": True}

DEMOS = [("LEGENDA: POP (ATUAL)", {"animacao_legenda": "pop"}),
         ("LEGENDA: QUIQUE", {"animacao_legenda": "quique"}),
         ("LEGENDA: SUBIR", {"animacao_legenda": "subir"}),
         ("LEGENDA: DESLIZAR", {"animacao_legenda": "deslizar"}),
         ("LEGENDA: DESFOQUE", {"animacao_legenda": "desfoque"}),
         ("LEGENDA: GIRAR", {"animacao_legenda": "girar"}),
         ("LEGENDA: BRILHO", {"animacao_legenda": "brilho"}),
         ("LEGENDA: PALAVRA POR PALAVRA", {"animacao_legenda": "palavra"}),
         ("LEGENDA: FADE", {"animacao_legenda": "fade"}),
         ("GANCHO: POP", {"animacao_gancho": "pop"}),
         ("GANCHO: CAIR", {"animacao_gancho": "cair"}),
         ("GANCHO: REVELAR", {"animacao_gancho": "revelar"}),
         ("GANCHO: DIGITAR", {"animacao_gancho": "digitar"}),
         ("GANCHO: FADE", {"animacao_gancho": "fade"})]
partes = []
for k, (rotulo, opc) in enumerate(DEMOS, 1):
    est = {**base_est, **opc}
    ass = SAIDA / f"{k:02d}.ass"
    R.gerar_ass(ws5, ass, est, "short", f"{k}. {rotulo}", None, enq["planos"], DUR)
    mp4 = SAIDA / f"{k:02d}.mp4"
    R.render_short(trecho, enq, ass, mp4, encerramento=0.45)
    partes.append(mp4)
    print("ok", rotulo, flush=True)
lista = SAIDA / "lista.txt"
lista.write_text("".join(f"file '{p.name}'\n" for p in partes), encoding="utf-8")
final = RAIZ / "_comparacao" / "demo_animacoes.mp4"
run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", "lista.txt", "-c", "copy", str(final)], cwd=str(SAIDA))
print("PRONTO", final, flush=True)
