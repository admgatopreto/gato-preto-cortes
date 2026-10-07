"""Fábrica de canais de cortes — linha de comando.

  cortes novo-canal <canal> --nome "Nome do Canal"
  cortes auditar <url do canal do podcast> [--canal <canal> --adicionar]
  cortes baixar <canal> <url do episódio> [--forcar]
  cortes transcrever <canal> <id do episódio>
  cortes preparar <canal> <url do episódio>         (baixar + transcrever)
  cortes renderizar <canal> <id> [--so 01,03] [--formatos short,horizontal]
  cortes status <canal>
  cortes painel                                      (abre o painel de progresso no navegador)
"""
import argparse, os, shutil, sys, time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "lib"))
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from util import (RAIZ, MODELO_CANAL, log, ler_json, salvar_json, pasta_canal, config_canal,
                  slug_arquivo, fmt_tempo)


def cmd_novo_canal(a):
    destino = RAIZ / a.canal
    if destino.exists():
        sys.exit(f"Já existe: {destino}")
    shutil.copytree(MODELO_CANAL, destino)
    cfg = ler_json(destino / "canal.json")
    cfg["nome"] = a.nome or a.canal
    cfg["criado_em"] = datetime.now().strftime("%Y-%m-%d")
    salvar_json(destino / "canal.json", cfg)
    for sub in ("episodios", "prontos"):
        (destino / sub).mkdir(exist_ok=True)
    log("Canal criado:", destino)


def cmd_auditar(a):
    from fonte import auditar
    r = auditar(a.url, n_episodios=a.n)
    log(f"\n{r.get('canal')}  →  {r['status']}  ({r.get('episodios_com_liberacao', 0)} liberam / "
        f"{r.get('episodios_com_proibicao', 0)} proíbem / {r.get('episodios_lidos', 0)} lidos)"
        + (f"  | espera {r['espera_horas']}h" if r.get("espera_horas") else "")
        + (f"  | contato: {', '.join(r['emails'])}" if r.get("emails") else ""))
    for e in r["episodios"]:
        for t in e["proibido"]:
            log("   ✖", t[:200])
        for t in e["liberado"]:
            log("   ✔", t[:200])
    if a.canal:
        p = pasta_canal(a.canal)
        hist = p / "fontes_auditoria.json"
        dados = ler_json(hist) if hist.exists() else []
        dados.append(r)
        salvar_json(hist, dados)
        if a.adicionar:
            cfg = config_canal(a.canal)
            cfg["fontes"] = [f for f in cfg.get("fontes", []) if f.get("canal_url") != r["canal_url"]]
            evid = next((t for e in r["episodios"] for t in (e["proibido"] or e["liberado"])), "")
            cfg["fontes"].append({"canal": r.get("canal"), "canal_url": r["canal_url"], "status": r["status"],
                                  "espera_horas": r.get("espera_horas"), "evidencia": evid,
                                  "auditado_em": r.get("auditado_em")})
            salvar_json(p / "canal.json", cfg)
            log(f"Fonte gravada em canal.json como {r['status']}.")


def cmd_baixar(a):
    from fonte import baixar
    return baixar(a.canal, a.url, a.forcar)


def cmd_transcrever(a, pasta=None):
    from transcrever import transcrever
    pasta = pasta or pasta_canal(a.canal) / "episodios" / a.id
    transcrever(pasta)


def cmd_preparar(a):
    pasta = cmd_baixar(a)
    if not (pasta / "transcricao.json").exists():
        cmd_transcrever(a, pasta)
    log(f"\nPronto pra curadoria: {pasta / 'leitura.txt'}\nPróximo: escrever {pasta / 'cortes.json'} e rodar renderizar.")


def cmd_renderizar(a):
    import render as R, pacote as P
    cfg = config_canal(a.canal)
    base = pasta_canal(a.canal)
    ep = base / "episodios" / a.id
    plano = ler_json(ep / "cortes.json")
    info = ler_json(ep / "info.json")
    palavras = R.palavras_da_transcricao(ler_json(ep / "transcricao.json"))
    # correções de transcrição: do canal (nomes fixos) + do episódio (nomes do convidado etc.)
    palavras = R.aplicar_correcoes(palavras, {**cfg.get("correcoes", {}), **plano.get("correcoes", {})})
    est = cfg.get("estilo", {})
    so = set(a.so.split(",")) if a.so else None
    forcar_fmt = a.formatos.split(",") if a.formatos else None
    existentes = sorted((base / "prontos").glob(f"*_{a.id}"))   # re-render reaproveita a pasta do episódio
    saida = existentes[-1] if existentes else base / "prontos" / f"{datetime.now():%Y-%m-%d}_{a.id}"
    trab = ep / "trabalho"
    trab.mkdir(exist_ok=True)
    from fonte import fonte_do_video
    fonte = fonte_do_video(cfg, info)
    liberado = bool(fonte and fonte.get("status") == "LIBERADO")
    saida.mkdir(parents=True, exist_ok=True)
    aviso = saida / "NAO PUBLICAR - sem autorizacao da fonte.txt"
    if not liberado:
        aviso.write_text(
            f"Fonte: {info.get('channel')} — status {(fonte or {}).get('status', 'não cadastrada')}.\n"
            "Cortes preparados só pra uso interno. Publicar SOMENTE depois que a fonte autorizar\n"
            "(e-mail respondido) e o status no canal.json virar LIBERADO.\n", encoding="utf-8")
        log("⚠ Fonte sem autorização: saída marcada como NÃO PUBLICAR.")
    elif aviso.exists():
        aviso.unlink()
    relatorio = []
    for c in plano["cortes"]:
        if so and c["id"] not in so:
            continue
        t0 = time.time()
        formatos = forcar_fmt or c.get("formatos", ["short"])
        log(f"\n[{c['id']}] {c['titulo']}  ({c['inicio']} → {c['fim']})  {formatos}")
        credito = _preencher_credito(cfg, c, info)
        for fmt in formatos:
            cfmt = cfg.get(fmt, {})
            trechos, ws = R.planejar_trechos(palavras, c, cfmt)
            bruto = trab / f"{c['id']}_{fmt}_bruto.mkv"
            dur = R.montar_bruto(ep / "video.mp4", trechos, bruto)
            cr = R.resolver_ancoras(palavras, c)
            original = R.para_seg(cr["fim"]) - R.para_seg(cr["inicio"])
            nome = f"{c['id']} - {slug_arquivo(c.get('titulo_short') if fmt == 'short' and c.get('titulo_short') else c['titulo'])}"
            pasta_fmt = saida / ("shorts" if fmt == "short" else "horizontal")
            pasta_fmt.mkdir(parents=True, exist_ok=True)
            ass = trab / f"{c['id']}_{fmt}.ass"
            mp4 = pasta_fmt / f"{nome}.mp4"
            if fmt == "short":
                # visual novo (liga por canal em canal.json → estilo): falante_ativo, zoom_enfase, barra_progresso,
                # gancho_animado, nome_convidado, censurar_palavroes. Por corte (cortes.json): esconder, cortar_embaixo
                enq = R.planejar_enquadramento(bruto, {"falante_ativo": est.get("falante_ativo"),
                                                      "janela": plano.get("janela_original")})
                salvar_json(trab / f"{c['id']}_enquadramento.json", {k: v for k, v in enq.items() if k != "amostras"})
                R.gerar_ass(ws, ass, est, "short", c.get("gancho"), credito, enq["planos"], dur, nome=c.get("convidado"))
                cor = est.get("cor_destaque", "#FFD400").lstrip("#")
                R.render_short(bruto, enq, ass, mp4,
                               zooms=R.zooms_de_enfase(ws, est.get("zoom_nivel", 1.12)) if est.get("zoom_enfase") else None,
                               barra=(int(cor[4:6], 16), int(cor[2:4], 16), int(cor[0:2], 16)) if est.get("barra_progresso") else None,
                               esconder=c.get("esconder"), cortar_embaixo=c.get("cortar_embaixo"),
                               encerramento=0.45 if est.get("encerramento") else None,
                               logo=(RAIZ / est["logo_marca"]) if est.get("logo_marca") else None)
                modos = {}
                for p in enq["planos"]:
                    modos[p.get("modo")] = modos.get(p.get("modo"), 0) + p["t1"] - p["t0"]
                extra = ", ".join(f"{k} {v:.0f}s" for k, v in modos.items())
            else:
                R.gerar_ass(ws, ass, est, "horizontal", None, credito, None, dur)
                R.render_horizontal(bruto, ass, mp4)
                enq = R.planejar_enquadramento(bruto) if not (trab / f"{c['id']}_enquadramento.json").exists() else None
                thumbs = saida / "thumbnails" / "referencias"
                thumbs.mkdir(parents=True, exist_ok=True)
                if enq:
                    for k, t in enumerate(R.escolher_quadros_thumb(bruto, enq)):
                        P.extrair_quadro(bruto, t, thumbs / f"{c['id']}_{'abc'[k]}.jpg")
                extra = ""
            d, probs = P.verificar_video(mp4, dur, fmt)
            # texto exato que foi pra legenda — revisar erro de transcrição antes de publicar
            (saida / "verificacao").mkdir(exist_ok=True)
            (saida / "verificacao" / f"{c['id']}_{fmt}_legenda.txt").write_text(
                " ".join(w["w"] for w in ws), encoding="utf-8")
            txt, probs_txt = P.texto_upload(cfg, c, info, fmt)
            mp4.with_suffix(".txt").write_text(txt, encoding="utf-8")
            verif = saida / "verificacao"
            verif.mkdir(exist_ok=True)
            P.mosaico(mp4, verif / f"{c['id']}_{fmt}.jpg")
            probs += probs_txt
            relatorio.append((c["id"], fmt, nome, d, original, extra, probs))
            log(f"   {fmt}: {d:.1f}s (trecho original {original:.0f}s, {len(trechos)} pedaços) {extra} "
                + ("OK" if not probs else "⚠ " + "; ".join(probs)))
        log(f"   ({time.time() - t0:.0f}s)")
    _relatorio(saida, a.id, info, relatorio)
    # auditoria automática do enquadramento dos Shorts que acabaram de sair (vai pro painel como aviso)
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        import qa_enquadramento as QA
        det, qa_arq = QA.detector(), ep / "qa.json"
        qa = ler_json(qa_arq) if qa_arq.exists() else {}
        for cid, fmt, nome_arq, *_ in relatorio:
            if fmt == "short":
                qa[cid] = QA.auditar_mp4(saida / "shorts" / f"{nome_arq}.mp4", det)
        salvar_json(qa_arq, qa)
        ruins = [f"{c} ({v['nota_problema']})" for c, v in sorted(qa.items()) if v["nota_problema"] >= 0.25]
        log("Enquadramento: " + (("conferir " + ", ".join(ruins)) if ruins else "OK em todos"))
    except Exception as ex:
        log(f"auditoria de enquadramento falhou: {ex}")
    log(f"\nSaída: {saida}")
    if os.name == "nt" and not os.environ.get("CORTES_NAO_ABRIR"):
        os.startfile(saida)


def _preencher_credito(cfg, c, info):
    modelo = cfg.get("estilo", {}).get("credito", "{podcast}")
    if not modelo:
        return None
    return modelo.replace("{podcast}", c.get("podcast") or info.get("channel", "")).replace(
        "{convidado}", c.get("convidado", "")).strip(" •|-")


def _relatorio(saida, vid, info, rel):
    linhas = [f"# {info.get('title')}", f"Episódio: https://youtu.be/{vid} — {info.get('channel')}", "",
              "| # | formato | arquivo | duração | trecho orig. | enquadramento | problemas |",
              "|---|---|---|---|---|---|---|"]
    for i, f, n, d, o, e, p in rel:
        linhas.append(f"| {i} | {f} | {n} | {d:.1f}s | {o:.0f}s | {e} | {'; '.join(p) or 'OK'} |")
    arq = saida / "relatorio.md"
    arq.write_text("\n".join(linhas) + "\n", encoding="utf-8")


def cmd_palavras(a):
    """Mostra as palavras com tempo num trecho — pra acertar início/fim de corte."""
    from util import para_seg
    ep = pasta_canal(a.canal) / "episodios" / a.id
    t0, t1 = para_seg(a.inicio), para_seg(a.fim)
    linha, ult = [], None
    for s in ler_json(ep / "transcricao.json")["segmentos"]:
        for w in s["words"]:
            if t0 <= w["s"] <= t1:
                if ult is not None and w["s"] - ult > 0.6:
                    linha.append(f"  ‖{w['s'] - ult:.1f}s‖")
                linha.append(f"{w['w']}@{fmt_tempo(w['s'], True)[3:] if w['s'] < 3600 else fmt_tempo(w['s'], True)}")
                ult = w["e"]
    log(" ".join(linha))


def cmd_permissao_fala(a):
    """Procura na transcrição falas liberando/proibindo cortes (ex.: 'pode fazer corte')."""
    import re
    from fonte import PADROES_LIBERADO, PADROES_PROIBIDO, PADRAO_ESPERA
    ep = pasta_canal(a.canal) / "episodios" / a.id
    segs = ler_json(ep / "transcricao.json")["segmentos"]
    extra = [r"pode(m)?\s+fazer\s+(o\s+|os\s+)?cortes?", r"regra\s+de\s+\d+\s*horas"]
    achou = False
    for i, s in enumerate(segs):
        ctx = " ".join(x["t"] for x in segs[max(0, i - 1):i + 2])
        for tipo, pads in (("PROÍBE", PADROES_PROIBIDO), ("LIBERA", PADROES_LIBERADO + extra)):
            if any(re.search(p, s["t"], re.I) for p in pads):
                achou = True
                log(f"[{fmt_tempo(s['s'])}] {tipo}: {ctx[:300]}")
    if not achou:
        log("Nenhuma fala sobre cortes encontrada.")


def cmd_validar(a):
    """Resolve as âncoras de todos os cortes e mostra duração final, começo e fim — sem renderizar."""
    import render as R
    cfg = config_canal(a.canal)
    ep = pasta_canal(a.canal) / "episodios" / a.id
    plano = ler_json(ep / "cortes.json")
    palavras = R.aplicar_correcoes(R.palavras_da_transcricao(ler_json(ep / "transcricao.json")),
                                   {**cfg.get("correcoes", {}), **plano.get("correcoes", {})})
    erros = 0
    for c in plano["cortes"]:
        for fmt in c.get("formatos", ["short"]):
            try:
                trechos, ws = R.planejar_trechos(palavras, c, cfg.get(fmt, {}))
            except Exception as ex:
                erros += 1
                log(f"✖ {c['id']} {fmt}: {ex}")
                continue
            dur = sum(b - a_ for a_, b in trechos)
            alvo = cfg.get(fmt, {}).get("duracao_alvo_seg", [0, 99999])
            aviso = "" if alvo[0] - 5 <= dur <= max(alvo[1] + 15, 175 if fmt == "short" else alvo[1]) else "  ⚠ fora da duração alvo"
            txt = [w["w"] for w in ws]
            log(f"✔ {c['id']} {fmt:<10} {dur:6.1f}s  «{' '.join(txt[:7])} … {' '.join(txt[-7:])}»{aviso}")
    log(f"{len(plano['cortes'])} cortes, {erros} erro(s)")


def cmd_status(a):
    base = pasta_canal(a.canal)
    cfg = config_canal(a.canal)
    log(f"{cfg['nome']}  —  nicho: {cfg.get('nicho')}")
    log("Fontes:")
    for f in cfg.get("fontes", []):
        log(f"  {f['status']:<11} {f.get('canal')}  espera={f.get('espera_horas') or 0}h")
    log("Episódios:")
    for ep in sorted((base / "episodios").glob("*")):
        etapas = [n for n, arq in (("baixado", "video.mp4"), ("transcrito", "transcricao.json"),
                                    ("curado", "cortes.json")) if (ep / arq).exists()]
        prontos = list((base / "prontos").glob(f"*_{ep.name}"))
        info = ep / "info.json"
        titulo = ler_json(info).get("title", "") if info.exists() else ""
        log(f"  {ep.name}  [{' > '.join(etapas)}{' > renderizado' if prontos else ''}]  {titulo[:60]}")


def main():
    ap = argparse.ArgumentParser(description="Fábrica de canais de cortes")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("novo-canal"); s.add_argument("canal"); s.add_argument("--nome")
    s = sub.add_parser("auditar"); s.add_argument("url"); s.add_argument("--canal")
    s.add_argument("--adicionar", action="store_true"); s.add_argument("-n", type=int, default=6)
    for nome in ("baixar", "preparar"):
        s = sub.add_parser(nome); s.add_argument("canal"); s.add_argument("url"); s.add_argument("--forcar", action="store_true")
    s = sub.add_parser("transcrever"); s.add_argument("canal"); s.add_argument("id")
    s = sub.add_parser("renderizar"); s.add_argument("canal"); s.add_argument("id")
    s.add_argument("--so"); s.add_argument("--formatos")
    s = sub.add_parser("status"); s.add_argument("canal")
    s = sub.add_parser("palavras"); s.add_argument("canal"); s.add_argument("id"); s.add_argument("inicio"); s.add_argument("fim")
    s = sub.add_parser("permissao-fala"); s.add_argument("canal"); s.add_argument("id")
    s = sub.add_parser("validar"); s.add_argument("canal"); s.add_argument("id")
    s = sub.add_parser("painel"); s.add_argument("--porta", default="8765"); s.add_argument("--nao-abrir", action="store_true")
    a = ap.parse_args()
    if a.cmd == "painel":
        sys.argv = ["servidor.py", "--porta", a.porta] + (["--nao-abrir"] if a.nao_abrir else [])
        sys.path.insert(0, str(Path(__file__).parent / "painel"))
        import servidor
        return servidor.main()
    {"novo-canal": cmd_novo_canal, "auditar": cmd_auditar, "baixar": cmd_baixar, "preparar": cmd_preparar,
     "transcrever": cmd_transcrever, "renderizar": cmd_renderizar, "status": cmd_status,
     "palavras": cmd_palavras, "permissao-fala": cmd_permissao_fala, "validar": cmd_validar}[a.cmd](a)


if __name__ == "__main__":
    main()
