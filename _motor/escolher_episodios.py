"""Escolhe o episódio longo mais recente (40 min–4h) de cada fonte, pulando os já baixados.
Uso: python escolher_episodios.py fontes_lote.json lote.json
fontes_lote.json: {"canal-tema1-negocios": ["https://www.youtube.com/channel/...", ...], ...}
Saída lote.json: [{"canal": ..., "fonte": ..., "id": ..., "titulo": ..., "duracao_min": ...}]"""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "lib"))
sys.stdout.reconfigure(encoding="utf-8")
from util import run, salvar_json, RAIZ

fontes = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
lote = []
for canal, urls in fontes.items():
    for url in urls:
        ents = []
        for aba in ("/videos", "/streams"):
            try:
                d = json.loads(run(["yt-dlp", "--extractor-args", "youtube:lang=pt", "--flat-playlist",
                                    "-I", "1:15", "-J", url.rstrip("/") + aba]))
                ents += [(e, d.get("channel") or d.get("title")) for e in (d.get("entries") or [])]
            except Exception:
                pass
        ja = {p.name for p in (RAIZ / canal / "episodios").glob("*")}
        cands = [(e, nome) for e, nome in ents if 2400 <= (e.get("duration") or 0) <= 4 * 3600
                 and e.get("id") not in ja and e.get("availability") in (None, "public")
                 and e.get("live_status") not in ("is_live", "is_upcoming")]
        if not cands:
            print(f"!! {canal}: nenhum episódio longo em {url}")
            continue
        e, nome = cands[0]  # mais recente (ordem da aba); /videos vem antes de /streams
        lote.append({"canal": canal, "fonte": nome, "fonte_url": url, "id": e["id"], "titulo": e.get("title"),
                     "duracao_min": round(e["duration"] / 60)})
        print(f"{canal:<22} {nome[:28]:<28} {e['id']}  {round(e['duration']/60):>4} min  {e.get('title', '')[:70]}")
salvar_json(sys.argv[2], lote)
print(f"{len(lote)} episódios, {sum(x['duracao_min'] for x in lote) / 60:.1f} h de áudio")
