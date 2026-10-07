"""Remove episódios descartados (pasta do episódio + Shorts prontos + estado do painel) e registra em
_pesquisa/descartados.json, pra nenhuma busca futura pegar de novo. Fonte sem nenhum episódio restante sai de
`fontes` e vai pra `fontes_descartadas` (com o motivo); nos `candidatos` ganha "nao_usar".
Uso: python remover_episodios.py remocoes.json   ([{"canal","id","motivo","fonte_motivo"?,"retentar"?}])"""
import json, shutil, sys
from datetime import date
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8")
RAIZ = Path(__file__).resolve().parents[1]
REG = RAIZ / "_pesquisa" / "descartados.json"


def ler(p, padrao):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else padrao


def gravar(p, d):
    p.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


registro = ler(REG, [])
estado_p = RAIZ / "painel-estado.json"
estado = ler(estado_p, {"shorts": {}, "avisos": {}})
for r in json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")):
    canal_dir = RAIZ / r["canal"]
    ep = canal_dir / "episodios" / r["id"]
    info = ler(ep / "info.json", {})
    url = (info.get("channel_url") or "").rstrip("/")
    for k in [k for k in list(estado.get("shorts", {})) + list(estado.get("avisos", {})) if k.startswith(f"{r['canal']}/{r['id']}/")]:
        estado["shorts"].pop(k, None)
        estado["avisos"].pop(k, None)
    apagados = []
    for alvo in [ep] + sorted((canal_dir / "prontos").glob(f"*_{r['id']}")):
        if alvo.exists():
            shutil.rmtree(alvo)
            apagados.append(alvo.relative_to(RAIZ).as_posix())
    registro = [x for x in registro if x["id"] != r["id"]]
    registro.append({"id": r["id"], "canal": r["canal"], "fonte": info.get("channel"), "fonte_url": url,
                     "titulo": info.get("title"), "motivo": r["motivo"], "retentar": bool(r.get("retentar")),
                     "removido_em": date.today().isoformat()})
    # fonte sem episódio restante → fontes_descartadas
    cfg_p = canal_dir / "canal.json"
    cfg = ler(cfg_p, {})
    restantes = {ler(p, {}).get("channel_url", "").rstrip("/") for p in (canal_dir / "episodios").glob("*/info.json")}
    if r.get("fonte_motivo") and url and url not in restantes:
        fica, sai = [], []
        for f in cfg.get("fontes", []):
            (sai if (f.get("canal_url") or "").rstrip("/") == url else fica).append(f)
        for f in sai:
            f["motivo_descarte"] = r["fonte_motivo"]
        cfg["fontes"] = fica
        cfg.setdefault("fontes_descartadas", []).extend(sai)
        for c in cfg.get("candidatos", []):
            if (c.get("canal_url") or "").rstrip("/") == url:
                c["nao_usar"] = r["fonte_motivo"]
        gravar(cfg_p, cfg)
    print(f"{r['canal']} {r['id']}: apagado {apagados}")
gravar(REG, registro)
gravar(estado_p, estado)
print("registro:", REG, len(registro), "itens")
