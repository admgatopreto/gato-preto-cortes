"""Mapeia os maiores canais de um nicho no YouTube BR.
Para cada nicho: busca canais por várias consultas, confirma formato podcast (episódios longos)
e separa PODCASTS (fontes possíveis) de CANAIS DE CORTES (concorrência). Depois audita permissão
das maiores fontes (descrição + aba Sobre + e-mail de contato).

Uso: python pesquisar_nicho.py nichos.json saida.json
nichos.json: {"negocios": {"podcast": ["podcast empreendedorismo", ...], "cortes": ["cortes empreendedorismo", ...]}, ...}
Retoma de onde parou (cache na própria saída)."""
import json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "lib"))
sys.stdout.reconfigure(encoding="utf-8")
from util import run, salvar_json
from fonte import auditar

FILTRO_CANAL = "EgIQAg%253D%253D"
TOP_AUDITAR = 10


def buscar_canais(q, n=20):
    try:
        # SEM lang=pt: em pt o YouTube devolve "6,75 mi" e o yt-dlp lê 675 inscritos
        out = run(["yt-dlp", "--flat-playlist", "-I", f"1:{n}", "-J",
                   f"https://www.youtube.com/results?search_query={q.replace(' ', '+')}&sp={FILTRO_CANAL}"])
    except Exception:
        return []
    res = []
    for e in json.loads(out).get("entries") or []:
        res.append({"canal": e.get("channel") or e.get("title"), "url": e.get("url") or e.get("channel_url"),
                    "id": e.get("channel_id") or e.get("id"), "inscritos": e.get("channel_follower_count") or 0})
    return res


MARCAS_PT = [" você", " não ", "ção", "ções", "ões", " pra ", " do ", " da ", " dos ", " das ", " nosso", " canal ",
             " inscreva", " vídeos", " também", " são ", " é ", " um ", " uma ", " com ", " para ", " em ", " no ",
             " na ", " os ", " amigos", " contato", "história", " vida", " aí", " tio", " fé "]
MARCAS_OUTRAS = [" el ", " los ", " las ", "ción", " the ", " and ", " of ", " le ", " les ", " und ", " y ", " del ",
                 " for ", " official", "featuring", " with ", " your ", " our "]


def idioma(texto):
    t = " " + (texto or "").lower() + " "
    pt = sum(t.count(m) for m in MARCAS_PT)
    outr = sum(t.count(m) for m in MARCAS_OUTRAS)
    if pt == 0 and outr == 0:
        return "?"
    return "pt" if pt >= outr else "outro"


def perfil_videos(url, n=15):
    """Quantos dos últimos n vídeos são longos (>=40 min), duração mediana, inscritos reais e idioma (pelo Sobre)."""
    d, ents = {}, []
    for aba in ("/videos", "/streams"):      # podcast grande costuma gravar ao vivo (episódios ficam em /streams)
        try:
            dd = json.loads(run(["yt-dlp", "--flat-playlist", "-I", f"1:{n}", "-J", url.rstrip("/") + aba]))
        except Exception:
            continue
        d = d or dd
        ents += dd.get("entries") or []
        if sum((e.get("duration") or 0) >= 2400 for e in ents) >= 3:
            break
    if not d:
        return {"longos": 0, "lidos": 0, "mediana_min": 0, "idioma": "?"}
    durs = sorted((e.get("duration") or 0) for e in ents)
    sobre = d.get("description") or ""
    return {"longos": sum(x >= 2400 for x in durs), "lidos": len(durs),
            "mediana_min": round(durs[len(durs) // 2] / 60) if durs else 0,
            "inscritos": d.get("channel_follower_count"), "idioma": idioma(sobre), "sobre": sobre[:300]}


def main():
    nichos = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    saida = Path(sys.argv[2])
    dados = json.loads(saida.read_text(encoding="utf-8")) if saida.exists() else {}
    for nicho, consultas in nichos.items():
        d = dados.setdefault(nicho, {"podcasts": {}, "cortes": {}, "consultas_feitas": []})
        if d.get("versao") != 2:          # v1 tinha inscritos errados: refaz buscas, mantém auditorias
            d["consultas_feitas"] = []
            for grupo in ("podcasts", "cortes"):
                for c in d[grupo].values():
                    c.pop("perfil", None)
            d["versao"] = 2
        for tipo in ("podcast", "cortes"):
            alvo = d["podcasts" if tipo == "podcast" else "cortes"]
            for q in consultas[tipo]:
                if q in d["consultas_feitas"]:
                    continue
                for c in buscar_canais(q):
                    if not c["id"]:
                        continue
                    existente = d["podcasts"].get(c["id"]) or d["cortes"].get(c["id"])
                    if existente:
                        existente["inscritos"] = c["inscritos"] or existente["inscritos"]
                        continue
                    eh_cortes = "corte" in (c["canal"] or "").lower()
                    if tipo == "podcast" and eh_cortes:
                        d["cortes"][c["id"]] = c        # busca de podcast que devolveu canal de cortes
                    elif tipo == "cortes" and not eh_cortes:
                        continue                         # busca de cortes que devolveu outra coisa
                    else:
                        alvo[c["id"]] = c
                d["consultas_feitas"].append(q)
                salvar_json(saida, dados)
                print(f"[{nicho}] '{q}' → {len(d['podcasts'])} podcasts / {len(d['cortes'])} cortes", flush=True)
        # confirmar formato podcast nos maiores (episódios longos) — só os 25 maiores por inscritos
        maiores = sorted(d["podcasts"].values(), key=lambda c: -(c["inscritos"] or 0))[:30]
        for c in maiores:
            if "perfil" not in c:
                c["perfil"] = perfil_videos(c["url"])
                if c["perfil"].get("inscritos"):
                    c["inscritos"] = c["perfil"]["inscritos"]
                salvar_json(saida, dados)
        maiores.sort(key=lambda c: -(c["inscritos"] or 0))
        # auditar permissão das maiores fontes confirmadas (podcast de verdade e em português)
        fontes = [c for c in maiores if c.get("perfil", {}).get("longos", 0) >= 3
                  and c["perfil"].get("idioma") != "outro"][:TOP_AUDITAR]
        for c in fontes:
            if "auditoria" not in c:
                try:
                    r = auditar(c["url"], n_episodios=3)
                    c["auditoria"] = {"status": r["status"], "espera_horas": r.get("espera_horas"),
                                      "emails": r.get("emails", []),
                                      "trechos": list(dict.fromkeys(t for e in r.get("episodios", [])
                                                                    for t in e["proibido"] + e["liberado"]))[:2]}
                except Exception as ex:
                    c["auditoria"] = {"status": f"ERRO {str(ex)[:80]}"}
                salvar_json(saida, dados)
                print(f"   {c['auditoria']['status']:<11} {c['canal']} ({c['inscritos']}) {c['auditoria'].get('emails')}", flush=True)
        # perfil dos maiores canais de cortes (concorrência)
        for c in sorted(d["cortes"].values(), key=lambda c: -(c["inscritos"] or 0))[:12]:
            if "perfil" not in c:
                c["perfil"] = perfil_videos(c["url"], n=20)
                if c["perfil"].get("inscritos"):
                    c["inscritos"] = c["perfil"]["inscritos"]
                salvar_json(saida, dados)
    print("FIM", flush=True)


if __name__ == "__main__":
    main()
