"""Audita (descrição + Sobre + e-mail) todo podcast confirmado que entraria no top 15 de algum nicho e ainda não foi auditado.
Uso: python auditar_faltantes.py ..\\_pesquisa\\nichos_resultado.json"""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "lib"))
sys.path.insert(0, str(Path(__file__).parent))
sys.stdout.reconfigure(encoding="utf-8")
from util import salvar_json
from fonte import auditar
from pesquisar_nicho import idioma

arq = Path(sys.argv[1])
dados = json.loads(arq.read_text(encoding="utf-8"))
feitos = {}
for v in dados.values():
    for cid, c in v["podcasts"].items():
        if "auditoria" in c:
            feitos[cid] = c["auditoria"]
for nicho, v in dados.items():
    pods = sorted(v["podcasts"].items(), key=lambda kv: -(kv[1]["inscritos"] or 0))
    conf = [(cid, c) for cid, c in pods if c.get("perfil", {}).get("longos", 0) >= 3
            and idioma(c["perfil"].get("sobre", "")) != "outro"][:18]
    for cid, c in conf:
        if "auditoria" in c:
            continue
        if cid in feitos:
            c["auditoria"] = feitos[cid]
        else:
            try:
                r = auditar(c["url"], n_episodios=3)
                c["auditoria"] = {"status": r["status"], "espera_horas": r.get("espera_horas"), "emails": r.get("emails", []),
                                  "trechos": list(dict.fromkeys(t for e in r.get("episodios", [])
                                                                for t in e["proibido"] + e["liberado"]))[:2]}
            except Exception as ex:
                c["auditoria"] = {"status": f"ERRO {str(ex)[:80]}"}
            feitos[cid] = c["auditoria"]
            print(f"{c['auditoria']['status']:<11} [{nicho}] {c['canal']} {c['auditoria'].get('emails')}", flush=True)
        salvar_json(arq, dados)
print("FIM", flush=True)
