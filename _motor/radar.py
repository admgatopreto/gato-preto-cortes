"""Radar de episódios: procura episódios longos novos das fontes e candidatos de cada canal, pontua e filtra
ANTES de baixar. Resultado em _pesquisa/radar.json (o painel mostra na aba "Novos episódios").

O que aprendemos no lote 1 e virou filtro aqui:
  - "mais recente" não é critério → nota pelo desempenho (visualizações por dia vs. a média do próprio canal)
  - imagem parada (podcast só áudio com capa) → tira de miniaturas do YouTube (sb2), sem baixar o vídeo
  - política/campanha fora do canal de Política, live de vendas, live lendo chat → palavras no título/descrição
  - canal fora do nicho → candidatos com "nao_usar" no canal.json são pulados
  - nunca repetir descartado → _pesquisa/descartados.json (exceto os marcados "retentar")
Uso: python radar.py [--canal canal-tema8-games] [--por-fonte 12]"""
import json, re, statistics, sys, time, traceback, urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "lib"))
if sys.stdout:
    sys.stdout.reconfigure(encoding="utf-8")
from util import RAIZ, run   # noqa: E402

PESQ = RAIZ / "_pesquisa"
SAIDA = PESQ / "radar.json"
STATUS = PESQ / "radar.status.json"
LANG = ["--extractor-args", "youtube:lang=pt"]
MIN_S, MAX_S = 40 * 60, 4 * 3600
POR_FONTE = int(sys.argv[sys.argv.index("--por-fonte") + 1]) if "--por-fonte" in sys.argv else 12
SO_CANAL = sys.argv[sys.argv.index("--canal") + 1] if "--canal" in sys.argv else None

RX = {
    "politica": re.compile(r"\b(candidat\w*|elei[çc][ãa]o|elei[çc][õo]es|eleitora\w*|voto|votar|bolsonar\w*|lula\b|petista\w*|"
                           r"esquerdista\w*|direitista\w*|esquerda|direita|deputad\w*|senador\w*|stf|partido|pt\b|pl\b|"
                           r"presidente|presid[êe]ncia|pol[íi]tic[ao]s?|governo|ministro|campanha eleitoral)", re.I),
    "crime_nomeado": re.compile(r"(inocente\?|culpad[oa]\?|acusad[oa]|suspeit[oa]|vaza(m|ram) [áa]udios|investigad[oa]|"
                                r"foi pres[oa]|é pres[oa]|mandante|assassin[oa] de)", re.I),
    "evento": re.compile(r"(lan[çc]amento d[eo]s? (foguete|astronautas|miss[ãa]o)|transmiss[ãa]o (ao vivo|oficial)|"
                         r"\bjogo completo\b|partida completa|cobertura ao vivo|narra[çc][ãa]o|pr[ée]-jogo|p[óo]s-jogo|"
                         r"\bcrew-?\d+|acoplagem|acoplamento|esta[çc][ãa]o espacial|\breact\b|discurso (ao vivo|hist[óo]rico))", re.I),
    "eleitoral": re.compile(r"\b(bolsonar\w*|lula\b|fl[áa]vio\b|petista\w*|esquerdista\w*|candidat\w*|elei[çc]\w+|"
                            r"eleitor\w*|voto|votar|debate da globo|debate presidencial|tse\b|nikolas|tarc[íi]sio|haddad|boulos|"
                            r"mar[çc]al|ciro gomes|moraes)", re.I),
    "morte": re.compile(r"(morte d[eo]|morreu|assassinat[oa])", re.I),
    "campanha": re.compile(r"(candidat[oa] a|vote\b|vote em|meu n[úu]mero|n[úu]mero \d{2,5}\b|pedi(u|ndo) voto|santinho)", re.I),
    "vendas": re.compile(r"\b(inscri[çc][õo]es|inscreva-se na|lan[çc]amento do curso|mentoria|imers[ãa]o|black friday|"
                         r"aula gratuita|vagas abertas|garanta sua vaga|webinar|masterclass)", re.I),
    "chat": re.compile(r"\b(lendo o chat|respondendo (o chat|perguntas)|live de perguntas|q&a|react)\b", re.I),
}


PT = set("de que não nao é o a os as com para um uma do da dos das em no na você voce mais por como mas isso ele ela eu "
         "tem foi ser vai muito sobre quando já ja também tambem porque".split())
OUTRAS = set("the and you of to in is we for with this that my our der die und mit ist zu das nicht ein eine el los las "
             "del por qué que con una para es".split()) - PT


def portugues(texto):
    """Conta palavras comuns: título+descrição em PT têm bem mais 'de/que/não/você' do que 'the/and/der/und'."""
    ps = re.findall(r"[a-zà-ú]+", texto.lower())
    pt, out = sum(w in PT for w in ps), sum(w in OUTRAS for w in ps)
    if pt + out < 4:
        return None            # pouco texto pra saber
    return pt >= 2 * out


def status(**kw):
    atual = json.loads(STATUS.read_text(encoding="utf-8")) if STATUS.exists() else {}
    atual.update(kw)
    STATUS.write_text(json.dumps(atual, ensure_ascii=False), encoding="utf-8")


def ytdlp_json(args, tentativas=2):
    for t in range(tentativas):
        try:
            return json.loads(run(["yt-dlp", *args]))
        except Exception:
            if t == tentativas - 1:
                raise
            time.sleep(5)


def fontes_do_canal(cfg):
    """Fontes cadastradas + candidatos do ranking, sem os marcados como não usar."""
    vistas, saida = set(), []
    proibidos = {"PROIBIDO", "NEGADO"}
    for f in cfg.get("fontes", []):
        u = (f.get("canal_url") or "").rstrip("/")
        if u and u not in vistas and f.get("status") not in proibidos:
            vistas.add(u)
            saida.append({"nome": f["canal"], "url": u, "status": f.get("status"), "tipo": "fonte"})
    for c in cfg.get("candidatos", []):
        u = (c.get("canal_url") or "").rstrip("/")
        if u and u not in vistas and not c.get("nao_usar") and c.get("status") not in proibidos:
            vistas.add(u)
            saida.append({"nome": c["canal"], "url": u, "status": c.get("status"), "tipo": "candidato",
                          "inscritos": c.get("inscritos")})
    for f in cfg.get("fontes_descartadas", []):
        vistas.add((f.get("canal_url") or "").rstrip("/"))
    return saida


def listar(fonte):
    """Últimos episódios (abas /videos e /streams) — lista rápida, sem abrir cada vídeo."""
    ents = []
    for aba in ("/videos", "/streams"):
        try:
            # sem lang=pt: com ele a lista rápida traz "200 mil visualizações" como 200
            d = ytdlp_json(["--flat-playlist", "-I", f"1:{POR_FONTE}", "-J", fonte["url"] + aba])
            ents += [e for e in (d.get("entries") or []) if e.get("id")]
        except Exception:
            pass
    return ents


def imagem_parada(info):
    """Usa a tira de miniaturas (sb2: grade 10x10 de quadros 80x45, ~1 a cada 10 s). Baixa 3 imagens pequenas."""
    try:
        import cv2, numpy as np
        sb = next((f for f in info.get("formats", []) if f.get("format_id") == "sb2"), None)
        if not sb or not sb.get("fragments"):
            return None
        frs = sb["fragments"]
        escolha = [frs[i] for i in sorted({0, len(frs) // 2, len(frs) - 1})]
        tiles = []
        for fr in escolha:
            url = fr.get("url") or (sb.get("fragment_base_url", "") + fr.get("path", ""))
            dado = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=20).read()
            im = cv2.imdecode(np.frombuffer(dado, np.uint8), cv2.IMREAD_GRAYSCALE)
            if im is None:
                continue
            h, w = sb.get("height") or 45, sb.get("width") or 80
            for r in range(im.shape[0] // h):
                for c in range(im.shape[1] // w):
                    t = im[r * h:(r + 1) * h, c * w:(c + 1) * w].astype(np.float32)
                    if t.mean() > 3:          # pula quadro preto (fim da grade)
                        tiles.append(t)
        if len(tiles) < 10:
            return None
        difs = [float(np.mean(np.abs(a - b))) for a, b in zip(tiles, tiles[1:])]
        iguais = sum(d < 2.5 for d in difs) / len(difs)
        return round(iguais, 2)
    except Exception:
        return None


CACHE_INFO = PESQ / "radar_cache"
PAUSA_ROBO = {"ate": 0.0}


def info_video(vid):
    """yt-dlp -J com cache de 12 h e pausa quando o YouTube pede 'confirme que não é robô'."""
    CACHE_INFO.mkdir(exist_ok=True)
    arq = CACHE_INFO / f"{vid}.json"
    if arq.exists() and time.time() - arq.stat().st_mtime < 12 * 3600:
        return json.loads(arq.read_text(encoding="utf-8"))
    for tentativa in range(4):
        espera = PAUSA_ROBO["ate"] - time.time()
        if espera > 0:
            time.sleep(espera)
        try:
            info = json.loads(run(["yt-dlp", *LANG, "--skip-download", "-J", f"https://www.youtube.com/watch?v={vid}"]))
            leve = {k: info.get(k) for k in ("id", "title", "description", "chapters", "view_count", "upload_date",
                                             "duration", "live_status")}
            leve["formats"] = [f for f in info.get("formats", []) if f.get("format_id") == "sb2"]
            arq.write_text(json.dumps(leve, ensure_ascii=False), encoding="utf-8")
            time.sleep(1.5)   # devagar: muitas consultas seguidas fazem o YouTube pedir login
            return leve
        except Exception as ex:
            if "bot" in str(ex) or "login" in str(ex).lower() or "429" in str(ex):
                PAUSA_ROBO["ate"] = max(PAUSA_ROBO["ate"], time.time() + 90 * (tentativa + 1))
                continue
            raise
    raise RuntimeError("YouTube pediu verificação de robô 4 vezes seguidas")


def avaliar(canal, nicho, fonte, ent, mediana_views):
    """Abre o vídeo (yt-dlp -J, com cache), calcula desempenho e avisos."""
    info = info_video(ent["id"])
    views = info.get("view_count") or ent.get("view_count") or 0
    up = info.get("upload_date")
    dias = max(1, (date.today() - datetime.strptime(up, "%Y%m%d").date()).days) if up else 30
    texto = " ".join([info.get("title") or "", (info.get("description") or "")[:1500],
                      " ".join(c.get("title", "") for c in (info.get("chapters") or []))])
    avisos, bloqueado = [], False

    def av(nivel, t):
        avisos.append({"nivel": nivel, "texto": t})

    pol = sorted({m.group(0).lower() for m in RX["politica"].finditer(texto)})
    pol_titulo = sorted({m.group(0).lower() for m in RX["politica"].finditer(info.get("title") or "")})
    if nicho == "politica":
        if RX["campanha"].search(texto):
            av("grave", "Parece campanha (candidato/número/pedido de voto). Até o 2º turno (25/10), só aula e análise.")
        elif RX["eleitoral"].search(info.get("title") or "") and date.today() <= date(2026, 10, 25):
            av("grave", "Tema eleitoral/partidário no título: até o 2º turno (25/10), só aula e análise.")
    elif pol_titulo or len(pol) >= 3:
        av("grave", f"Fala de política ({', '.join((pol_titulo or pol)[:4])}): pode ser política partidária fora do canal de Política.")
    if RX["morte"].search(info.get("title") or "") and not RX["crime_nomeado"].search(info.get("title") or ""):
        av("atencao", "Fala da morte de uma pessoa real: cuidado com sensacionalismo e com a família.")
    if RX["crime_nomeado"].search(info.get("title") or ""):
        av("grave", "Caso criminal com pessoa citada como suspeita/acusada: risco de difamação (como o da Mãe Michelly).")
    if RX["evento"].search(texto) or (info.get("live_status") == "was_live" and nicho == "ciencia"
                                      and re.search(r"lan[çc]amento|ao vivo", info.get("title") or "", re.I)):
        av("grave", "Transmissão de evento com imagem de terceiros (NASA, jogo, TV): risco de Content ID.")
    # vendas: no título/capítulos qualquer termo; na descrição só frase forte (rodapé de patrocínio tem "curso/mentoria")
    titulo_caps = " ".join([info.get("title") or "", " ".join(c.get("title", "") for c in (info.get("chapters") or []))])
    if RX["vendas"].search(titulo_caps) or re.search(r"(inscri[çc][õo]es abertas|garanta sua vaga|vagas abertas|aula gratuita|"
                                                       r"lan[çc]amento (do|da) (curso|mentoria|imers[ãa]o))",
                                                       (info.get("description") or "")[:1500], re.I):
        av("atencao", "Pode ser live de vendas ou lançamento (curso, mentoria, inscrições).")
    titulo_cap = " ".join([info.get("title") or "", " ".join(c.get("title", "") for c in (info.get("chapters") or []))])
    if portugues(texto) is False:
        av("grave", "Não é em português.")
        bloqueado = True
    if RX["chat"].search(titulo_cap) or (info.get("live_status") == "was_live" and re.search(r"\blive\b|ao vivo", info.get("title") or "", re.I)):
        av("atencao", "Live: pode ter muito tempo lendo chat ou falando com a audiência.")
    parado = imagem_parada(info)
    if parado is not None and parado >= 0.8:
        av("grave", f"Imagem parada ({int(parado * 100)}% dos quadros iguais): podcast só áudio. Não serve para Shorts.")
        bloqueado = True
    if fonte["status"] in (None, "NÃO AUDITADO"):
        av("atencao", "Fonte ainda não auditada (permissão de cortes).")
    rel = views / mediana_views if mediana_views and mediana_views >= 100 else None   # sem base pra comparar
    return {"canal": canal, "fonte": fonte["nome"], "fonte_url": fonte["url"], "fonte_tipo": fonte["tipo"],
            "fonte_status": fonte["status"], "id": info["id"], "titulo": info.get("title"),
            "url": f"https://youtu.be/{info['id']}", "thumb": f"https://i.ytimg.com/vi/{info['id']}/mqdefault.jpg",
            "duracao_min": round((info.get("duration") or 0) / 60), "views": views, "data": up, "dias": dias,
            "vpd": round(views / dias), "rel": round(rel, 2) if rel is not None else None, "parado": parado, "avisos": avisos,
            "bloqueado": bloqueado, "capitulos": len(info.get("chapters") or [])}


def nota(itens):
    """0–100: metade desempenho relativo (vs. média do canal), metade alcance (visualizações/dia no nicho)."""
    for canal in {i["canal"] for i in itens}:
        grupo = [i for i in itens if i["canal"] == canal]
        vpds = sorted(i["vpd"] for i in grupo)
        for i in grupo:
            pct = vpds.index(i["vpd"]) / max(1, len(vpds) - 1)
            rel = i["rel"] if i["rel"] is not None else 1.0
            i["nota"] = round(50 * min(1.0, rel / 2.5) + 50 * pct)
            if any(a["nivel"] == "grave" for a in i["avisos"]):
                i["nota"] = min(i["nota"], 15)


def marcar_fora_do_idioma(itens):
    """Candidato cujos episódios não são em português sai das próximas buscas (nao_usar no canal.json)."""
    por_fonte = {}
    for i in itens:
        por_fonte.setdefault((i["canal"], i["fonte_url"]), []).append(any(a["texto"] == "Não é em português." for a in i["avisos"]))
    for (canal, url), marcas in por_fonte.items():
        if not all(marcas):
            continue
        p = RAIZ / canal / "canal.json"
        cfg = json.loads(p.read_text(encoding="utf-8"))
        mudou = False
        for c in cfg.get("candidatos", []):
            if (c.get("canal_url") or "").rstrip("/") == url and not c.get("nao_usar"):
                c["nao_usar"] = "Não é em português (radar)."
                mudou = True
        if mudou:
            p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    inicio = datetime.now().strftime("%Y-%m-%d %H:%M")
    status(rodando=True, inicio=inicio, etapa="listando", feitos=0, total=0, erro=None)
    descartados = json.loads((PESQ / "descartados.json").read_text(encoding="utf-8")) if (PESQ / "descartados.json").exists() else []
    nao = {d["id"] for d in descartados if not d.get("retentar")}
    retentar = {d["id"]: d for d in descartados if d.get("retentar")}
    ja = {p.parent.name for p in RAIZ.glob("canal-*/episodios/*/info.json")}
    tarefas = []
    for canal_dir in sorted(RAIZ.glob("canal-tema*")):
        if SO_CANAL and canal_dir.name != SO_CANAL:
            continue
        cfg = json.loads((canal_dir / "canal.json").read_text(encoding="utf-8"))
        nicho = canal_dir.name.split("-", 2)[2]
        tarefas += [(canal_dir.name, nicho, f) for f in fontes_do_canal(cfg)]
    status(etapa="listando episódios das fontes", total=len(tarefas))
    listas = {}
    with ThreadPoolExecutor(3) as ex:
        for k, (t, ents) in enumerate(zip(tarefas, ex.map(lambda t: listar(t[2]), tarefas))):
            listas[(t[0], t[2]["url"])] = (t, ents)
            status(feitos=k + 1)
    # escolhe por fonte: episódios longos, novos pra nós; os 2 de melhor desempenho relativo
    abrir = []
    for (t, ents) in listas.values():
        canal, nicho, fonte = t
        longos = [e for e in ents if MIN_S <= (e.get("duration") or 0) <= MAX_S
                  and e.get("live_status") not in ("is_live", "is_upcoming") and e.get("availability") in (None, "public")]
        vs = [e["view_count"] for e in longos if e.get("view_count")]
        mediana = statistics.median(vs) if len(vs) >= 3 else 0
        novos = [e for e in longos if e["id"] not in ja and e["id"] not in nao]
        novos.sort(key=lambda e: (e.get("view_count") or 0), reverse=True)
        quantos = 6 if fonte.get("status") == "LIBERADO" else 2    # fonte liberada: mais opções pro piloto automático
        abrir += [(canal, nicho, fonte, e, mediana) for e in novos[:quantos]]
    for rid, d in retentar.items():
        if rid not in ja and (not SO_CANAL or d["canal"] == SO_CANAL):
            f = {"nome": d.get("fonte"), "url": d.get("fonte_url"), "status": None, "tipo": "retentar"}
            abrir.append((d["canal"], d["canal"].split("-", 2)[2], f, {"id": rid}, 0))
    status(etapa="avaliando episódios", feitos=0, total=len(abrir))
    itens, erros, msgs = [], 0, []

    def um(a):
        try:
            return avaliar(*a)
        except Exception as ex:
            msgs.append(f"{a[3].get('id')}: {str(ex).strip().splitlines()[-1][:200]}")
            return None
    with ThreadPoolExecutor(2) as ex:
        for k, r in enumerate(ex.map(um, abrir)):
            if r:
                if r["id"] in retentar:
                    r["avisos"].append({"nivel": "atencao", "texto": "Download tinha falhado antes (HTTP 403): tentar de novo."})
                itens.append(r)
            else:
                erros += 1
            status(feitos=k + 1)
    nota(itens)
    marcar_fora_do_idioma(itens)
    itens.sort(key=lambda i: (i["canal"], -i["nota"]))
    anterior = json.loads(SAIDA.read_text(encoding="utf-8")) if SAIDA.exists() else {}
    if SO_CANAL and anterior.get("itens"):
        itens = [i for i in anterior["itens"] if i["canal"] != SO_CANAL] + itens
    SAIDA.write_text(json.dumps({"gerado_em": datetime.now().strftime("%Y-%m-%d %H:%M"), "itens": itens},
                                ensure_ascii=False, indent=1), encoding="utf-8")
    status(rodando=False, fim=datetime.now().strftime("%Y-%m-%d %H:%M"), etapa="pronto",
           resumo=f"{len(itens)} episódios avaliados de {len(tarefas)} canais" + (f" ({erros} falharam)" if erros else ""))
    print(f"radar: {len(itens)} itens, {erros} erros → {SAIDA}", flush=True)
    for m in msgs[:8]:
        print("  erro", m, flush=True)


def fontes_semanal():
    """1 vez por semana: procura podcasts que liberam cortes publicamente (fontes_liberadas.py)."""
    arq = PESQ / "fontes_novas.json"
    if arq.exists() and time.time() - arq.stat().st_mtime < 6 * 86400 and "--fontes" not in sys.argv:
        return
    status(etapa="procurando fontes que liberam cortes")
    import fontes_liberadas
    fontes_liberadas.main()


if __name__ == "__main__":
    try:
        main()
        if not SO_CANAL:
            fontes_semanal()
    except Exception:
        status(rodando=False, etapa="erro", erro=traceback.format_exc()[-800:])
        raise
