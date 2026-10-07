"""Prepara um lote de episódios: registra a fonte no canal.json (com o status da auditoria), baixa e transcreve.
Baixa o próximo enquanto transcreve o atual (download em thread, GPU numa fila só).
Uso: python lote.py lote.json [nichos_resultado.json]
lote.json: [{"canal": "canal-tema1-negocios", "fonte": "...", "fonte_url": "...", "id": "..."}]"""
import json, queue, sys, threading, time, traceback
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "lib"))
sys.stdout.reconfigure(encoding="utf-8")
from util import RAIZ, log, ler_json, salvar_json
from fonte import baixar
from transcrever import transcrever

lote = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
auditorias = {}
if len(sys.argv) > 2:
    for v in json.loads(Path(sys.argv[2]).read_text(encoding="utf-8")).values():
        for c in v["podcasts"].values():
            if "auditoria" in c:
                auditorias[c["url"].rstrip("/")] = c["auditoria"]


def registrar_fonte(item):
    p = RAIZ / item["canal"] / "canal.json"
    cfg = ler_json(p)
    url = item["fonte_url"].rstrip("/")
    if any(f.get("canal_url", "").rstrip("/") == url for f in cfg.get("fontes", [])):
        return
    a = auditorias.get(url, {})
    cfg.setdefault("fontes", []).append({
        "canal": item["fonte"], "canal_url": url, "status": a.get("status", "NÃO AUDITADO"),
        "espera_horas": a.get("espera_horas"), "emails": a.get("emails", []),
        "evidencia": "", "obs": "preparado antes da autorização — pedir por e-mail antes de publicar"})
    salvar_json(p, cfg)


fila = queue.Queue()


def baixador():
    for item in lote:
        try:
            registrar_fonte(item)
            pasta = baixar(item["canal"], f"https://youtu.be/{item['id']}", forcar=True)
            fila.put((item, pasta))
        except BaseException as ex:      # sys.exit do baixar também cai aqui
            log(f"ERRO download {item['id']}: {ex}")
    fila.put(None)


threading.Thread(target=baixador, daemon=True).start()
t0 = time.time()
while True:
    x = fila.get()
    if x is None:
        break
    item, pasta = x
    if (pasta / "transcricao.json").exists():
        log(f"já transcrito: {item['canal']} {item['id']}")
        continue
    try:
        log(f"\n=== TRANSCREVENDO {item['canal']} / {item['fonte']} / {item['id']}")
        transcrever(pasta)
        log(f"PRONTO {item['canal']} {item['id']}")
    except Exception:
        log(f"ERRO transcrição {item['id']}:\n{traceback.format_exc()[-800:]}")
log(f"FIM em {(time.time() - t0) / 60:.0f} min")
