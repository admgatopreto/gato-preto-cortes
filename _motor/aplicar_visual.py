"""Liga o visual padrão (identidade Gato Preto) em todos os canais e, com --rerender, põe todos os episódios
cortados na fila de render de novo (toca o cortes.json; a fila_render.py pega sozinha).
Uso: python aplicar_visual.py [--rerender]"""
import json, os, sys, time
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8")
RAIZ = Path(__file__).resolve().parents[1]

PADRAO = {   # visual padrão dos Shorts (definido nos testes de 06/10/2026)
    "falante_ativo": True, "zoom_enfase": True, "barra_progresso": True, "gancho_animado": True,
    "animacao_legenda": "quique", "animacao_gancho": "pop", "nome_convidado": False,   # tirado: confunde com várias pessoas
    "censurar_palavroes": True, "encerramento": True,
}
for cj in sorted(RAIZ.glob("canal-tema*/canal.json")) + [RAIZ / "_motor" / "modelo-canal" / "canal.json"]:
    cfg = json.loads(cj.read_text(encoding="utf-8"))
    cfg.setdefault("estilo", {}).update(PADRAO)
    cfg["estilo"].pop("marca_rotulo", None)   # trocado pelo logo discreto (logo_marca)
    cj.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    print("visual padrão →", cfg.get("nome"))
if "--rerender" in sys.argv:
    n = 0
    for cortes in sorted(RAIZ.glob("canal-tema*/episodios/*/cortes.json")):
        if (cortes.parent / "NAO CORTAR - motivo.txt").exists():
            continue
        os.utime(cortes, None)
        n += 1
    print(f"{n} episódios na fila de render")
