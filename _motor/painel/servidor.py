"""Painel da fábrica de cortes — http://localhost:8765

Lê o progresso direto das pastas de F:\\CORTES (vídeo baixado, transcrição, cortes.json, marcadores de render,
pasta prontos). O que não dá pra saber pelas pastas (Short aprovado/reprovado, publicado, avisos de qualidade)
fica em F:\\CORTES\\painel-estado.json. Status de permissão da fonte é gravado no próprio canal.json (o motor usa).

Uso: cortes painel   (ou python servidor.py [--porta 8765] [--nao-abrir])
"""
import copy, hashlib, json, mimetypes, os, re, shutil, subprocess, sys, threading, time, webbrowser
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

AQUI = Path(__file__).resolve().parent
RAIZ = AQUI.parents[1]
ESTADO = RAIZ / "painel-estado.json"
TRAVA = threading.Lock()
if sys.stdout:                      # pythonw (atalho da área de trabalho) não tem console
    sys.stdout.reconfigure(encoding="utf-8")
else:
    sys.stdout = sys.stderr = open(AQUI / "painel.log", "a", encoding="utf-8", buffering=1)

PALAVROES = re.compile(r"\b(caralho|porra|foda|foda-se|fodeu|puta|puto|putaria|merda|cacete|buceta|arrombado|bosta)\b", re.I)
STATUS_FONTE = ["SEM MENÇÃO", "CONDICIONAL", "E-MAIL ENVIADO", "LIBERADO", "NEGADO", "PROIBIDO"]
ULTIMO_PEDIDO = time.time()
FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
LIMITE_FFMPEG = threading.Semaphore(2)


# ---------- leitura (com cache por data de modificação: só relê arquivo que mudou) ----------
_CACHE = {}


def _cacheado(p, carregar):
    p = Path(p)
    try:
        st = p.stat()
    except OSError:
        _CACHE.pop(str(p), None)
        raise
    chave = (st.st_mtime_ns, st.st_size)
    item = _CACHE.get(str(p))
    if item and item[0] == chave:
        return item[1]
    dado = carregar(p)
    _CACHE[str(p)] = (chave, dado)
    return dado


def ler(p, padrao=None):
    try:
        return _cacheado(p, lambda q: json.loads(q.read_text(encoding="utf-8")))
    except Exception:
        return padrao


def ler_texto(p, padrao=""):
    try:
        return _cacheado(p, lambda q: q.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return padrao


def gravar(p, dados):
    tmp = Path(str(p) + ".tmp")
    tmp.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)


def estado(fresco=False):
    e = ler(ESTADO, {}) or {}
    if fresco:
        e = copy.deepcopy(e)     # pra gravar sem mexer no cache
    e.setdefault("shorts", {})
    e.setdefault("avisos", {})
    return e


def versao(obj):
    if isinstance(obj, dict) and "atualizado" in obj:
        obj = {k: v for k, v in obj.items() if k != "atualizado"}
    return hashlib.md5(json.dumps(obj, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:12]


def poster(canal, vid, corte):
    """Quadro do Short (gerado uma vez com ffmpeg e guardado em episodios/<id>/trabalho/poster_NN.jpg)."""
    saida = saida_do_ep(RAIZ / canal, vid)
    mp4 = sorted((saida / "shorts").glob(f"{corte} - *.mp4")) if saida else []
    if not mp4:
        return None
    jpg = RAIZ / canal / "episodios" / vid / "trabalho" / f"poster_{corte}.jpg"
    if jpg.exists() and jpg.stat().st_mtime >= mp4[0].stat().st_mtime:
        return jpg
    with LIMITE_FFMPEG:
        if jpg.exists() and jpg.stat().st_mtime >= mp4[0].stat().st_mtime:
            return jpg
        jpg.parent.mkdir(exist_ok=True)
        tmp = jpg.with_name(jpg.stem + ".tmp.jpg")
        subprocess.run([FFMPEG, "-y", "-v", "error", "-ss", "2", "-i", str(mp4[0]), "-frames:v", "1",
                        "-vf", "scale=360:-2", "-q:v", "5", str(tmp)],
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=60)
        if tmp.exists():
            os.replace(tmp, jpg)
    return jpg if jpg.exists() else None


def aquecer_posters():
    """Em segundo plano, gera os quadros que faltam (a 1ª abertura de cada episódio fica instantânea)."""
    time.sleep(3)
    for canal_dir in canais():
        for ep in sorted((canal_dir / "episodios").glob("*")):
            plano = ler(ep / "cortes.json")
            if not plano or (ep / "trabalho" / ".renderizando").exists():
                continue
            for c in plano.get("cortes", []):
                try:
                    poster(canal_dir.name, ep.name, c["id"])
                except Exception as e:
                    print("poster", ep.name, c.get("id"), e, flush=True)


def rel(p):
    return Path(p).relative_to(RAIZ).as_posix()


def canais():
    return sorted(p for p in RAIZ.glob("canal-*") if (p / "canal.json").exists())


def fonte_do_info(cfg, info):
    url = (info.get("channel_url") or "").rstrip("/")
    for f in cfg.get("fontes", []):
        u = (f.get("canal_url") or "").rstrip("/")
        if u and u == url:
            return f
    for f in cfg.get("fontes", []):   # fallback pelo nome
        if (f.get("canal") or "").lower() == (info.get("channel") or "").lower():
            return f
    return None


def saida_do_ep(canal_dir, vid):
    ex = sorted((canal_dir / "prontos").glob(f"*_{vid}"))
    return ex[-1] if ex else None


def ler_relatorio(saida):
    linhas = {}
    arq = saida / "relatorio.md" if saida else None
    if not arq or not arq.exists():
        return linhas
    for l in ler_texto(arq).splitlines():
        c = [x.strip() for x in l.strip().strip("|").split("|")]
        if len(c) == 7 and re.fullmatch(r"\d+", c[0]):
            linhas[(c[0], c[1])] = {"duracao": c[3], "enquadramento": c[5], "problemas": "" if c[6] == "OK" else c[6]}
    return linhas


def progresso_render(ep, total):
    log = ep / "render.log"
    if not log.exists():
        return {"feitos": 0, "total": total, "atual": None}
    t = ler_texto(log)
    feitos = len(re.findall(r"^\s+short: ", t, re.M))
    atual = re.findall(r"^\[(\d+)\] (.*?)  \(", t, re.M)
    return {"feitos": feitos, "total": total, "atual": (atual[-1][0] + " — " + atual[-1][1]) if atual else None,
            "desde": datetime.fromtimestamp((ep / "trabalho" / ".renderizando").stat().st_mtime).strftime("%H:%M")
            if (ep / "trabalho" / ".renderizando").exists() else None}


def _seg(hms):
    h, m, s = (int(x) for x in hms.split(":"))
    return h * 3600 + m * 60 + s


def progresso_preparo(ep, info, etapa):
    """Download: tamanho do arquivo parcial vs. ~0,45 GB por hora (1080p H.264) — aproximado.
    Transcrição: última linha 'HH:MM:SS / HH:MM:SS (Ns)' do log → % e quanto falta."""
    dur = info.get("duration") or 0
    if etapa == "download":
        tam = sum(f.stat().st_size for f in ep.iterdir() if f.is_file() and (".part" in f.name or ".f" in f.name))
        if not dur or not tam:
            return {"pct": 0, "texto": "começando o download"}
        pct = min(99, round(100 * tam / (dur / 3600 * 0.45e9)))
        return {"pct": pct, "texto": f"baixando · {tam / 1e9:.2f} GB (aprox. {pct}%)"}
    logs = sorted((RAIZ / "_pesquisa").glob(f"preparo_{ep.name}.log")) + sorted((RAIZ / "_pesquisa").glob("lote*.log"))
    for lg in logs:
        txt = ler_texto(lg)
        if ep.name not in txt and not lg.name.startswith("preparo_"):
            continue
        m = re.findall(r"(\d\d:\d\d:\d\d) / (\d\d:\d\d:\d\d)\s+\((\d+)s\)", txt[-4000:])
        if m:
            feito, total, gasto = _seg(m[-1][0]), _seg(m[-1][1]), int(m[-1][2])
            pct = min(99, round(100 * feito / max(1, total)))
            falta = gasto * (total - feito) / max(1, feito) / 60
            return {"pct": pct, "texto": f"transcrevendo · {m[-1][0]} de {m[-1][1]}",
                    "falta": f"falta ~{max(1, round(falta))} min"}
    return {"pct": 0, "texto": "transcrição começando (carregando o modelo)"}


def ler_txt_upload(p):
    """Separa o .txt do Short em título, descrição e tags."""
    if not p.exists():
        return {}
    partes = ler_texto(p).split("\n---\n")
    out = {}
    for parte in partes:
        cab, _, corpo = parte.strip().partition("\n")
        cab = cab.upper()
        if cab.startswith("TÍTULO"):
            out["titulo"] = corpo.strip()
        elif cab.startswith("DESCRIÇÃO"):
            out["descricao"] = corpo.strip()
        elif cab.startswith("TAGS"):
            out["tags"] = corpo.strip()
    return out


def aviso_qa(ep, cid):
    """Resultado da auditoria automática de enquadramento (qa.json, gravado no fim de cada render)."""
    q = (ler(ep / "qa.json", {}) or {}).get(cid)
    if not q or q.get("nota_problema", 0) < 0.25:
        return []
    partes = [f"{nome} {int(q[ch] * 100)}% do tempo" for ch, nome in
              (("cortado", "rosto cortado na borda"), ("gancho", "rosto atrás do gancho"), ("pequeno", "rosto pequeno"))
              if q.get(ch, 0) >= 0.1]
    if q.get("sem_rosto", 0) > 0.4:
        partes.append(f"sem rosto {int(q['sem_rosto'] * 100)}% do tempo")
    quando = ", ".join(f"{t:.0f}s" for t in q.get("tempos", [])[:6])
    return [{"nivel": "atencao", "texto": "Enquadramento (auditoria automática): " + "; ".join(partes or ["conferir"])
             + (f" — aos {quando}" if quando else "")}]


def episodio(canal_dir, cfg, ep, est, detalhe=False):
    vid = ep.name
    info = ler(ep / "info.json", {}) or {}
    fonte = fonte_do_info(cfg, info)
    d = {"id": vid, "titulo": info.get("title") or vid, "podcast": info.get("channel") or "",
         "url": info.get("webpage_url") or f"https://youtu.be/{vid}", "duracao_s": info.get("duration"),
         "fonte_status": (fonte or {}).get("status", "não cadastrada"),
         "liberado": bool(fonte and fonte.get("status") == "LIBERADO"), "pasta": rel(ep)}
    auto = next((x for x in est.get("fila_preparo", []) if x["id"] == vid), None)
    if auto:
        d["auto"] = {k: auto.get(k) for k in ("status", "erro", "resumo", "inicio_cur", "fim")}
    motivo = ep / "NAO CORTAR - motivo.txt"
    if motivo.exists():
        d.update(etapa="descartado", motivo=ler_texto(motivo).strip().splitlines()[0])
        return d
    trab, cj = ep / "trabalho", ep / "cortes.json"
    plano = ler(cj) if cj.exists() else None
    if not (ep / "video.mp4").exists():
        d["etapa"] = "download"
        d["baixando"] = any(ep.glob("*.part"))
        d["prep"] = progresso_preparo(ep, info, "download")
        return d
    if not (ep / "transcricao.json").exists():
        d["etapa"] = "transcricao"
        d["prep"] = progresso_preparo(ep, info, "transcricao")
        return d
    if plano is None:
        d["etapa"] = "curadoria"
        return d
    cortes = [c for c in plano.get("cortes", []) if "short" in c.get("formatos", ["short"])]
    saida = saida_do_ep(canal_dir, vid)
    d["n_shorts"] = len(cortes)
    d["saida"] = rel(saida) if saida else None
    marca, trava = trab / ".renderizado", trab / ".renderizando"
    chave = f"{canal_dir.name}/{vid}/"
    contagem = {"aprovado": 0, "reprovado": 0, "publicado": 0}
    for c in cortes:
        s = est["shorts"].get(chave + c["id"], {})
        if s.get("aprovacao") in contagem:
            contagem[s["aprovacao"]] += 1
        if s.get("publicado"):
            contagem["publicado"] += 1
    d.update(aprovados=contagem["aprovado"], reprovados=contagem["reprovado"], publicados=contagem["publicado"])
    if trava.exists() and time.time() - trava.stat().st_mtime < 3 * 3600:
        d["etapa"] = "render"
        d["progresso"] = progresso_render(ep, len(cortes))
    elif not marca.exists() or marca.stat().st_mtime < cj.stat().st_mtime:
        d["etapa"] = "fila_render"
    elif contagem["aprovado"] + contagem["reprovado"] < len(cortes):
        d["etapa"] = "conferencia"
    elif contagem["aprovado"] and contagem["publicado"] < contagem["aprovado"]:
        d["etapa"] = "publicacao"
    else:
        d["etapa"] = "concluido"
    if not detalhe:
        return d
    # ---- detalhe dos Shorts ----
    relat = ler_relatorio(saida)
    lista = []
    for c in cortes:
        k = chave + c["id"]
        s = est["shorts"].get(k, {})
        item = {"corte": c["id"], "titulo_short": c.get("titulo_short") or c.get("titulo"), "gancho": c.get("gancho", ""),
                "inicio": c.get("inicio"), "fim": c.get("fim"), "aprovacao": s.get("aprovacao"), "motivo": s.get("motivo", ""),
                "publicado": s.get("publicado"), "link": s.get("link", ""), "fora_padrao": s.get("fora_padrao"),
                "refeito": s.get("refeito"), "youtube": s.get("youtube"), "youtube_erro": s.get("youtube_erro"),
                "correcao": next(({kk: x.get(kk) for kk in ("tipo", "status", "erro", "resumo")}
                                  for x in reversed(est.get("fila_correcoes", []))
                                  if f"{x['canal']}/{x['id']}/{x['corte']}" == k and x["status"] in ("na fila", "corrigindo", "erro")), None),
                "avisos": est["avisos"].get(k, []) + (ler(ep / "avisos.json", {}) or {}).get(c["id"], []) + aviso_qa(ep, c["id"])}
        if saida:
            mp4 = sorted((saida / "shorts").glob(f"{c['id']} - *.mp4"))
            if mp4:
                item["mp4"] = rel(mp4[0])
                item["poster"] = f"/poster/{canal_dir.name}/{vid}/{c['id']}.jpg?m={int(mp4[0].stat().st_mtime)}"
                item["upload"] = ler_txt_upload(mp4[0].with_suffix(".txt"))
            leg = saida / "verificacao" / f"{c['id']}_short_legenda.txt"
            if leg.exists():
                item["legenda"] = ler_texto(leg)
                item["palavroes"] = sorted({m.group(0).lower() for m in PALAVROES.finditer(item["legenda"])})
            mos = saida / "verificacao" / f"{c['id']}_short.jpg"
            if mos.exists():
                item["mosaico"] = rel(mos)
            r = relat.get((c["id"], "short"))
            if r:
                item.update(duracao=r["duracao"], enquadramento=r["enquadramento"], problemas=r["problemas"])
        lista.append(item)
    d["shorts"] = lista
    return d


def resumo_canal(canal_dir, est, detalhe=False):
    cfg = ler(canal_dir / "canal.json", {}) or {}
    eps = [episodio(canal_dir, cfg, ep, est) for ep in sorted((canal_dir / "episodios").iterdir()) if ep.is_dir()] \
        if (canal_dir / "episodios").exists() else []
    validos = [e for e in eps if e["etapa"] != "descartado"]
    fontes = cfg.get("fontes", [])
    nome = cfg.get("nome") or canal_dir.name
    d = {"pasta": canal_dir.name, "nome": nome, "nicho": cfg.get("nicho", ""),
         "tema": nome.replace("Gato Preto", "").strip() or canal_dir.name,
         "cor": cfg.get("estilo", {}).get("cor_destaque", "#F0BF2A"),
         "handle": cfg.get("handle", ""), "episodios": eps,
         "n_shorts": sum(e.get("n_shorts", 0) for e in validos),
         "aprovados": sum(e.get("aprovados", 0) for e in validos),
         "reprovados": sum(e.get("reprovados", 0) for e in validos),
         "publicados": sum(e.get("publicados", 0) for e in validos),
         "fontes_total": len(fontes), "fontes_liberadas": sum(1 for f in fontes if f.get("status") == "LIBERADO"),
         "fontes_email": sum(1 for f in fontes if f.get("pedido", {}).get("enviado_em"))}
    if detalhe:
        try:
            sys.path.insert(0, str(AQUI.parent / "lib"))
            import youtube as YT
            pub = cfg.get("publicacao", {})
            d["piloto"] = {"auto_escolher": bool(pub.get("auto_escolher")), "estoque_dias": pub.get("estoque_dias", 7),
                           "estoque": estoque_canal(canal_dir, cfg, est),
                           "log": [x for x in est.get("piloto_log", []) if x["canal"] == canal_dir.name][-5:]}
            d["youtube"] = {"app": YT.CLIENTE.exists(), "conectado": YT.conectado(canal_dir.name), "info": cfg.get("youtube"),
                            "auto": bool(cfg.get("publicacao", {}).get("auto_upload")),
                            "status": YT_STATUS.get(canal_dir.name)}
        except Exception as e:
            d["youtube"] = {"erro": f"{type(e).__name__}: {e}"}
        d["fontes"] = fontes
        d["candidatos"] = [{k: c.get(k) for k in ("canal", "canal_url", "inscritos", "status", "emails")}
                           for c in cfg.get("candidatos", [])]
        modelo = canal_dir / "email-permissao.txt"
        d["email_modelo"] = ler_texto(modelo)
    return d


def publicacao_dados():
    """Aba Publicação: todos os Shorts aprovados, por canal, com a situação de envio pro YouTube."""
    est = estado()
    sys.path.insert(0, str(AQUI.parent / "lib"))
    import youtube as YT
    hoje = datetime.now().strftime("%Y-%m-%d")
    cota = est.get("youtube_cota", {})
    out = []
    for canal_dir in canais():
        cfg = ler(canal_dir / "canal.json", {}) or {}
        auto = bool(cfg.get("publicacao", {}).get("auto_upload"))
        con = YT.conectado(canal_dir.name)
        itens = []
        for ep in sorted((canal_dir / "episodios").glob("*")):
            plano = ler(ep / "cortes.json")
            if not plano:
                continue
            info = ler(ep / "info.json", {}) or {}
            fonte = fonte_do_info(cfg, info) or {}
            saida = saida_do_ep(canal_dir, ep.name)
            for c in plano.get("cortes", []):
                k = f"{canal_dir.name}/{ep.name}/{c['id']}"
                sh = est["shorts"].get(k, {})
                if sh.get("aprovacao") != "aprovado":
                    continue
                mp4 = sorted((saida / "shorts").glob(f"{c['id']} - *.mp4")) if saida else []
                if sh.get("youtube"):
                    sit = "agendado" if sh["youtube"]["agendado"] > datetime.utcnow().strftime("%Y-%m-%dT%H:%M") else "publicado"
                elif sh.get("publicado"):
                    sit = "publicado"
                elif sh.get("youtube_erro"):
                    sit = "erro"
                elif sh.get("fora_padrao"):
                    sit = "fora do padrão"
                elif fonte.get("status") != "LIBERADO":
                    sit = "aguardando a fonte liberar"
                elif not con:
                    sit = "canal não conectado ao YouTube"
                elif not auto:
                    sit = "envio automático desligado"
                else:
                    sit = "na fila de envio"
                itens.append({"canal": canal_dir.name, "id": ep.name, "corte": c["id"], "titulo": c.get("titulo_short") or c.get("titulo"),
                              "podcast": info.get("channel"), "fonte_status": fonte.get("status", "não cadastrada"),
                              "situacao": sit, "agendado": (sh.get("youtube") or {}).get("agendado"), "link": sh.get("link"),
                              "desempenho": sh.get("desempenho"),
                              "erro": sh.get("youtube_erro"),
                              "poster": f"/poster/{canal_dir.name}/{ep.name}/{c['id']}.jpg?m={int(mp4[0].stat().st_mtime)}" if mp4 else None})
        itens.sort(key=lambda x: (x["agendado"] or "9999", x["id"], x["corte"]))
        out.append({"pasta": canal_dir.name, "nome": cfg.get("nome"), "cor": cfg.get("estilo", {}).get("cor_destaque"),
                    "conectado": con, "auto": auto, "horarios": cfg.get("publicacao", {}).get("agenda", {}).get("horarios", []),
                    "itens": itens})
    return {"canais": out, "cota": {"limite": COTA_DIA, "usados_hoje": cota.get("n", 0) if cota.get("dia") == hoje else 0}}


def situacao_short(sh, liberado):
    """Em que ponto do funil o Short está."""
    agora = datetime.utcnow().strftime("%Y-%m-%dT%H:%M")
    if sh.get("fora_padrao"):
        return "fora"
    if sh.get("aprovacao") == "reprovado":
        return "reprovados"
    if sh.get("aprovacao") != "aprovado":
        return "a_revisar"
    if sh.get("youtube"):
        return "agendados" if sh["youtube"]["agendado"] > agora else "publicados"
    if sh.get("publicado"):
        return "publicados"
    return "aprovados" if liberado else "esperando_fonte"


def funil(est):
    """Funil dos Shorts por canal e no total (pra visão geral)."""
    total = {k: 0 for k in ("a_revisar", "aprovados", "esperando_fonte", "agendados", "publicados", "reprovados", "fora")}
    por_canal = {}
    for canal_dir in canais():
        cfg = ler(canal_dir / "canal.json", {}) or {}
        f = {k: 0 for k in total}
        for ep in (canal_dir / "episodios").glob("*"):
            plano = ler(ep / "cortes.json")
            if not plano or (ep / "NAO CORTAR - motivo.txt").exists() or not saida_do_ep(canal_dir, ep.name):
                continue
            fonte = fonte_do_info(cfg, ler(ep / "info.json", {}) or {}) or {}
            lib = fonte.get("status") == "LIBERADO"
            for c in plano.get("cortes", []):
                f[situacao_short(est["shorts"].get(f"{canal_dir.name}/{ep.name}/{c['id']}", {}), lib)] += 1
        por_canal[canal_dir.name] = f
        for k in total:
            total[k] += f[k]
    return {"total": total, "canais": por_canal}


def revisar_dados(canal=None, vid=None):
    """Fila do modo revisão: Shorts ainda sem decisão (nem aprovado, nem reprovado, nem fora do padrão)."""
    est = estado()
    itens = []
    for canal_dir in canais():
        if canal and canal_dir.name != canal:
            continue
        cfg = ler(canal_dir / "canal.json", {}) or {}
        for ep in sorted((canal_dir / "episodios").glob("*")):
            if vid and ep.name != vid:
                continue
            if not (ep / "cortes.json").exists() or (ep / "NAO CORTAR - motivo.txt").exists():
                continue
            e = episodio(canal_dir, cfg, ep, est, detalhe=True)
            for sh in e.get("shorts", []):
                if sh.get("mp4") and not sh.get("aprovacao") and not sh.get("fora_padrao") and not sh.get("correcao"):
                    itens.append({**sh, "canal": canal_dir.name, "canal_nome": cfg.get("nome"), "cor": cfg.get("estilo", {}).get("cor_destaque"),
                                  "id": ep.name, "ep_titulo": e["titulo"], "podcast": e["podcast"], "fonte_status": e["fonte_status"]})
    return {"itens": itens}


def fontes_novas_dados():
    arq = PESQ / "fontes_novas.json"
    d = ler(arq, {}) or {}
    nomes = {c.name: (ler(c / "canal.json", {}) or {}).get("nome", c.name) for c in canais()}
    return {"gerado_em": d.get("gerado_em"), "itens": [i for i in d.get("itens", []) if not i.get("decisao")], "nomes": nomes}


def decidir_fonte_nova(dados):
    arq = PESQ / "fontes_novas.json"
    with TRAVA:
        d = copy.deepcopy(ler(arq, {}) or {})
        item = next((i for i in d.get("itens", []) if i["url"] == dados["url"]), None)
        if not item:
            return {"erro": "Fonte não encontrada na lista."}
        item["decisao"] = dados["decisao"]
        if dados["decisao"] == "adicionar":
            canal = dados.get("canal") or item["canal"]
            alvo = item.get("principal") if dados.get("usar_principal") and item.get("principal") else {"canal": item["nome"], "canal_url": item["url"]}
            cj = RAIZ / canal / "canal.json"
            cfg = copy.deepcopy(ler(cj))
            if not any((f.get("canal_url") or "").rstrip("/") == alvo["canal_url"].rstrip("/") for f in cfg.get("fontes", [])):
                prova = item.get("prova") or {}
                cfg.setdefault("fontes", []).append({
                    "canal": alvo["canal"], "canal_url": alvo["canal_url"],
                    "status": "LIBERADO" if item["status"] == "LIBERADO" else "CONDICIONAL",
                    "espera_horas": item.get("espera_horas"), "emails": item.get("emails", []),
                    "evidencia": f"Público: \"{prova.get('texto', '')}\" ({prova.get('video', item['url'])}) — radar de fontes em {item.get('achado_em')}",
                    "obs": "Adicionada pelo radar de fontes liberadas" + (f" (canal de cortes: {item['nome']})" if alvo["canal_url"] != item["url"] else "")})
                gravar(cj, cfg)
        gravar(arq, d)
    return {"ok": True}


def visao_geral():
    est = estado()
    cs = [resumo_canal(c, est) for c in canais()]
    agora = [{"canal": c["pasta"], **e} for c in cs for e in c["episodios"] if e["etapa"] in ("render", "download", "transcricao")]
    fila = sum(1 for c in cs for e in c["episodios"] if e["etapa"] == "fila_render")
    espera = [x for x in est.get("fila_preparo", []) if x.get("status") in ("aguardando", "curadoria na fila", "curadoria")]
    fora = []
    for k, v in est.get("shorts", {}).items():
        if v.get("fora_padrao"):
            canal, vid, corte = k.split("/")
            fora.append({"canal": canal, "id": vid, "corte": corte, **v["fora_padrao"]})
    correcoes = [x for x in est.get("fila_correcoes", []) if x["status"] in ("na fila", "corrigindo", "erro")]
    cobrar = []   # pedido de autorização enviado há 7+ dias sem resposta
    for canal_dir in canais():
        cfg = ler(canal_dir / "canal.json", {}) or {}
        for f in cfg.get("fontes", []):
            env = (f.get("pedido") or {}).get("enviado_em")
            if env and f.get("status") == "E-MAIL ENVIADO" and not (f.get("pedido") or {}).get("respondido_em"):
                try:
                    dias = (datetime.now() - datetime.strptime(env, "%Y-%m-%d")).days
                except ValueError:
                    continue
                if dias >= 7:
                    cobrar.append({"canal": canal_dir.name, "canal_nome": cfg.get("nome"), "fonte": f["canal"], "dias": dias})
    return {"canais": cs, "agora": agora, "fila_render": fila, "fila_preparo": espera, "fora_padrao": fora, "correcoes": correcoes,
            "funil": funil(est), "cobrar": cobrar, "atualizado": datetime.now().strftime("%H:%M:%S"),
            "parar_fila": (RAIZ / "_pesquisa" / "fila.parar").exists()}


# ---------- gravação ----------
def marcar_short(dados):
    k = f"{dados['canal']}/{dados['id']}/{dados['corte']}"
    with TRAVA:
        est = estado(fresco=True)
        s = est["shorts"].setdefault(k, {})
        if "fora_padrao" in dados:   # marcado pelo usuário: Short não segue o padrão combinado
            if dados["fora_padrao"]:
                s["fora_padrao"] = {**dados["fora_padrao"], "em": datetime.now().strftime("%Y-%m-%d %H:%M")}
            else:
                s.pop("fora_padrao", None)
        if "aprovacao" in dados:
            s["aprovacao"] = dados["aprovacao"] or None
            s["motivo"] = dados.get("motivo", "")
            s["revisado_em"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        if "publicado" in dados:
            if dados["publicado"]:
                canal_dir = RAIZ / dados["canal"]
                cfg = ler(canal_dir / "canal.json", {})
                info = ler(canal_dir / "episodios" / dados["id"] / "info.json", {})
                f = fonte_do_info(cfg, info)
                if not (f and f.get("status") == "LIBERADO"):
                    return {"erro": "A fonte deste episódio não está LIBERADA. Só marque como publicado depois da autorização."}
                if s.get("aprovacao") != "aprovado":
                    return {"erro": "Aprove o Short antes de marcar como publicado."}
                s["publicado"] = dados.get("data") or datetime.now().strftime("%Y-%m-%d")
                s["link"] = dados.get("link", "")
            else:
                s.pop("publicado", None)
                s.pop("link", None)
        _sincronizar_correcao(est, dados["canal"], dados["id"], dados["corte"], s)
        gravar(ESTADO, est)
    FILA_EVENTO.set()
    return {"ok": True}


def _sincronizar_correcao(est, canal, vid, corte, s):
    """Fora do padrão → volta pra produção; reprovado → volta pra conferência. Os dois viram trabalho do Claude
    (fila_correcoes). Desmarcar antes de começar tira da fila. O trabalho só começa 45 s depois do último clique."""
    fila = est.setdefault("fila_correcoes", [])
    atual = next((x for x in fila if (x["canal"], x["id"], x["corte"]) == (canal, vid, corte)
                  and x["status"] in ("na fila", "corrigindo")), None)
    tipo = "fora_padrao" if s.get("fora_padrao") else ("reprovado" if s.get("aprovacao") == "reprovado" else None)
    if not tipo:
        if atual and atual["status"] == "na fila":
            fila.remove(atual)
        return
    dados = {"tipo": tipo, "motivos": (s.get("fora_padrao") or {}).get("motivos", []),
             "obs": (s.get("fora_padrao") or {}).get("obs", "") if tipo == "fora_padrao" else s.get("motivo", ""),
             "atualizado": time.time()}
    if atual and atual["status"] == "na fila":
        atual.update(dados)
    elif not atual:
        fila.append({"canal": canal, "id": vid, "corte": corte, "status": "na fila",
                     "pedido_em": datetime.now().strftime("%Y-%m-%d %H:%M"), **dados})


def marcar_fonte(dados):
    arq = RAIZ / dados["canal"] / "canal.json"
    with TRAVA:
        cfg = copy.deepcopy(ler(arq))
        alvo = next((f for f in cfg.get("fontes", []) if f.get("canal") == dados["fonte"]), None)
        if not alvo:
            return {"erro": "Fonte não encontrada no canal.json"}
        if "status" in dados:
            if dados["status"] not in STATUS_FONTE:
                return {"erro": "Status inválido"}
            if dados["status"] == "LIBERADO" and not (dados.get("evidencia") or alvo.get("evidencia")):
                return {"erro": "Para LIBERADO, diga onde está a autorização (ex.: e-mail de fulano em 10/10)."}
            alvo["status"] = dados["status"]
        if dados.get("evidencia"):
            alvo["evidencia"] = dados["evidencia"]
        p = alvo.setdefault("pedido", {})
        for campo in ("enviado_em", "respondido_em", "resposta"):
            if campo in dados:
                p[campo] = dados[campo]
        gravar(arq, cfg)
    return {"ok": True}


# ---------- radar (novos episódios) e fila de preparo (baixar + transcrever o que você escolheu) ----------
PESQ = RAIZ / "_pesquisa"
MOTOR = AQUI.parent
PY = Path(sys.executable).with_name("python.exe") if Path(sys.executable).name.lower() == "pythonw.exe" else Path(sys.executable)
SEM_JANELA = getattr(subprocess, "CREATE_NO_WINDOW", 0)
RADAR_PROC = None
PREPARO_ATIVO = False
FILA_EVENTO = threading.Event()


def radar_rodando():
    return bool(RADAR_PROC and RADAR_PROC.poll() is None)


def radar_dados():
    r = ler(PESQ / "radar.json", {}) or {}
    st = dict(ler(PESQ / "radar.status.json", {}) or {})
    st["rodando"] = radar_rodando() or (st.get("rodando") and _status_recente(st))
    est = estado()
    dec, fila = est.get("radar", {}), est.get("fila_preparo", [])
    ja = {q.parent.name for q in RAIZ.glob("canal-*/episodios/*/info.json")}
    por_id = {x["id"]: x for x in fila}
    itens = []
    for i in r.get("itens", []):
        i = dict(i)
        i["decisao"] = dec.get(i["id"])
        i["ja_baixado"] = i["id"] in ja
        i["preparo"] = (por_id.get(i["id"]) or {}).get("status")
        itens.append(i)
    nomes = {c.name: (ler(c / "canal.json", {}) or {}).get("nome", c.name) for c in canais()}
    return {"gerado_em": r.get("gerado_em"), "itens": itens, "status": st, "fila": fila, "nomes": nomes}


def _status_recente(st):
    try:
        return (datetime.now() - datetime.strptime(st.get("inicio", ""), "%Y-%m-%d %H:%M")).total_seconds() < 3 * 3600
    except ValueError:
        return False


def rodar_radar():
    global RADAR_PROC
    if radar_rodando():
        return {"erro": "O radar já está procurando."}
    log = open(PESQ / "radar.log", "w", encoding="utf-8")
    RADAR_PROC = subprocess.Popen([str(PY), "-u", str(MOTOR / "radar.py")], cwd=str(MOTOR), stdout=log, stderr=subprocess.STDOUT,
                                  creationflags=SEM_JANELA, env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    return {"ok": True}


def pedir_auto(dados):
    ep = RAIZ / dados["canal"] / "episodios" / dados["id"]
    if not (ep / "transcricao.json").exists():
        return {"erro": "O episódio ainda não foi transcrito."}
    info = ler(ep / "info.json", {}) or {}
    with TRAVA:
        est = estado(fresco=True)
        fila = est.setdefault("fila_preparo", [])
        fila[:] = [x for x in fila if x["id"] != dados["id"]]
        fila.append({"id": dados["id"], "canal": dados["canal"], "fonte": info.get("channel", ""), "fonte_url": info.get("channel_url", ""),
                     "titulo": info.get("title", dados["id"]), "status": "curadoria na fila",
                     "pedido_em": datetime.now().strftime("%Y-%m-%d %H:%M")})
        gravar(ESTADO, est)
    FILA_EVENTO.set()
    return {"ok": True}


def decidir_radar(dados):
    with TRAVA:
        est = estado(fresco=True)
        dec = est.setdefault("radar", {})
        fila = est.setdefault("fila_preparo", [])
        vid, d = dados["id"], dados.get("decisao")
        if d:
            dec[vid] = d
        else:
            dec.pop(vid, None)
        item = next((i for i in (ler(PESQ / "radar.json", {}) or {}).get("itens", []) if i["id"] == vid), None)
        if d == "quero" and item and not any(x["id"] == vid for x in fila):
            fila.append({"id": vid, "canal": item["canal"], "fonte": item["fonte"], "fonte_url": item["fonte_url"],
                         "titulo": item["titulo"], "status": "aguardando", "pedido_em": datetime.now().strftime("%Y-%m-%d %H:%M")})
        if d != "quero":
            est["fila_preparo"] = [x for x in fila if not (x["id"] == vid and x["status"] == "aguardando")]
        gravar(ESTADO, est)
    FILA_EVENTO.set()
    return {"ok": True}


def _atualizar_fila(vid, **campos):
    with TRAVA:
        est = estado(fresco=True)
        for x in est.get("fila_preparo", []):
            if x["id"] == vid:
                x.update(campos)
        gravar(ESTADO, est)


def achar_claude():
    """claude.exe da extensão do VS Code (a versão mais nova instalada)."""
    achados = sorted(Path.home().glob(".vscode/extensions/anthropic.claude-code-*/resources/native-binary/claude.exe"),
                     key=lambda q: q.stat().st_mtime)
    return achados[-1] if achados else None


PROMPT_AUTO = """Use a skill cortes. Trabalho AUTOMÁTICO, sem ninguém olhando: não pergunte nada, decida pelo padrão da skill.
IMPORTANTE: ninguém vai te mandar notificação. NUNCA rode comando em segundo plano (run_in_background) nem termine
"esperando" algo: rode tudo em primeiro plano com timeout 600000; se um render for passar de 10 min, renderize em
partes com --so 01,02,03... Só escreva a linha RESUMO depois de renderizar e conferir TUDO.
Episódio {id} do canal {canal} (pasta F:\\CORTES\\{canal}\\episodios\\{id}). Entregue os Shorts prontos:
1. Leia F:\\CORTES\\_pesquisa\\regras_aprendidas.md (regras que vieram das correções do usuário) e siga todas.
   Leia o leitura.txt INTEIRO e o info.json (título, convidado, capítulos).
2. Escreva o cortes.json: SÓ Shorts (formatos ["short"]), 8 a 15 dos melhores, com de/ate exatos (use `cortes.bat palavras`),
   gancho, titulo_short, titulo, descricao, convidado, podcast, tags e correcoes de nomes. Regras: nada de difamação ou
   acusação a pessoa nomeada, nada de suicídio, nada de política partidária fora do canal de Política, nada de merchan do episódio.
   Evite Short em que mais da metade do tempo é plano aberto de grupo/plateia (rosto pequeno, sem close possível).
   Se o episódio inteiro não servir, escreva "NAO CORTAR - motivo.txt" na pasta do episódio e pare.
3. `cortes.bat validar {canal} {id}` até dar 0 erros.
4. `set CORTES_NAO_ABRIR=1` e `cortes.bat renderizar {canal} {id}` (o visual padrão já está no canal.json).
5. Confira 100%: primeira e última palavra de cada prontos\\*_{id}\\verificacao\\NN_short_legenda.txt (frase não pode começar
   nem terminar cortada) e nomes errados → corrija (correcoes / de / ate) e `cortes.bat renderizar {canal} {id} --so NN`.
   Abra cada mosaico NN_short.jpg (é o Short JÁ recortado). Marque SÓ o que aparece DENTRO do Short no mosaico — nunca
   pelo quadro original inteiro: o Short é um recorte estreito em quem fala, então logo/QR no canto do original quase
   sempre já fica de fora e NÃO deve ser marcado (cortar_embaixo à toa dá zoom e perde qualidade).
   Se no mosaico houver logo, QR code ou anúncio atrás da legenda → marque no corte
   "esconder": [[x0,y0,x1,y1]] (0 a 1 do vídeo original; meça num quadro do trabalho\\NN_short_bruto.mkv com grade) ou
   "cortar_embaixo": 0.77 para faixa embaixo, e renderize --so NN. Depois de editar o cortes.json rode
   `python -c "import os;os.utime(r'F:\\CORTES\\{canal}\\episodios\\{id}\\trabalho\\.renderizado', None)"` se ele existir.
   Se no MOSAICO aparecer um slide/artigo/gráfico com quem fala numa janelinha num canto, meça a janela
   e grave no TOPO do cortes.json "janela_original": [x0,y0,x1,y1] (0 a 1, sem a borda): o render usa só a janela
   nesses trechos, sozinho. Renderize de novo os cortes afetados.
   O render grava a auditoria automática do enquadramento em episodios\\{id}\\qa.json (nota_problema >= 0.25 =
   conferir: rosto cortado, atrás do gancho, pequeno). Olhe esses Shorts no mosaico e corrija o que for erro de verdade.
6. Grave em F:\\CORTES\\{canal}\\episodios\\{id}\\avisos.json os avisos que ficarem: {{"NN": [{{"nivel": "atencao"|"grave", "texto": "..."}}]}}.
7. Termine com UMA linha: RESUMO: <n> Shorts prontos; <avisos em poucas palavras>.
Não publique nada. Escreva em português."""


def curadoria_auto(item, ja_rodando=False):
    """Sessão do Claude sem janela fazendo curadoria + render + conferência. Trava o episódio pra fila de render não pegar.
    ja_rodando: o painel foi reiniciado com a sessão no meio → só espera ela terminar e fecha o resultado."""
    claude = achar_claude()
    ep = RAIZ / item["canal"] / "episodios" / item["id"]
    if not claude:
        return {"status": "erro", "erro": "Claude Code não encontrado (extensão do VS Code)."}
    trava = ep / "trabalho" / ".renderizando"
    (ep / "trabalho").mkdir(exist_ok=True)
    trava.touch()
    log = PESQ / f"auto_{item['id']}.log"
    try:
        if ja_rodando:
            while processos_com(f"Episódio {item['id']} do canal"):
                time.sleep(30)
        else:
          with open(log, "w", encoding="utf-8") as f:
            r = subprocess.run([str(claude), "-p", PROMPT_AUTO.format(**item), "--output-format", "text",
                                "--permission-mode", "acceptEdits", "--allowedTools", "Bash Read Write Edit Glob Grep Skill",
                                "--add-dir", str(RAIZ)], cwd=str(RAIZ), stdout=f, stderr=subprocess.STDOUT,
                               creationflags=SEM_JANELA, timeout=3 * 3600,
                               env={**os.environ, "CORTES_NAO_ABRIR": "1", "PYTHONIOENCODING": "utf-8"})
    except subprocess.TimeoutExpired:
        return {"status": "erro", "erro": "Curadoria automática passou de 3 h."}
    finally:
        trava.unlink(missing_ok=True)
    texto = ler_texto(log)
    resumo = next((l.split(":", 1)[1].strip() for l in reversed(texto.splitlines()) if l.strip().upper().startswith("RESUMO:")), "")
    # garantia: se a sessão parou com o cortes.json mais novo que os vídeos, renderiza o que faltou aqui mesmo
    saida = saida_do_ep(RAIZ / item["canal"], item["id"])
    mp4s = list((saida / "shorts").glob("*.mp4")) if saida else []
    if (ep / "cortes.json").exists() and not (ep / "NAO CORTAR - motivo.txt").exists() and \
            (not mp4s or (ep / "cortes.json").stat().st_mtime > max(m.stat().st_mtime for m in mp4s)):
        trava.touch()
        with open(PESQ / f"auto_{item['id']}_render.log", "w", encoding="utf-8") as f:
            subprocess.run([str(PY), "-u", str(MOTOR / "cortes.py"), "renderizar", item["canal"], item["id"]], cwd=str(MOTOR),
                           stdout=f, stderr=subprocess.STDOUT, creationflags=SEM_JANELA,
                           env={**os.environ, "CORTES_NAO_ABRIR": "1", "PYTHONIOENCODING": "utf-8"})
        trava.unlink(missing_ok=True)
        if not resumo:
            resumo = "conferência incompleta: a sessão parou antes; o painel renderizou o que faltava"
    if (ep / "NAO CORTAR - motivo.txt").exists():
        return {"status": "descartado", "erro": ler_texto(ep / "NAO CORTAR - motivo.txt").strip().splitlines()[0][:300]}
    saida = saida_do_ep(RAIZ / item["canal"], item["id"])
    if (ep / "cortes.json").exists() and saida and any((saida / "shorts").glob("*.mp4")):
        (ep / "trabalho" / ".renderizado").touch()
        return {"status": "shorts prontos", "resumo": resumo or "conferência incompleta (sessão terminou sem resumo)"}
    return {"status": "erro", "erro": (resumo or texto.strip().splitlines()[-1:] or ["sem saída"])[0][:300]}


REGRAS = RAIZ / "_pesquisa" / "regras_aprendidas.md"

PROMPT_CORRECAO = """Use a skill cortes. Trabalho AUTOMÁTICO, sem ninguém olhando: não pergunte nada.
IMPORTANTE: NUNCA rode comando em segundo plano nem termine "esperando" algo; tudo em primeiro plano (timeout 600000).
Episódio {id} do canal {canal} (F:\\CORTES\\{canal}), Short {corte}.
O usuário {acao}. Motivos marcados: {motivos}. Observação dele: "{obs}".
1. Entenda o problema: mosaico prontos\\*_{id}\\verificacao\\{corte}_short.jpg, legenda {corte}_short_legenda.txt,
   episodios\\{id}\\qa.json (auditoria de enquadramento), o corte {corte} no cortes.json e o trecho no leitura.txt.
   Leia também F:\\CORTES\\_pesquisa\\regras_aprendidas.md.
2. {tarefa}
3. Renderize só esse Short: `set CORTES_NAO_ABRIR=1` e `cortes.bat renderizar {canal} {id} --so {corte}`.
4. Confira o mosaico e a legenda novos. Se ainda estiver errado, corrija e renderize de novo.
5. Se o motivo vale como REGRA GERAL (não só deste Short), acrescente UMA linha em F:\\CORTES\\_pesquisa\\regras_aprendidas.md:
   "- AAAA-MM-DD · <motivo> · <regra objetiva pra próxima curadoria/render>". Não repita regra que já existe.
6. Termine com UMA linha: RESUMO: <o que você mudou, em poucas palavras>.
Escreva em português."""

TAREFA = {
    "fora_padrao": ("marcou este Short como FORA DO PADRÃO combinado (identidade Gato Preto, close em quem fala, sem logo/QR/anúncio "
                    "do original na tela, legenda certa, começo e fim no ponto)",
                    "Corrija NA CAUSA: enquadramento → \"esconder\"/\"cortar_embaixo\"/\"janela_original\" ou ajuste de/ate pra "
                    "fugir do trecho ruim; legenda → \"correcoes\"; começo/fim cortado → \"de\"/\"ate\" (use `cortes.bat palavras`); "
                    "gancho/título → \"gancho\"/\"titulo_short\". Mantenha o mesmo id."),
    "reprovado": ("REPROVOU este Short",
                  "Reanalise o porquê. Se dá pra salvar, refaça o corte (outros limites de/ate, outro gancho/título). Se o trecho "
                  "não presta, troque por OUTRO trecho melhor do mesmo episódio que ainda não foi usado, com o MESMO id "
                  "(atualize de/ate/gancho/titulo/titulo_short/descricao/tags) e rode `cortes.bat validar`."),
}


def corrigir_short(item):
    claude = achar_claude()
    ep = RAIZ / item["canal"] / "episodios" / item["id"]
    if not claude:
        return {"status": "erro", "erro": "Claude Code não encontrado (extensão do VS Code)."}
    trava = ep / "trabalho" / ".renderizando"
    for _ in range(240):    # espera a fila de render largar o episódio (até 2 h)
        if not trava.exists() or time.time() - trava.stat().st_mtime > 3 * 3600:
            break
        time.sleep(30)
    trava.touch()
    acao, tarefa = TAREFA[item["tipo"]]
    prompt = PROMPT_CORRECAO.format(canal=item["canal"], id=item["id"], corte=item["corte"], acao=acao, tarefa=tarefa,
                                    motivos=", ".join(item.get("motivos") or []) or "nenhum marcado",
                                    obs=item.get("obs") or "nenhuma")
    log = PESQ / f"correcao_{item['id']}_{item['corte']}.log"
    try:
        with open(log, "w", encoding="utf-8") as f:
            subprocess.run([str(claude), "-p", prompt, "--output-format", "text", "--permission-mode", "acceptEdits",
                            "--allowedTools", "Bash Read Write Edit Glob Grep Skill", "--add-dir", str(RAIZ)],
                           cwd=str(RAIZ), stdout=f, stderr=subprocess.STDOUT, creationflags=SEM_JANELA, timeout=2 * 3600,
                           env={**os.environ, "CORTES_NAO_ABRIR": "1", "PYTHONIOENCODING": "utf-8"})
    except subprocess.TimeoutExpired:
        return {"status": "erro", "erro": "Correção passou de 2 h."}
    finally:
        (ep / "trabalho" / ".renderizado").touch()
        trava.unlink(missing_ok=True)
    texto = ler_texto(log)
    resumo = next((l.split(":", 1)[1].strip() for l in reversed(texto.splitlines()) if l.strip().upper().startswith("RESUMO:")), "")
    if not resumo:
        return {"status": "erro", "erro": (texto.strip().splitlines()[-1:] or ["sem saída"])[0][:300]}
    return {"status": "pronto", "resumo": resumo}


def trabalhador_correcoes():
    global PREPARO_ATIVO, ULTIMO_PEDIDO
    with TRAVA:
        est = estado(fresco=True)
        for x in est.get("fila_correcoes", []):
            if x["status"] == "corrigindo":
                x["status"] = "na fila"
        gravar(ESTADO, est)
    while True:
        time.sleep(10)
        prox = next((x for x in estado().get("fila_correcoes", [])
                     if x["status"] == "na fila" and time.time() - x.get("atualizado", 0) > 45), None)
        if not prox:
            continue
        chave = (prox["canal"], prox["id"], prox["corte"])

        def mudar(**c):
            with TRAVA:
                est = estado(fresco=True)
                for x in est.get("fila_correcoes", []):
                    if (x["canal"], x["id"], x["corte"]) == chave and x["status"] in ("na fila", "corrigindo"):
                        x.update(c)
                if c.get("status") == "pronto":   # volta pra revisão do usuário, com o que foi refeito
                    sh = est["shorts"].setdefault(f"{chave[0]}/{chave[1]}/{chave[2]}", {})
                    sh.pop("fora_padrao", None)
                    sh["aprovacao"] = None
                    sh["motivo"] = ""
                    sh["refeito"] = {"tipo": prox["tipo"], "resumo": c.get("resumo", ""), "em": datetime.now().strftime("%Y-%m-%d %H:%M")}
                gravar(ESTADO, est)
        PREPARO_ATIVO = True
        mudar(status="corrigindo", inicio=datetime.now().strftime("%H:%M"))
        try:
            fim = corrigir_short(prox)
        except Exception as e:
            fim = {"status": "erro", "erro": f"{type(e).__name__}: {e}"[:300]}
        mudar(fim=datetime.now().strftime("%H:%M"), **fim)
        notificar("Short corrigido" if fim.get("status") == "pronto" else "Correção falhou",
                  f"Short {prox['corte']} de {prox['id']}: {(fim.get('resumo') or fim.get('erro') or '')[:90]}")
        PREPARO_ATIVO = False
        ULTIMO_PEDIDO = time.time()


# ---------- avisos no Windows (notificação na tela) ----------
def notificar(titulo, texto):
    """Notificação nativa do Windows (sem instalar nada), pelo PowerShell."""
    def esc(x):
        return (x or "").replace("&", "e").replace("<", "").replace(">", "").replace("'", "").replace('"', "")[:200]
    ps = ("[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null;"
          "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null;"
          "$x = New-Object Windows.Data.Xml.Dom.XmlDocument;"
          f"$x.LoadXml('<toast><visual><binding template=\"ToastGeneric\"><text>{esc(titulo)}</text><text>{esc(texto)}</text></binding></visual></toast>');"
          "$n = [Windows.UI.Notifications.ToastNotification]::new($x);"
          "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe').Show($n)")
    try:
        subprocess.Popen(["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps], creationflags=SEM_JANELA)
    except Exception as e:
        print("notificar:", e, flush=True)


def vigia_radar():
    """Avisa quando o radar acha episódio com nota acima de 90 (uma vez por episódio)."""
    vistos = set()
    while True:
        try:
            for i in (ler(PESQ / "radar.json", {}) or {}).get("itens", []):
                if i.get("nota", 0) >= 90 and not i.get("bloqueado") and i["id"] not in vistos:
                    if vistos is not None and len(vistos) > 0:
                        notificar("Radar: episódio forte", f"{i['fonte']}: {i['titulo'][:80]} (nota {i['nota']})")
                    vistos.add(i["id"])
            if not vistos:
                vistos.add("")
        except Exception:
            pass
        time.sleep(600)


# ---------- 9) disco: espaço livre e limpeza dos vídeos originais de episódios resolvidos ----------
def disco_dados():
    import shutil as _sh
    uso = _sh.disk_usage(str(RAIZ))
    est = estado()
    eps, total = [], 0
    for canal_dir in canais():
        cfg = ler(canal_dir / "canal.json", {}) or {}
        for ep in (canal_dir / "episodios").glob("*"):
            v = ep / "video.mp4"
            if not v.exists():
                continue
            tam = v.stat().st_size
            total += tam
            plano = ler(ep / "cortes.json") or {}
            estados = [est["shorts"].get(f"{canal_dir.name}/{ep.name}/{c['id']}", {}) for c in plano.get("cortes", [])]
            resolvido = bool(estados) and all(x.get("publicado") or x.get("youtube") or x.get("aprovacao") == "reprovado" for x in estados)
            eps.append({"canal": canal_dir.name, "id": ep.name, "gb": round(tam / 1e9, 2), "resolvido": resolvido})
    return {"livre_gb": round(uso.free / 1e9, 1), "total_gb": round(uso.total / 1e9, 1), "videos_gb": round(total / 1e9, 1),
            "liberavel_gb": round(sum(e["gb"] for e in eps if e["resolvido"]), 1),
            "resolvidos": [e for e in eps if e["resolvido"]]}


def limpar_disco(dados):
    apagados, gb = [], 0.0
    for e in disco_dados()["resolvidos"]:
        ep = RAIZ / e["canal"] / "episodios" / e["id"]
        for f in [ep / "video.mp4"] + list((ep / "trabalho").glob("*_bruto.mkv")):
            if f.exists():
                gb += f.stat().st_size / 1e9
                f.unlink()
        apagados.append(e["id"])
    return {"ok": True, "apagados": apagados, "gb": round(gb, 1)}


# ---------- 7) desempenho: visualizações dos Shorts publicados (YouTube Data API, leitura) ----------
def trabalhador_desempenho():
    while True:
        time.sleep(90)
        try:
            YT = _yt()
            est = estado()
            por_canal = {}
            for k, v in est["shorts"].items():
                if (v.get("youtube") or {}).get("id"):
                    por_canal.setdefault(k.split("/")[0], []).append((k, v["youtube"]["id"]))
            novos = {}
            for canal, lista in por_canal.items():
                if not YT.conectado(canal):
                    continue
                svc = YT._servico(canal)
                for i in range(0, len(lista), 50):
                    lote = lista[i:i + 50]
                    r = svc.videos().list(part="statistics,status", id=",".join(v for _, v in lote)).execute()
                    stats = {it["id"]: it for it in r.get("items", [])}
                    for k, vid in lote:
                        it = stats.get(vid)
                        if it:
                            st = it.get("statistics", {})
                            novos[k] = {"views": int(st.get("viewCount", 0)), "likes": int(st.get("likeCount", 0)),
                                        "comentarios": int(st.get("commentCount", 0)), "privacidade": it["status"].get("privacyStatus"),
                                        "em": datetime.now().strftime("%Y-%m-%d %H:%M")}
            if novos:
                with TRAVA:
                    e2 = estado(fresco=True)
                    for k, d in novos.items():
                        e2["shorts"].setdefault(k, {})["desempenho"] = d
                    gravar(ESTADO, e2)
        except Exception as e:
            print("desempenho:", e, flush=True)
        time.sleep(6 * 3600)


# ---------- piloto automático: mantém um estoque de Shorts escolhendo episódios sozinho ----------
SHORTS_POR_EPISODIO = 10   # estimativa pro estoque de episódio ainda em produção


def estoque_canal(canal_dir, cfg, est):
    """Quantos Shorts o canal tem pela frente (agendados + aprovados + a revisar de fonte liberada + em produção)."""
    pub = cfg.get("publicacao", {})
    por_dia = len(pub.get("agenda", {}).get("horarios") or ["12:00", "19:00"])
    agora = datetime.utcnow().strftime("%Y-%m-%dT%H:%M")
    n = {"agendados": 0, "aprovados": 0, "a_revisar": 0, "producao": 0}
    for ep in (canal_dir / "episodios").glob("*"):
        plano = ler(ep / "cortes.json")
        if not plano or (ep / "NAO CORTAR - motivo.txt").exists():
            continue
        fonte = fonte_do_info(cfg, ler(ep / "info.json", {}) or {}) or {}
        if fonte.get("status") != "LIBERADO":
            continue
        for c in plano.get("cortes", []):
            sh = est["shorts"].get(f"{canal_dir.name}/{ep.name}/{c['id']}", {})
            if sh.get("youtube"):
                n["agendados"] += sh["youtube"]["agendado"] > agora
            elif sh.get("aprovacao") == "aprovado" and not sh.get("publicado"):
                n["aprovados"] += 1
            elif not sh.get("aprovacao") and not sh.get("fora_padrao"):
                n["a_revisar"] += 1
    for x in est.get("fila_preparo", []):
        if x["canal"] == canal_dir.name and x["status"] in ("aguardando", "preparando", "curadoria na fila", "curadoria"):
            n["producao"] += SHORTS_POR_EPISODIO
    total = sum(n.values())
    return {**n, "total": total, "por_dia": por_dia, "dias": round(total / max(1, por_dia), 1),
            "alvo_dias": pub.get("estoque_dias", 7)}


def trabalhador_piloto():
    """A cada 30 min: canal com piloto ligado e estoque abaixo do alvo → escolhe 1 episódio do radar (fonte LIBERADA)."""
    time.sleep(120)
    while True:
        try:
            est = estado()
            radar = (ler(PESQ / "radar.json", {}) or {}).get("itens", [])
            dec = est.get("radar", {})
            na_fila = {x["id"] for x in est.get("fila_preparo", [])}
            ja = {q.parent.name for q in RAIZ.glob("canal-*/episodios/*/info.json")}
            for canal_dir in canais():
                cfg = ler(canal_dir / "canal.json", {}) or {}
                if not cfg.get("publicacao", {}).get("auto_escolher"):
                    continue
                e = estoque_canal(canal_dir, cfg, est)
                if e["dias"] >= e["alvo_dias"]:
                    continue
                liberadas = {(f.get("canal_url") or "").rstrip("/") for f in cfg.get("fontes", []) if f.get("status") == "LIBERADO"}
                opcoes = [i for i in radar if i["canal"] == canal_dir.name and i["fonte_url"].rstrip("/") in liberadas
                          and not i.get("bloqueado") and not any(a["nivel"] == "grave" for a in i.get("avisos", []))
                          and i["id"] not in ja and i["id"] not in na_fila and dec.get(i["id"]) != "ignorar"
                          and (i.get("duracao_min") or 0) >= 30]
                if not opcoes:
                    continue
                melhor = max(opcoes, key=lambda i: i.get("nota", 0))
                decidir_radar({"id": melhor["id"], "decisao": "quero"})
                with TRAVA:
                    e2 = estado(fresco=True)
                    e2.setdefault("piloto_log", []).append({"em": datetime.now().strftime("%Y-%m-%d %H:%M"), "canal": canal_dir.name,
                                                             "id": melhor["id"], "titulo": melhor["titulo"], "estoque_dias": e["dias"]})
                    e2["piloto_log"] = e2["piloto_log"][-50:]
                    gravar(ESTADO, e2)
                notificar(f"{cfg.get('nome')}: episódio escolhido sozinho", f"{melhor['titulo'][:80]} (estoque {e['dias']} dias)")
                break    # um por ciclo
        except Exception as ex:
            print("piloto:", ex, flush=True)
        time.sleep(1800)


def resumo_diario():
    """Às 20h: notificação com o dia de cada canal com piloto ligado."""
    feito = None
    while True:
        agora = datetime.now()
        if agora.hour == 20 and feito != agora.date():
            feito = agora.date()
            try:
                est = estado()
                for canal_dir in canais():
                    cfg = ler(canal_dir / "canal.json", {}) or {}
                    if not cfg.get("publicacao", {}).get("auto_escolher"):
                        continue
                    e = estoque_canal(canal_dir, cfg, est)
                    hoje = agora.strftime("%Y-%m-%d")
                    agendados_hoje = sum(1 for k, v in est["shorts"].items() if k.startswith(canal_dir.name + "/")
                                         and (v.get("youtube") or {}).get("enviado_em", "").startswith(hoje))
                    notificar(f"{cfg.get('nome')} hoje",
                              f"{agendados_hoje} agendado(s) hoje · {e['a_revisar']} esperando sua revisão · estoque {e['dias']} dias")
            except Exception as ex:
                print("resumo:", ex, flush=True)
        time.sleep(300)


def piloto_config(dados):
    arq = RAIZ / dados["canal"] / "canal.json"
    with TRAVA:
        cfg = copy.deepcopy(ler(arq))
        pub = cfg.setdefault("publicacao", {})
        for k in ("auto_escolher", "auto_upload"):
            if k in dados:
                pub[k] = bool(dados[k])
        if "estoque_dias" in dados:
            pub["estoque_dias"] = max(2, min(30, int(dados["estoque_dias"])))
        gravar(arq, cfg)
    return {"ok": True}


# ---------- YouTube: conectar canal e enviar Shorts aprovados de fonte liberada ----------
YT_STATUS = {}
COTA_DIA = 5     # cota grátis da API ≈ 6 envios/dia por app; deixa folga


def _yt():
    sys.path.insert(0, str(AQUI.parent / "lib"))
    import youtube as YT
    return YT


def youtube_conectar(dados):
    pasta = dados["canal"]

    def rodar():
        YT_STATUS[pasta] = "abrindo o navegador: escolha a conta e o canal e autorize"
        try:
            YT = _yt()
            info = YT.autenticar(pasta)
            arq = RAIZ / pasta / "canal.json"
            with TRAVA:
                cfg = copy.deepcopy(ler(arq))
                cfg["youtube"] = {**info, "conectado_em": datetime.now().strftime("%Y-%m-%d %H:%M")}
                gravar(arq, cfg)
            esperado = (cfg.get("handle") or "").lstrip("@").lower()
            if esperado and info.get("handle", "").lstrip("@").lower() != esperado:
                YT_STATUS[pasta] = f"ATENÇÃO: conectou {info.get('handle')} ({info.get('titulo')}), mas este canal é @{esperado}. Conecte de novo com o canal certo."
            else:
                YT_STATUS[pasta] = f"conectado: {info.get('titulo')} {info.get('handle')}"
        except Exception as e:
            YT_STATUS[pasta] = f"falhou: {e}"
    threading.Thread(target=rodar, daemon=True).start()
    return {"ok": True}


def youtube_auto(dados):
    arq = RAIZ / dados["canal"] / "canal.json"
    with TRAVA:
        cfg = copy.deepcopy(ler(arq))
        cfg.setdefault("publicacao", {})["auto_upload"] = bool(dados.get("ligado"))
        gravar(arq, cfg)
    return {"ok": True}


def _candidatos_envio(est):
    """Shorts aprovados, ainda não enviados, de fonte LIBERADA, em canais com envio automático ligado."""
    YT = _yt()
    for canal_dir in canais():
        cfg = ler(canal_dir / "canal.json", {}) or {}
        if not (cfg.get("publicacao", {}).get("auto_upload") and YT.conectado(canal_dir.name)):
            continue
        for ep in sorted((canal_dir / "episodios").glob("*")):
            info = ler(ep / "info.json", {}) or {}
            fonte = fonte_do_info(cfg, info)
            if not (fonte and fonte.get("status") == "LIBERADO"):
                continue
            plano = ler(ep / "cortes.json", {}) or {}
            for c in plano.get("cortes", []):
                k = f"{canal_dir.name}/{ep.name}/{c['id']}"
                s = est["shorts"].get(k, {})
                if s.get("aprovacao") == "aprovado" and not s.get("publicado") and not s.get("youtube") and not s.get("fora_padrao"):
                    yield canal_dir, cfg, ep, info, fonte, c, k


def trabalhador_youtube():
    from datetime import timezone as _tz
    while True:
        time.sleep(300)
        item = None
        try:
            est = estado()
            hoje = datetime.now().strftime("%Y-%m-%d")
            cota = est.get("youtube_cota", {})
            feitos = cota.get("n", 0) if cota.get("dia") == hoje else 0
            if feitos >= COTA_DIA:
                continue
            item = next(_candidatos_envio(est), None)
            if not item:
                continue
            YT = _yt()
            canal_dir, cfg, ep, info, fonte, c, k = item
            YT.confere_canal(canal_dir.name, cfg)
            saida = saida_do_ep(canal_dir, ep.name)
            mp4 = sorted((saida / "shorts").glob(f"{c['id']} - *.mp4"))[0]
            up = ler_txt_upload(mp4.with_suffix(".txt"))
            ocupados = [v["youtube"]["agendado"] for kk, v in est["shorts"].items()
                        if kk.startswith(canal_dir.name + "/") and v.get("youtube")]
            minimo = None
            if fonte.get("espera_horas") and info.get("timestamp"):
                minimo = datetime.fromtimestamp(info["timestamp"], _tz.utc) + timedelta(hours=fonte["espera_horas"])
            quando = YT.proximo_horario(cfg, ocupados, minimo)
            vid = YT.enviar_short(canal_dir.name, cfg, mp4, up.get("titulo", c.get("titulo_short", "")), up.get("descricao", ""),
                                  [x.strip() for x in up.get("tags", "").split(",")], quando)
            with TRAVA:
                e2 = estado(fresco=True)
                sh = e2["shorts"].setdefault(k, {})
                sh["youtube"] = {"id": vid, "agendado": quando, "enviado_em": datetime.now().strftime("%Y-%m-%d %H:%M")}
                sh["publicado"] = quando[:10]
                sh["link"] = f"https://youtube.com/shorts/{vid}"
                sh.pop("youtube_erro", None)
                e2["youtube_cota"] = {"dia": hoje, "n": feitos + 1}
                gravar(ESTADO, e2)
            notificar("Short agendado no YouTube", f"{up.get('titulo', '')[:80]} → {quando[:16].replace('T', ' ')} UTC")
        except Exception as e:
            print("youtube:", e, flush=True)
            try:
                if item:
                    with TRAVA:
                        e2 = estado(fresco=True)
                        e2["shorts"].setdefault(item[6], {})["youtube_erro"] = f"{type(e).__name__}: {e}"[:300]
                        gravar(ESTADO, e2)
                    notificar("Envio pro YouTube falhou", f"{type(e).__name__}: {str(e)[:100]}")
            except Exception:
                pass


def processos_com(trecho):
    """PIDs de processos cuja linha de comando contém o trecho (pra não repetir trabalho que ainda está rodando)."""
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command",
                              "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*" + trecho.replace("'", "") +
                              "*' -and $_.CommandLine -notlike '*Get-CimInstance*' } | ForEach-Object { $_.ProcessId }"],
                             capture_output=True, text=True, creationflags=SEM_JANELA, timeout=60).stdout
        return [int(x) for x in out.split() if x.strip().isdigit()]
    except Exception:
        return []


def _esperar_e_concluir(item, trecho):
    """O painel foi reiniciado no meio: espera o processo antigo terminar e confere o resultado."""
    global PREPARO_ATIVO
    PREPARO_ATIVO = True
    while processos_com(trecho):
        time.sleep(30)
    ep = RAIZ / item["canal"] / "episodios" / item["id"]
    ok = (ep / "video.mp4").exists() and (ep / "transcricao.json").exists()
    _atualizar_fila(item["id"], status=("curadoria na fila" if item.get("auto", True) else "pronto") if ok else "erro",
                    fim=datetime.now().strftime("%H:%M"), **({} if ok else {"erro": "processo terminou sem vídeo/transcrição"}))
    PREPARO_ATIVO = False
    FILA_EVENTO.set()


def trabalhador_preparo():
    """Um episódio por vez: lote.py (registra a fonte, baixa e transcreve), confere imagem parada e, se o
    "automático" estiver ligado, chama a curadoria automática (Claude) que renderiza e confere."""
    global PREPARO_ATIVO, ULTIMO_PEDIDO
    retomar, retomar_cur = [], []
    with TRAVA:   # o que estava no meio quando o painel fechou: se o processo ainda roda, espera; senão volta pra fila
        est = estado(fresco=True)
        for x in est.get("fila_preparo", []):
            if x["status"] == "preparando":
                if processos_com(f"preparo_{x['id']}.json"):
                    retomar.append((x, f"preparo_{x['id']}.json"))
                else:
                    x["status"] = "aguardando"
            elif x["status"] == "curadoria":
                if processos_com(f"Episódio {x['id']} do canal"):
                    retomar_cur.append(x)
                else:
                    x["status"] = "curadoria na fila"
        gravar(ESTADO, est)
    for x, trecho in retomar:
        _esperar_e_concluir(x, trecho)
    for x in retomar_cur:     # sessão do Claude ainda rodando: espera e fecha o resultado (em fila, um por vez)
        global PREPARO_ATIVO
        PREPARO_ATIVO = True
        try:
            fim = curadoria_auto(x, ja_rodando=True)
        except Exception as e:
            fim = {"status": "erro", "erro": f"{type(e).__name__}: {e}"[:300]}
        _atualizar_fila(x["id"], fim=datetime.now().strftime("%H:%M"), **fim)
        if fim.get("status") == "shorts prontos":
            notificar("Shorts prontos para aprovar", f"{x.get('titulo', x['id'])[:90]}")
        PREPARO_ATIVO = False
    while True:
        FILA_EVENTO.wait(15)
        FILA_EVENTO.clear()
        fila_atual = estado().get("fila_preparo", [])
        prox = next((x for x in fila_atual if x["status"] == "aguardando"), None)
        cur = next((x for x in fila_atual if x["status"] == "curadoria na fila"), None)
        if not prox and cur:
            PREPARO_ATIVO = True
            _atualizar_fila(cur["id"], status="curadoria", inicio_cur=datetime.now().strftime("%H:%M"))
            try:
                fim = curadoria_auto(cur)
            except Exception as e:
                fim = {"status": "erro", "erro": f"{type(e).__name__}: {e}"[:300]}
            _atualizar_fila(cur["id"], fim=datetime.now().strftime("%H:%M"), **fim)
            if fim.get("status") == "shorts prontos":
                notificar("Shorts prontos para aprovar", f"{cur.get('titulo', cur['id'])[:90]}")
            elif fim.get("status") == "erro":
                notificar("Curadoria automática falhou", f"{cur.get('titulo', cur['id'])[:60]}: {fim.get('erro', '')[:80]}")
            PREPARO_ATIVO = False
            ULTIMO_PEDIDO = time.time()
            FILA_EVENTO.set()
            continue
        if not prox:
            continue
        PREPARO_ATIVO = True
        vid = prox["id"]
        _atualizar_fila(vid, status="preparando", inicio=datetime.now().strftime("%H:%M"))
        lote = PESQ / f"preparo_{vid}.json"
        lote.write_text(json.dumps([{k: prox[k] for k in ("canal", "fonte", "fonte_url", "id")}], ensure_ascii=False), encoding="utf-8")
        with open(PESQ / f"preparo_{vid}.log", "w", encoding="utf-8") as log:
            subprocess.run([str(PY), "-u", str(MOTOR / "lote.py"), str(lote), str(PESQ / "nichos_resultado.json")],
                           cwd=str(MOTOR), stdout=log, stderr=subprocess.STDOUT, creationflags=SEM_JANELA,
                           env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        ep = RAIZ / prox["canal"] / "episodios" / vid
        if (ep / "video.mp4").exists() and (ep / "transcricao.json").exists():
            fim = {"status": "curadoria na fila" if prox.get("auto", True) else "pronto"}
            try:
                sys.path.insert(0, str(MOTOR))
                from video_parado import medir
                m = medir(ep / "video.mp4")
                if m and m["parado"]:
                    (ep / "NAO CORTAR - motivo.txt").write_text(
                        f"Imagem parada ({int(m['iguais'] * 100)}% dos quadros iguais): podcast só áudio, não serve para Shorts.\n",
                        encoding="utf-8")
                    fim = {"status": "imagem parada"}
            except Exception as e:
                print("video_parado", vid, e, flush=True)
        else:
            ultima = ler_texto(PESQ / f"preparo_{vid}.log").strip().splitlines()[-1:] or ["sem log"]
            fim = {"status": "erro", "erro": ultima[0][:300]}
        _atualizar_fila(vid, fim=datetime.now().strftime("%H:%M"), **fim)
        PREPARO_ATIVO = False
        ULTIMO_PEDIDO = time.time()
        FILA_EVENTO.set()


# ---------- HTTP ----------
def acesso_permitido(handler):
    """Janela no próprio PC: sempre. Pelo Tailscale (celular): só as contas em _segredos/painel_acesso.json."""
    login = handler.headers.get("Tailscale-User-Login")
    if login is None:
        return handler.client_address[0] in ("127.0.0.1", "::1")
    permitidos = (ler(RAIZ / "_segredos" / "painel_acesso.json", {}) or {}).get("permitidos", [])
    return login.lower() in [p.lower() for p in permitidos]


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _bloquear(self):
        corpo = "<h1>Acesso negado</h1><p>Esta conta não tem acesso ao painel Gato Preto.</p>".encode("utf-8")
        self.send_response(403)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def _json(self, obj, cod=200):
        b = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(cod)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b)

    def _versionado(self, dados, q):
        """Manda {"v", "dados"}; se o navegador já tem essa versão, responde só {"igual": true}."""
        v = versao(dados)
        if q.get("v", [""])[0] == v:
            return self._json({"igual": True, "v": v})
        return self._json({"v": v, "dados": dados})

    def do_GET(self):
        global ULTIMO_PEDIDO
        if not acesso_permitido(self):
            return self._bloquear()
        ULTIMO_PEDIDO = time.time()
        u = urlparse(self.path)
        q = parse_qs(u.query)
        partes = [unquote(x) for x in u.path.strip("/").split("/") if x]
        try:
            if not partes:
                return self._arquivo(AQUI / "index.html", raiz=AQUI)
            if partes[0] in ("icone.png", "icone.ico", "icone-180.png", "icone-192.png", "icone-512.png", "manifest.webmanifest"):
                return self._arquivo(AQUI / partes[0], raiz=AQUI)
            if partes[0] == "api":
                if partes[1:] == ["ping"]:
                    return self._json({"ok": True})
                if partes[1:] == ["geral"]:
                    return self._versionado(visao_geral(), q)
                if partes[1:] == ["radar"]:
                    return self._versionado(radar_dados(), q)
                if partes[1:] == ["publicacao"]:
                    return self._versionado(publicacao_dados(), q)
                if partes[1:] == ["disco"]:
                    return self._json(disco_dados())
                if partes[1:] == ["fontes_novas"]:
                    return self._versionado(fontes_novas_dados(), q)
                if partes[1] == "revisar":
                    return self._versionado(revisar_dados(*(partes[2:4] + [None, None])[:2]), q)
                if partes[1] == "canal" and len(partes) == 3:
                    return self._versionado(resumo_canal(RAIZ / partes[2], estado(), detalhe=True), q)
                if partes[1] == "episodio" and len(partes) == 4:
                    cd = RAIZ / partes[2]
                    cfg = ler(cd / "canal.json", {})
                    d = episodio(cd, cfg, cd / "episodios" / partes[3], estado(), detalhe=True)
                    d["canal"] = partes[2]
                    d["canal_nome"] = cfg.get("nome")
                    return self._versionado(d, q)
            if partes[0] == "poster" and len(partes) == 4:
                jpg = poster(partes[1], partes[2], partes[3].removesuffix(".jpg"))
                return self._arquivo(jpg, raiz=RAIZ, cache="max-age=86400") if jpg else self._json({"erro": "sem vídeo"}, 404)
            if partes[0] == "f":
                return self._arquivo(RAIZ / "/".join(partes[1:]), raiz=RAIZ)
            self._json({"erro": "não encontrado"}, 404)
        except (ConnectionError, BrokenPipeError):
            pass
        except Exception as e:
            self._json({"erro": f"{type(e).__name__}: {e}"}, 500)

    def do_POST(self):
        global ULTIMO_PEDIDO
        if not acesso_permitido(self):
            return self._bloquear()
        ULTIMO_PEDIDO = time.time()
        n = int(self.headers.get("Content-Length") or 0)
        dados = json.loads(self.rfile.read(n) or b"{}")
        rota = self.path.strip("/")
        try:
            if rota == "api/short":
                r = marcar_short(dados)
            elif rota == "api/fonte":
                r = marcar_fonte(dados)
            elif rota == "api/radar/rodar":
                r = rodar_radar()
            elif rota == "api/radar/decidir":
                r = decidir_radar(dados)
            elif rota == "api/auto":
                r = pedir_auto(dados)
            elif rota == "api/disco/limpar":
                r = limpar_disco(dados)
            elif rota == "api/fontes_novas/decidir":
                r = decidir_fonte_nova(dados)
            elif rota == "api/youtube/conectar":
                r = youtube_conectar(dados)
            elif rota == "api/youtube/auto":
                r = youtube_auto(dados)
            elif rota == "api/piloto":
                r = piloto_config(dados)
            elif rota == "api/abrir":
                p = (RAIZ / dados["caminho"]).resolve()
                if RAIZ not in p.parents and p != RAIZ:
                    r = {"erro": "fora de F:\\CORTES"}
                else:
                    os.startfile(p if p.is_dir() else p.parent)
                    r = {"ok": True}
            else:
                r = {"erro": "rota desconhecida"}
            self._json(r, 400 if "erro" in r else 200)
        except Exception as e:
            self._json({"erro": f"{type(e).__name__}: {e}"}, 500)

    def _arquivo(self, p, raiz, cache=None):
        p = p.resolve()
        if raiz.resolve() not in p.parents or not p.is_file():
            return self._json({"erro": "arquivo não encontrado"}, 404)
        tam = p.stat().st_size
        tipo = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        if tipo.startswith("text/") or tipo.endswith("javascript"):
            tipo += "; charset=utf-8"
        ini, fim, cod = 0, tam - 1, 200
        m = re.match(r"bytes=(\d*)-(\d*)", self.headers.get("Range") or "")
        if m and tam:
            if m.group(1):
                ini = int(m.group(1))
                fim = min(int(m.group(2)), tam - 1) if m.group(2) else tam - 1
            elif m.group(2):
                ini = max(0, tam - int(m.group(2)))
            cod = 206
        self.send_response(cod)
        self.send_header("Content-Type", tipo)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(fim - ini + 1))
        if cod == 206:
            self.send_header("Content-Range", f"bytes {ini}-{fim}/{tam}")
        self.send_header("Cache-Control", cache or ("no-cache" if raiz == AQUI else "max-age=3600"))
        self.end_headers()
        try:
            with open(p, "rb") as f:
                f.seek(ini)
                resta = fim - ini + 1
                while resta > 0:
                    bloco = f.read(min(512 * 1024, resta))
                    if not bloco:
                        break
                    self.wfile.write(bloco)
                    resta -= len(bloco)
        except (ConnectionError, BrokenPipeError):
            pass     # navegador cancelou (normal ao pular no vídeo)


def main():
    porta = int(sys.argv[sys.argv.index("--porta") + 1]) if "--porta" in sys.argv else 8765
    srv = ThreadingHTTPServer(("127.0.0.1", porta), H)
    srv.daemon_threads = True
    url = f"http://localhost:{porta}"
    print(f"Painel da fábrica de cortes em {url}  (Ctrl+C pra fechar)", flush=True)
    if "--nao-abrir" not in sys.argv:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    threading.Thread(target=aquecer_posters, daemon=True).start()
    threading.Thread(target=trabalhador_preparo, daemon=True).start()
    threading.Thread(target=trabalhador_correcoes, daemon=True).start()
    threading.Thread(target=trabalhador_youtube, daemon=True).start()
    threading.Thread(target=trabalhador_desempenho, daemon=True).start()
    threading.Thread(target=vigia_radar, daemon=True).start()
    threading.Thread(target=trabalhador_piloto, daemon=True).start()
    threading.Thread(target=resumo_diario, daemon=True).start()
    if "--auto-desligar" in sys.argv:
        # aberto pelo atalho: desliga sozinho uns minutos depois que a janela do painel é fechada
        def vigiar():
            while time.time() - ULTIMO_PEDIDO < 300 or PREPARO_ATIVO or radar_rodando():
                time.sleep(15)
            print("sem acesso há 5 min — desligando", flush=True)
            srv.shutdown()
        threading.Thread(target=vigiar, daemon=True).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
