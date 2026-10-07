"""Radar de FONTES: procura no YouTube, tema por tema, podcasts que escrevem publicamente que liberam cortes
("cortes liberados", "pode cortar" etc.), audita cada canal e guarda a prova (texto + vídeo).
Resultado em _pesquisa/fontes_novas.json; o painel mostra na aba "Novos episódios" pra você adicionar com 1 clique.
Roda sozinho 1 vez por semana junto com o radar (ou: python fontes_liberadas.py)."""
import json, re, subprocess, sys, time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "lib"))
if sys.stdout:
    sys.stdout.reconfigure(encoding="utf-8")
from util import RAIZ                     # noqa: E402
from fonte import auditar                 # noqa: E402

SAIDA = RAIZ / "_pesquisa" / "fontes_novas.json"
SEM_JANELA = 0x08000000


def _busca(q, n=20):
    try:
        out = subprocess.run(["yt-dlp", "--flat-playlist", "-J", f"ytsearch{n}:{q}"], capture_output=True, text=True,
                             encoding="utf-8", timeout=180, creationflags=SEM_JANELA).stdout
        return json.loads(out).get("entries") or []
    except Exception:
        return []


def _url(e):
    return (e.get("channel_url") or (f"https://www.youtube.com/channel/{e['channel_id']}" if e.get("channel_id") else "")).rstrip("/")


def conhecidos():
    """URLs que já estão em algum canal (fontes, candidatos, descartadas) — não oferecer de novo."""
    urls = set()
    for cj in RAIZ.glob("canal-*/canal.json"):
        c = json.loads(cj.read_text(encoding="utf-8"))
        for lista in ("fontes", "candidatos", "fontes_descartadas"):
            urls |= {(x.get("canal_url") or "").rstrip("/") for x in c.get(lista, [])}
    return urls


def principal_do_corte(nome):
    """'Neurotônico Cortes [OFICIAL]' → acha o canal do podcast principal ('Neurotônico')."""
    base = re.sub(r"(?i)\b(cortes?|clips?|oficial|official)\b|\[.*?\]|[|\-–]", " ", nome or "")
    base = re.sub(r"(?i)\b(do|da|de|dos)\b", " ", base).strip()
    base = re.sub(r"\s+", " ", base)
    if len(base) < 3:
        return None
    for e in _busca(f"{base} podcast", 8):
        ch = (e.get("channel") or "")
        if base.lower().split()[0] in ch.lower() and not re.search(r"(?i)cortes?|clips?", ch):
            return {"canal": ch, "canal_url": _url(e)}
    return None


def main():
    nichos = json.loads((RAIZ / "_pesquisa" / "nichos.json").read_text(encoding="utf-8"))
    pasta_de = {p.name.split("-", 2)[2]: p.name for p in RAIZ.glob("canal-tema*")}
    anteriores = {x["url"]: x for x in (json.loads(SAIDA.read_text(encoding="utf-8")).get("itens", []) if SAIDA.exists() else [])}
    ja = conhecidos()
    achados = {}
    for nicho, qs in nichos.items():
        if nicho not in pasta_de:
            continue
        buscas = [f"{q} cortes liberados" for q in qs.get("podcast", [])[:3]] + [f"cortes liberados {nicho}"]
        for q in buscas:
            for e in _busca(q):
                u = _url(e)
                if u and u not in ja and u not in achados:
                    achados[u] = {"nome": e.get("channel") or e.get("uploader"), "nicho": nicho, "canal": pasta_de[nicho]}
            time.sleep(1)
    print(len(achados), "canais novos pra auditar", flush=True)
    itens = list(anteriores.values())
    for u, a in achados.items():
        if u in anteriores:
            continue
        try:
            r = auditar(u, n_episodios=5, duracao_min=60)
        except Exception:
            continue
        if r.get("status") not in ("LIBERADO", "CONDICIONAL"):
            continue
        prova = next(({"texto": t, "video": f"https://youtu.be/{ep['id']}" if ep["id"] != "SOBRE" else u + "/about"}
                      for ep in r.get("episodios", []) for t in ep.get("liberado", [])), {})
        nome = r.get("canal") or a["nome"]
        item = {"url": u, "nome": nome, "nicho": a["nicho"], "canal": a["canal"], "status": r["status"],
                "espera_horas": r.get("espera_horas"), "emails": r.get("emails", []), "prova": prova,
                "achado_em": datetime.now().strftime("%Y-%m-%d"), "decisao": None}
        if re.search(r"(?i)cortes?|clips?", nome or ""):   # canal oficial de cortes: oferece o podcast principal
            item["principal"] = principal_do_corte(nome)
        itens.append(item)
        print(f"★ {r['status']}: {nome} ({a['nicho']}) — {prova.get('texto', '')[:90]}", flush=True)
    SAIDA.write_text(json.dumps({"gerado_em": datetime.now().strftime("%Y-%m-%d %H:%M"), "itens": itens},
                                ensure_ascii=False, indent=1), encoding="utf-8")
    print("fontes novas:", sum(1 for i in itens if not i.get("decisao")), "→", SAIDA)


if __name__ == "__main__":
    main()
