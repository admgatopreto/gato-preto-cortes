"""Audita em lote uma lista de podcasts candidatos (nome -> busca o canal no YouTube -> auditoria).
Uso: python pesquisar_fontes.py candidatos.txt saida.json
candidatos.txt: uma linha por podcast "nicho | nome de busca"."""
import json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "lib"))
sys.stdout.reconfigure(encoding="utf-8")
from util import run, salvar_json
from fonte import auditar


def achar_canal(nome):
    out = run(["yt-dlp", "--flat-playlist", "-I", "1:1", "-J",
               f"https://www.youtube.com/results?search_query={nome.replace(' ', '+')}&sp=EgIQAg%253D%253D"])
    e = (json.loads(out).get("entries") or [None])[0]
    if not e:
        return None, None, None
    return e.get("channel") or e.get("title"), e.get("url"), e.get("channel_follower_count")


linhas = [l.split("|", 1) for l in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines() if "|" in l]
saida = Path(sys.argv[2])
res = json.loads(saida.read_text(encoding="utf-8")) if saida.exists() else []
feitos = {r["busca"] for r in res}
for nicho, nome in linhas:
    nicho, nome = nicho.strip(), nome.strip()
    if nome in feitos:
        continue
    try:
        canal, url, inscritos = achar_canal(nome)
        r = auditar(url, n_episodios=4) if url else {"status": "CANAL NÃO ACHADO", "episodios": []}
    except Exception as ex:
        canal, url, inscritos, r = None, None, None, {"status": f"ERRO {str(ex)[:120]}", "episodios": []}
    trechos = list(dict.fromkeys(t for e in r.get("episodios", []) for t in e["proibido"] + e["liberado"]))[:3]
    res.append({"nicho": nicho, "busca": nome, "canal": canal, "url": url, "inscritos": inscritos,
                "status": r["status"], "espera_horas": r.get("espera_horas"), "trechos": trechos, "emails": r.get("emails", []),
                "ultimo_ep": (r.get("episodios") or [{}])[0].get("data")})
    salvar_json(saida, res)
    print(f"{r['status']:<12} {nicho:<12} {canal}  ({inscritos})", flush=True)
