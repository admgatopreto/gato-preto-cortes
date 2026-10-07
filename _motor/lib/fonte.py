"""Fontes (podcasts): auditoria de permissão de cortes e download de episódios."""
import json, re, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path
from util import log, run, salvar_json, ler_json, pasta_canal, config_canal

LANG = ["--extractor-args", "youtube:lang=pt"]

# Frases que os podcasts usam na descrição. Ordem importa: proibição vence liberação.
PADROES_PROIBIDO = [
    r"cortes?\s+n[ãa]o\s+(s[ãa]o\s+|est[ãa]o\s+)?(permitid|autorizad|liberad)",
    r"proibid[oa]s?\s+(fazer\s+|os\s+)?cortes?",
    r"n[ãa]o\s+(é\s+)?(permitid|autorizad)[oa]s?\s+(fazer\s+|a\s+)?(cria[çc][ãa]o\s+de\s+)?cortes?",
    r"cortes?[^.\n]{0,40}sem\s+autoriza[çc][ãa]o",
    r"n[ãa]o\s+autorizamos\s+cortes?",
]
PADROES_LIBERADO = [
    r"cortes?\s+(est[ãa]o\s+|s[ãa]o\s+|totalmente\s+)?(liberad|permitid|autorizad)",
    r"pode(m)?\s+(fazer|postar|criar|publicar)\s+cortes?",
    r"libera(mos|do|dos)\s+(os\s+)?cortes?",
    r"cortes?\s+s[ãa]o\s+bem[\s-]?vindos?",
    r"fa[çc]a\s+(seus?\s+)?cortes?",
]
PADRAO_ESPERA = r"(\d{1,3})\s*(h\b|hrs?\b|horas?)"
# permissão que depende de pedir/combinar algo antes = CONDICIONAL (não baixa até confirmar)
PADRAO_CONDICAO = r"(desde que|entre(m)? em contato|e-?mail|autoriza[çc][ãa]o pr[ée]via|solicit|pe[çc]a|consult)"


def _ytdlp_json_lista(url, n, completo=False):
    out = run(["yt-dlp", *LANG, "--flat-playlist", "-I", f"1:{n}", "-J", url])
    d = json.loads(out)
    return d if completo else (d.get("entries", []) or [])


PADRAO_EMAIL = r"[\w.+-]+@[\w-]+\.[\w.]+"


def _descricao(video_id):
    out = run(["yt-dlp", *LANG, "--skip-download", "-J", f"https://youtu.be/{video_id}"])
    return json.loads(out)


def classificar_descricao(desc):
    d = desc or ""
    achados = {"proibido": [], "liberado": [], "espera_horas": None}
    for p in PADROES_PROIBIDO:
        for m in re.finditer(p, d, re.I):
            achados["proibido"].append(_trecho(d, m))
    for p in PADROES_LIBERADO:
        for m in re.finditer(p, d, re.I):
            achados["liberado"].append(_trecho(d, m))
    for t in achados["liberado"]:
        m = re.search(PADRAO_ESPERA, t, re.I)
        if m:
            achados["espera_horas"] = int(m.group(1))
    return achados


def _trecho(d, m, linhas_depois=3):
    """Linha do achado + as linhas seguintes (onde costumam vir as regras)."""
    ini = d.rfind("\n", 0, m.start()) + 1
    fim = m.end()
    for _ in range(linhas_depois + 1):
        prox = d.find("\n", fim + 1)
        if prox == -1:
            fim = len(d)
            break
        fim = prox
    linhas = [l.strip() for l in d[ini:fim].split("\n") if l.strip()]
    corte = []
    for l in linhas:   # para no primeiro link/hashtag solto (já não é regra)
        if corte and (l.startswith("#") or (l.startswith("http") and len(l.split()) == 1)):
            break
        corte.append(l)
    return " / ".join(corte)[:400]


def auditar(url_canal, n_episodios=6, duracao_min=1200):
    """Lê a descrição dos últimos episódios longos de um canal e classifica a permissão de cortes."""
    url_canal = url_canal.rstrip("/")
    entradas, sobre = [], ""
    for aba in ("/videos", "/streams"):
        try:
            d = _ytdlp_json_lista(url_canal + aba, 30, completo=True)
            entradas += d.get("entries", []) or []
            sobre = sobre or d.get("description") or ""     # aba "Sobre" do canal
        except Exception:
            pass
    a_sobre = classificar_descricao(sobre)
    emails = list(dict.fromkeys(re.findall(PADRAO_EMAIL, sobre)))
    longos = [e for e in entradas if (e.get("duration") or 0) >= duracao_min][:n_episodios + 3]
    if not longos:
        return {"canal_url": url_canal, "status": "SEM EPISÓDIOS LONGOS", "episodios": [], "emails": emails}
    eps, prob, lib, espera, nome = [], 0, 0, None, None
    for e in longos:
        if len(eps) >= n_episodios:
            break
        try:
            info = _descricao(e["id"])
        except Exception:      # vídeo de membros/estreia/privado: pula e lê o próximo
            continue
        nome = nome or info.get("channel")
        a = classificar_descricao(info.get("description"))
        prob += bool(a["proibido"]); lib += bool(a["liberado"])
        espera = espera or a["espera_horas"]
        eps.append({"id": e["id"], "titulo": info.get("title"), "data": info.get("upload_date"),
                    "proibido": a["proibido"][:2], "liberado": a["liberado"][:2]})
    if a_sobre["proibido"] or a_sobre["liberado"]:     # regra escrita no "Sobre" vale como mais um episódio
        eps.insert(0, {"id": "SOBRE", "titulo": "aba Sobre do canal", "data": None,
                       "proibido": a_sobre["proibido"][:2], "liberado": a_sobre["liberado"][:2]})
        prob += bool(a_sobre["proibido"]); lib += bool(a_sobre["liberado"])
        espera = espera or a_sobre["espera_horas"]
    for e in eps:
        emails += [m for t in e["liberado"] + e["proibido"] for m in re.findall(PADRAO_EMAIL, t)]
    emails = list(dict.fromkeys(emails))
    condicional = any(re.search(PADRAO_CONDICAO, t, re.I) for e in eps for t in e["liberado"])
    if prob:
        status = "PROIBIDO"
    elif lib and condicional:
        status = "CONDICIONAL"   # ex.: "permitidos desde que siga as regras: contato por e-mail"
    elif lib:
        status = "LIBERADO"
    else:
        status = "SEM MENÇÃO"   # não é permissão: tratar como proibido até confirmar por outro meio
    return {"canal": nome, "canal_url": url_canal, "status": status,
            "episodios_com_liberacao": lib, "episodios_com_proibicao": prob, "episodios_lidos": len(eps),
            "espera_horas": espera, "emails": emails, "auditado_em": datetime.now().strftime("%Y-%m-%d"),
            "episodios": eps}


def fonte_do_video(cfg, info):
    url_canal = (info.get("channel_url") or "").rstrip("/")
    cid = info.get("channel_id")
    for f in cfg.get("fontes", []):
        u = f.get("canal_url", "").rstrip("/")
        if u and (u == url_canal or (cid and cid in u) or u.lower().endswith("/" + str(info.get("uploader_id", "")).lower())):
            return f
    return None


def baixar(canal, url, forcar=False):
    cfg = config_canal(canal)
    base = pasta_canal(canal)
    info = json.loads(run(["yt-dlp", *LANG, "--skip-download", "-J", url]))
    vid = info["id"]
    fonte = fonte_do_video(cfg, info)
    if not fonte:
        msg = f"O canal '{info.get('channel')}' ({info.get('channel_url')}) não está em 'fontes' do canal.json. Audite antes: cortes auditar <url do canal> --canal {canal} --adicionar"
        if not forcar:
            sys.exit(msg)
        log("AVISO:", msg)
    elif fonte.get("status") != "LIBERADO" and not forcar:
        sys.exit(f"Fonte '{fonte.get('canal')}' está como {fonte.get('status')} — não baixo sem --forcar. "
                 "Se a autorização veio por e-mail/DM, edite o status no canal.json pra LIBERADO e anote a prova em 'evidencia'.")
    # regra de espera (ex.: Praticast/Podpah = 24h depois do episódio)
    espera = (fonte or {}).get("espera_horas") or 0
    ts = info.get("release_timestamp") or info.get("timestamp")
    if espera and ts:
        horas = (datetime.now(timezone.utc).timestamp() - ts) / 3600
        if horas < espera:
            log(f"⚠ Episódio tem {horas:.0f}h. Regra da fonte: só postar cortes após {espera}h. Pode baixar e editar, mas NÃO publicar antes.")
    destino = base / "episodios" / vid
    destino.mkdir(parents=True, exist_ok=True)
    salvar_json(destino / "info.json", {k: info.get(k) for k in (
        "id", "title", "channel", "channel_url", "uploader_id", "upload_date", "timestamp",
        "duration", "description", "webpage_url", "chapters")})
    if (destino / "video.mp4").exists():
        log("Vídeo já baixado:", destino / "video.mp4")
        return destino
    log(f"Baixando {vid} — {info.get('title')} ({info.get('duration_string')})")
    # 1080p H.264 comum (137): ~0,4 GB/h. O "premium" 616 (VP9) tem 4-5x o tamanho sem ganho visível. 4 partes em paralelo
    # YouTube às vezes devolve HTTP 403 no meio do download (intermitente, some sozinho minutos depois).
    # Até 4 tentativas com espera crescente; o yt-dlp continua do .part quando dá.
    import time
    for tentativa in range(1, 5):
        try:
            run(["yt-dlp", "-N", "4", "-f",
                 "137+140/bv*[height<=1080][vcodec^=avc1]+ba[ext=m4a]/bv*[height<=1080]+ba/b[height<=1080]",
                 "--merge-output-format", "mp4", "-o", str(destino / "video.%(ext)s"), "-q", "--no-warnings",
                 f"https://youtu.be/{vid}"])
            break
        except Exception as ex:
            if tentativa == 4 or "403" not in str(ex):
                raise
            log(f"⚠ HTTP 403 no download (tentativa {tentativa}/4). Nova tentativa em {tentativa * 2} min.")
            time.sleep(tentativa * 120)
    log("OK:", destino / "video.mp4")
    return destino
