"""Renderização dos cortes: bruto (trechos + pausas apertadas), Short 9:16 com enquadramento
automático por rosto/plano, horizontal 16:9, legendas animadas (ASS) e crédito."""
import os, re, subprocess
from pathlib import Path
import numpy as np
import cv2
from util import (log, run, para_seg, info_video, args_encoder_video, FONTES_DIR, MODELOS_DIR, duracao)

# ----------------------------------------------------------------------------- trechos

def palavras_da_transcricao(trans):
    """Lista plana de palavras. Sinal solto ("%", "-", "?") gruda na palavra anterior ("90 %" -> "90%")."""
    out = []
    for s in trans["segmentos"]:
        for w in s["words"]:
            # gruda no anterior: sinal solto ("%", "$"), "-up", e fração de número (".750", ",5")
            if out and (not re.sub(r"[^\w]", "", w["w"]) or w["w"].startswith("-")
                        or re.match(r"^[.,]\d", w["w"]) and re.search(r"\d$", out[-1]["w"])):
                out[-1] = {**out[-1], "w": out[-1]["w"] + w["w"], "e": max(out[-1]["e"], w["e"])}
            else:
                out.append(w)
    return out


def _norm(t):
    return re.sub(r"[^\w]", "", t.lower())


def aplicar_correcoes(palavras, correcoes):
    """Corrige erros de transcrição (nomes, termos). correcoes = {"Quarto Milionários": "Cortes Bilionários"}.
    Funciona com várias palavras; preserva a pontuação final da última palavra."""
    if not correcoes:
        return palavras
    ws = [dict(w) for w in palavras]
    for errado, certo in correcoes.items():
        alvo = [_norm(t) for t in errado.split()]
        novo = certo.split()
        n = len(alvo)
        i = 0
        while i <= len(ws) - n:
            if [_norm(w["w"]) for w in ws[i:i + n]] == alvo:
                pont = re.search(r"[.,?!…]+$", ws[i + n - 1]["w"])
                bloco = ws[i:i + n]
                if len(novo) == n:
                    for w, t in zip(bloco, novo):
                        w["w"] = t
                else:
                    bloco[0]["w"] = " ".join(novo)
                    bloco[0]["e"] = bloco[-1]["e"]
                    del ws[i + 1:i + n]
                if pont:
                    ws[i + (len(novo) - 1 if len(novo) == n else 0)]["w"] += pont.group(0)
                i += 1
            else:
                i += 1
    return ws


def achar_frase(palavras, frase, perto, janela=150):
    """Acha a frase mais perto do tempo 'perto' (±janela s). Compara o texto emendado sem espaço/pontuação,
    então funciona mesmo se a transcrição quebrou ("check" "-up") ou juntou palavras de outro jeito.
    Devolve (índice da 1ª palavra, índice da última)."""
    alvo = "".join(_norm(t) for t in frase.split())
    idx = [i for i, w in enumerate(palavras) if _norm(w["w"]) and abs(w["s"] - perto) <= janela + 60]
    norm = [_norm(palavras[i]["w"]) for i in idx]
    melhor = None
    for k in range(len(idx)):
        i = idx[k]
        if abs(palavras[i]["s"] - perto) > janela or not alvo.startswith(norm[k]):
            continue
        acc, j = "", k
        while j < len(idx) and len(acc) < len(alvo):
            acc += norm[j]
            j += 1
        if acc == alvo:
            d = abs(palavras[i]["s"] - perto)
            if melhor is None or d < melhor[0]:
                melhor = (d, i, idx[j - 1])
    if melhor is None:
        perto_txt = " ".join(x["w"] for x in palavras if abs(x["s"] - perto) < 20)
        raise ValueError(f"Frase não achada perto de {perto:.0f}s: '{frase}'. Texto da região: {perto_txt[:400]}")
    return melhor[1], melhor[2]


def resolver_ancoras(palavras, corte):
    """Converte 'de'/'ate' (texto) em inicio/fim exatos, e 'remover_texto' em 'remover' (tempos)."""
    c = dict(corte)
    if c.get("de"):
        i, _ = achar_frase(palavras, c["de"], para_seg(c["inicio"]))
        c["inicio"] = palavras[i]["s"]
    if c.get("ate"):
        _, j = achar_frase(palavras, c["ate"], para_seg(c["fim"]))
        c["fim"] = palavras[j]["s"] + 0.01
    rem = list(c.get("remover", []))
    for a, b, *perto in c.get("remover_texto", []):
        ref = para_seg(perto[0]) if perto else (para_seg(c["inicio"]) + para_seg(c["fim"])) / 2
        i, _ = achar_frase(palavras, a, ref, janela=max(150, para_seg(c["fim"]) - para_seg(c["inicio"])))
        _, j = achar_frase(palavras, b, palavras[i]["s"] + 1, janela=max(300, para_seg(c["fim"]) - para_seg(c["inicio"])))
        rem.append((palavras[i]["s"] - 0.03, palavras[j]["e"] + 0.03))
    c["remover"] = rem
    return c


def planejar_trechos(palavras, corte, cfg_fmt):
    """Devolve (trechos_mantidos_no_original, palavras_remapeadas_pro_tempo_do_corte)."""
    corte = resolver_ancoras(palavras, corte)
    ini, fim = para_seg(corte["inicio"]), para_seg(corte["fim"])
    # regra: 'inicio' = tempo da 1ª palavra (como mostra `cortes palavras`); entra toda palavra que COMEÇA antes do 'fim'
    ws = [w for w in palavras if ini - 0.06 <= w["s"] < fim]
    if not ws:
        raise ValueError(f"Corte {corte['id']}: nenhuma palavra entre {corte['inicio']} e {corte['fim']}")
    remover = [(para_seg(a), para_seg(b)) for a, b in corte.get("remover", [])]
    ws = [w for w in ws if not any(a <= (w["s"] + w["e"]) / 2 <= b for a, b in remover)]
    a0 = ws[0]["s"] - 0.12
    b0 = ws[-1]["e"] + 0.30
    cortar = list(remover)
    if cfg_fmt.get("apertar_pausas", True):
        pmax, folga = cfg_fmt.get("pausa_max", 0.45), cfg_fmt.get("pausa_folga", 0.14)
        for w1, w2 in zip(ws, ws[1:]):
            if w2["s"] - w1["e"] > pmax:
                cortar.append((w1["e"] + folga, w2["s"] - folga * 0.7))
    trechos = [(a0, b0)]
    for a, b in sorted(cortar):
        novo = []
        for x, y in trechos:
            if b <= x or a >= y:
                novo.append((x, y))
                continue
            if a > x: novo.append((x, a))
            if b < y: novo.append((b, y))
        trechos = novo
    trechos = [(x, y) for x, y in trechos if y - x >= 0.08]

    def mapear(t):
        acc = 0.0
        for x, y in trechos:
            if t < x:
                return acc
            if t <= y:
                return acc + (t - x)
            acc += y - x
        return acc

    novas = [{**w, "s": round(mapear(w["s"]), 3), "e": round(mapear(w["e"]), 3)} for w in ws]
    return trechos, novas


def montar_bruto(video, trechos, saida):
    """Concatena os trechos com re-encode (corte preciso no quadro)."""
    ss = max(0.0, trechos[0][0] - 2.0)
    fim = trechos[-1][1] + 1.0
    partes, rot = [], []
    for i, (a, b) in enumerate(trechos):
        a, b = a - ss, b - ss
        partes.append(f"[0:v]trim={a:.3f}:{b:.3f},setpts=PTS-STARTPTS[v{i}];"
                      f"[0:a]atrim={a:.3f}:{b:.3f},asetpts=PTS-STARTPTS,"
                      f"afade=t=in:d=0.012,afade=t=out:st={max(0, b - a - 0.012):.3f}:d=0.012[a{i}];")
        rot.append(f"[v{i}][a{i}]")
    grafo = "".join(partes) + "".join(rot) + f"concat=n={len(trechos)}:v=1:a=1[v][a]"
    script = Path(saida).with_suffix(".grafo.txt")
    script.write_text(grafo, encoding="utf-8")
    run(["ffmpeg", "-y", "-v", "error", "-ss", f"{ss:.3f}", "-to", f"{fim:.3f}", "-i", str(video),
         "-/filter_complex", str(script), "-map", "[v]", "-map", "[a]",
         *args_encoder_video("alta"), "-c:a", "pcm_s16le", str(saida)])
    script.unlink(missing_ok=True)
    return sum(b - a for a, b in trechos)

# ----------------------------------------------------------------------------- análise de enquadramento

def _ler_frames(video, w, h, vf, pix="bgr24"):
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(video), "-vf", vf, "-f", "rawvideo",
                          "-pix_fmt", pix, "-"], stdout=subprocess.PIPE)
    tam = w * h * (3 if pix == "bgr24" else 1)
    while True:
        buf = p.stdout.read(tam)
        if len(buf) < tam:
            break
        yield np.frombuffer(buf, np.uint8).reshape(h, w, -1 if pix == "bgr24" else 1)
    p.wait()


def detectar_planos(video, fps, limiar=22.0):
    """Trocas de câmera com precisão de quadro: diferença média entre miniaturas 64x36."""
    cortes, ant = [0.0], None
    for i, f in enumerate(_ler_frames(video, 64, 36, "scale=64:36", "gray")):
        f = f.astype(np.int16)
        if ant is not None and np.abs(f - ant).mean() > limiar:
            cortes.append(i / fps)
        ant = f
    return cortes


def detectar_rostos(video, amostras_por_seg=5, largura=640):
    W, H, _ = info_video(video)
    h = int(round(largura * H / W / 2) * 2)
    det = cv2.FaceDetectorYN.create(str(MODELOS_DIR / "face_detection_yunet_2023mar.onnx"), "",
                                    (largura, h), 0.75, 0.3, 5000)
    res, ant = [], None
    for i, f in enumerate(_ler_frames(video, largura, h, f"fps={amostras_por_seg},scale={largura}:{h}")):
        _, faces = det.detect(np.ascontiguousarray(f))
        cinza = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY).astype(np.int16)
        lst = []
        if faces is not None:
            for x, y, fw, fh, *_r, score in faces:
                # movimento da metade de baixo do rosto (boca/queixo) vs. a amostra anterior: quem fala mexe mais
                x0, x1 = int(max(0, x + fw * 0.2)), int(min(largura, x + fw * 0.8))
                y0, y1 = int(max(0, y + fh * 0.55)), int(min(h, y + fh * 1.0))
                mov = float(np.abs(cinza[y0:y1, x0:x1] - ant[y0:y1, x0:x1]).mean()) if ant is not None and x1 > x0 and y1 > y0 else 0.0
                lst.append({"cx": (x + fw / 2) / largura, "cy": (y + fh / 2) / h,
                            "w": fw / largura, "h": fh / h, "score": float(score), "mov": mov})
        res.append({"t": i / amostras_por_seg, "faces": lst, "nitidez": float(cv2.Laplacian(
            cinza.astype(np.uint8), cv2.CV_64F).var())})
        ant = cinza
    return res


def _agrupar_pessoas(faces, n_amostras, gap=0.12, suporte=0.25):
    pts = sorted((f["cx"], f["cy"], f["w"]) for f in faces if f["w"] >= 0.035)
    grupos, atual = [], []
    for p in pts:
        if atual and p[0] - atual[-1][0] > gap:
            grupos.append(atual); atual = []
        atual.append(p)
    if atual:
        grupos.append(atual)
    pessoas = []
    for g in grupos:
        if len(g) >= max(2, suporte * n_amostras):
            arr = np.array(g)
            pessoas.append({"cx": float(np.median(arr[:, 0])), "cy": float(np.median(arr[:, 1])),
                            "w": float(np.median(arr[:, 2])), "n": len(g)})
    return pessoas


def _falante_ativo(p, am, pessoas, largura_crop, janela=2.0):
    """Plano de grupo: divide em janelas de ~2 s e escolhe, em cada uma, a pessoa com mais movimento na boca.
    Devolve sub-planos 'unico' centrados em quem fala (ou None se não der pra saber)."""
    if len(pessoas) < 2:
        return None
    sub, t, escolha_ant = [], p["t0"], None
    while t < p["t1"] - 0.01:
        t2 = min(p["t1"], t + janela)
        if p["t1"] - t2 < janela * 0.5:
            t2 = p["t1"]
        notas = [0.0] * len(pessoas)
        for a in am:
            if t <= a["t"] < t2:
                for f in a["faces"]:
                    k = min(range(len(pessoas)), key=lambda i: abs(pessoas[i]["cx"] - f["cx"]))
                    if abs(pessoas[k]["cx"] - f["cx"]) < 0.08:
                        notas[k] += f.get("mov", 0)
        ordem = sorted(range(len(pessoas)), key=lambda i: -notas[i])
        if notas[ordem[0]] > 3 and notas[ordem[0]] >= 1.35 * max(notas[ordem[1]], 0.01):
            escolha = ordem[0]
        else:
            escolha = escolha_ant
        sub.append((t, t2, escolha))
        escolha_ant = escolha
        t = t2
    if all(e is None for _, _, e in sub):
        return None
    # janela sem decisão herda a próxima decidida (começo do plano)
    prox = next(e for _, _, e in sub if e is not None)
    out = []
    for a, b, e in sub:
        e = prox if e is None else e
        prox = e
        q = {"t0": a, "t1": b, "modo": "unico", "cx": pessoas[e]["cx"], "cy": pessoas[e]["cy"], "fw": pessoas[e]["w"],
             "falante": True}
        if out and out[-1]["cx"] == q["cx"]:
            out[-1]["t1"] = b
        else:
            out.append(q)
    return out


def planejar_enquadramento(video, opcoes=None):
    opcoes = opcoes or {}
    W, H, fps = info_video(video)
    dur = duracao(video)
    cortes = detectar_planos(video, fps) + [dur]
    amostras = detectar_rostos(video)
    largura_crop = (H * 9 / 16) / W
    planos = []
    for t0, t1 in zip(cortes, cortes[1:]):
        am = [a for a in amostras if t0 <= a["t"] < t1]
        faces = [f for a in am for f in a["faces"]]
        pessoas = _agrupar_pessoas(faces, max(1, len(am)))
        jan = opcoes.get("janela")
        if jan and faces:
            # trecho de "slide": o vídeo do original virou uma janelinha (rosto pequeno dentro dela) → usa só a janela
            dentro = [f for f in faces if jan[0] <= f["cx"] <= jan[2] and jan[1] <= f["cy"] <= jan[3]]
            if len(dentro) >= 0.7 * len(faces) and np.median([f["w"] for f in dentro]) < 0.14:
                planos.append({"t0": t0, "t1": t1, "modo": "janela", "box": list(jan)})
                continue
        if pessoas:   # pessoa ao fundo (rosto bem menor que o maior do plano) não entra na tela dividida/close
            maior = max(x["w"] for x in pessoas)
            pessoas = [x for x in pessoas if x["w"] >= 0.6 * maior]
        p = {"t0": t0, "t1": t1}
        if len(am) < 2 and planos:
            p.update({k: v for k, v in planos[-1].items() if k not in ("t0", "t1")})
        elif not pessoas:
            p["modo"] = "ajustar"
        elif len(pessoas) == 1:
            p.update(modo="unico", cx=pessoas[0]["cx"], cy=pessoas[0]["cy"], fw=pessoas[0]["w"])
        elif len(pessoas) >= 3 and sorted(x["n"] for x in pessoas)[-3] >= 0.5 * sorted(x["n"] for x in pessoas)[-2]:
            # plano de grupo (3+ pessoas presentes o plano todo): mostra o quadro inteiro
            p["modo"] = "ajustar"
        else:
            pessoas.sort(key=lambda x: -x["n"])
            dois = sorted(pessoas[:2], key=lambda x: x["cx"])
            if dois[1]["cx"] - dois[0]["cx"] + dois[1]["w"] < largura_crop * 0.92:
                p.update(modo="unico", cx=(dois[0]["cx"] + dois[1]["cx"]) / 2, cy=(dois[0]["cy"] + dois[1]["cy"]) / 2)
            else:
                p.update(modo="dividido", cx=dois[0]["cx"], cy=dois[0]["cy"], cx2=dois[1]["cx"], cy2=dois[1]["cy"],
                         fw=dois[0]["w"], fw2=dois[1]["w"])
        if opcoes.get("falante_ativo") and p.get("modo") == "ajustar" and len(pessoas) >= 2:
            sub = _falante_ativo(p, am, pessoas, largura_crop)
            if sub:
                planos.extend(sub)
                continue
        if opcoes.get("falante_ativo") and p.get("modo") == "dividido":
            # tela dividida só faz sentido se as duas pessoas falam; se só uma fala o plano todo
            # (a outra é plateia/ouvinte), close em quem fala
            dois = [x for x in pessoas if x["cx"] in (p["cx"], p["cx2"])]
            mov = [sum(f.get("mov", 0) for a in am for f in a["faces"] if abs(f["cx"] - x["cx"]) < 0.08) for x in dois]
            if len(mov) == 2 and max(mov) > 3 and max(mov) >= 2.0 * max(min(mov), 0.01):
                fala = dois[mov.index(max(mov))]
                p = {"t0": p["t0"], "t1": p["t1"], "modo": "unico", "cx": fala["cx"], "cy": fala["cy"], "fw": fala["w"],
                     "falante": True}
        planos.append(p)
    return {"W": W, "H": H, "fps": fps, "planos": planos, "amostras": amostras}

# ----------------------------------------------------------------------------- composição 9:16

OW, OH = 1080, 1920
ROSTO_ALVO = 0.22    # largura do rosto no Short (fração da largura); abaixo disso o close aproxima


def _recorte(frame, cx, cy, cw, ch, pos_y=0.42):
    H, W = frame.shape[:2]
    x0 = int(min(max(cx * W - cw / 2, 0), W - cw))
    y0 = int(min(max(cy * H - ch * pos_y, 0), H - ch))
    return frame[y0:y0 + int(ch), x0:x0 + int(cw)]


def desfocar_caixas(frame, caixas):
    """Desfoca as sobreposições do original (logo, QR, anúncio) no quadro antes do recorte."""
    if not caixas:
        return frame
    H, W = frame.shape[:2]
    frame = frame.copy()
    for x0, y0, x1, y1 in caixas:
        a, b, c, d = int(x0 * W), int(y0 * H), int(x1 * W), int(y1 * H)
        if c - a > 4 and d - b > 4:
            reg = frame[b:d, a:c]
            peq = cv2.resize(reg, (max(1, (c - a) // 16), max(1, (d - b) // 16)), interpolation=cv2.INTER_AREA)
            frame[b:d, a:c] = cv2.GaussianBlur(cv2.resize(peq, (c - a, d - b)), (0, 0), 3)
    return frame


def compor(frame, p, zoom=1.0, teto=1.0):
    """teto: até onde (0–1 da altura) o recorte pode descer — usado pra deixar uma faixa de anúncio embaixo de fora."""
    H, W = frame.shape[:2]
    modo = p.get("modo", "ajustar")
    if modo == "janela":
        x0, y0, x1, y1 = p["box"]
        sub = frame[int(y0 * H):int(y1 * H), int(x0 * W):int(x1 * W)]
        return compor(sub, {"modo": "ajustar"})
    if modo == "unico":
        # rosto alto no quadro (close/pessoa em pé): aproxima um pouco pra descer o rosto pra ~32%
        # da tela, abaixo do gancho. Rosto já baixo: usa a altura inteira (sem perda de nitidez).
        cy = p.get("cy", 0.5)
        ch = (H if cy >= 0.30 else max(cy * H / 0.32, H * 0.70))
        if p.get("fw"):
            ch = min(ch, max(p["fw"] * W / ROSTO_ALVO * 16 / 9, H * 0.55))
        ch /= zoom
        if teto < 1.0:
            ch = min(ch, teto * H)
            cw = ch * 9 / 16
            x0 = int(min(max(p["cx"] * W - cw / 2, 0), W - cw))
            y0 = int(max(0, min(cy * H - ch * 0.32, teto * H - ch)))
            return cv2.resize(frame[y0:y0 + int(ch), x0:x0 + int(cw)], (OW, OH), interpolation=cv2.INTER_CUBIC)
        cw = ch * 9 / 16
        return cv2.resize(_recorte(frame, p["cx"], cy, cw, ch, pos_y=0.32), (OW, OH), interpolation=cv2.INTER_CUBIC)
    if modo == "dividido":
        metades = []
        for cx, cy, fw in ((p["cx"], p["cy"], p.get("fw")), (p["cx2"], p["cy2"], p.get("fw2"))):
            # rosto perto do topo do quadro original: aproxima (até 2,4x) pra o rosto descer
            # pra ~40% da metade e não ficar atrás do gancho
            ch = min(max(cy * H / 0.40, H * 0.42), H * 0.62)
            if fw:   # rosto pequeno na metade → aproxima mais (sem passar de 3,3x)
                ch = min(ch, max(fw * W / ROSTO_ALVO * (OH / 2) / OW, H * 0.30))
            ch /= zoom
            cw = ch * OW / (OH / 2)
            metades.append(cv2.resize(_recorte(frame, cx, cy, cw, ch, pos_y=0.40), (OW, OH // 2),
                                      interpolation=cv2.INTER_CUBIC))
        return np.vstack(metades)
    # ajustar: vídeo inteiro no meio, fundo = o próprio vídeo ampliado e desfocado
    fundo = cv2.resize(frame, (int(W * OH / H), OH))
    x = (fundo.shape[1] - OW) // 2
    fundo = fundo[:, x:x + OW]
    fundo = cv2.GaussianBlur(cv2.resize(fundo, (OW // 8, OH // 8)), (0, 0), 6)
    fundo = (cv2.resize(fundo, (OW, OH)) * 0.45).astype(np.uint8)
    esc = min(OW / W, OH / H)            # encaixa inteiro (janela alta não estoura a tela)
    fw, fh = int(W * esc) // 2 * 2, int(H * esc) // 2 * 2
    frente = cv2.resize(frame, (fw, fh), interpolation=cv2.INTER_AREA if esc < 1 else cv2.INTER_CUBIC)
    y, x = (OH - fh) // 2, (OW - fw) // 2
    fundo[y:y + fh, x:x + fw] = frente
    return fundo


def plano_em(planos, t):
    for p in planos:
        if p["t0"] <= t < p["t1"]:
            return p
    return planos[-1]

# ----------------------------------------------------------------------------- legendas ASS

def _cor_ass(hexcor, alpha="00"):
    h = hexcor.lstrip("#")
    return f"&H{alpha}{h[4:6]}{h[2:4]}{h[0:2]}".upper()


def _esc(t):
    return t.replace("\\", "").replace("{", "(").replace("}", ")")


def _t_ass(s):
    s = max(0, s)
    h, r = divmod(s, 3600); m, r = divmod(r, 60)
    return f"{int(h)}:{int(m):02d}:{r:05.2f}"


def blocos_legenda(palavras, max_palavras=3, max_chars=16, gap=0.35):
    blocos, atual = [], []
    for i, w in enumerate(palavras):
        if atual:
            texto = " ".join(x["w"] for x in atual + [w])
            if (len(atual) >= max_palavras or len(texto) > max_chars or w["s"] - atual[-1]["e"] > gap
                    or atual[-1]["w"].endswith((".", "?", "!", ","))):
                blocos.append(atual); atual = []
        atual.append(w)
    if atual:
        blocos.append(atual)
    return blocos


PALAVROES = re.compile(r"^(caralho|porra|foda|foda-se|fodeu|puta|puto|putaria|merda|cacete|buceta|arrombado|bosta)$", re.I)


def _limpar(w, maiusc, censurar=False):
    w = w.strip().strip(",;:").rstrip(".")
    w = w.replace("...", "").replace("…", "")
    if censurar:
        base = re.sub(r"[^\w-]", "", w)
        if PALAVROES.match(base):
            w = w.replace(base, base[0] + "*" * (len(base) - 1))
    return w.upper() if maiusc else w


# animações de entrada (tags ASS no começo do bloco). {x},{y} = posição final da legenda.
ANIM_LEGENDA = {
    "pop":      "{{\\pos({x},{y})\\t(0,80,\\fscx104\\fscy104)\\t(80,160,\\fscx100\\fscy100)}}",
    "quique":   "{{\\pos({x},{y})\\fscx60\\fscy60\\t(0,120,\\fscx114\\fscy114)\\t(120,200,\\fscx96\\fscy96)\\t(200,260,\\fscx100\\fscy100)}}",
    "subir":    "{{\\move({x},{y2},{x},{y},0,150)\\alpha&HFF&\\t(0,150,\\alpha&H00&)}}",
    "deslizar": "{{\\move({x0},{y},{x},{y},0,160)\\alpha&HFF&\\t(0,160,\\alpha&H00&)}}",
    "desfoque": "{{\\pos({x},{y})\\blur14\\alpha&H90&\\t(0,200,\\blur0\\alpha&H00&)}}",
    "girar":    "{{\\pos({x},{y})\\frz-9\\fscx80\\fscy80\\t(0,170,\\frz0\\fscx100\\fscy100)}}",
    "brilho":   "{{\\pos({x},{y})\\3c{cor}\\bord16\\t(0,240,\\3c&H000000&\\bord7)}}",
    "fade":     "{{\\pos({x},{y})\\fad(150,0)}}",
    "palavra":  "{{\\pos({x},{y})}}",   # palavra por palavra: as próximas ficam invisíveis
}
ANIM_GANCHO = {
    "pop":     "{{\\fscx55\\fscy55\\t(0,170,\\fscx118\\fscy118)\\t(170,300,\\fscx100\\fscy100)}}",
    "cair":    "{{\\an8\\move({x},{y0},{x},{y},0,240)\\t(0,240,\\fscy100)}}",
    "revelar": "{{\\clip(0,0,0,{h})\\t(0,380,\\clip(0,0,{w},{h}))}}",
    "fade":    "{{\\fad(250,0)}}",
    "digitar": "",   # letra por letra (karaokê com a cor "antes" transparente)
}


def gerar_ass(palavras, saida, est, formato, gancho=None, credito=None, planos=None, duracao_total=None, nome=None):
    vertical = formato == "short"
    PX, PY = (OW, OH) if vertical else (1920, 1080)
    cor = _cor_ass(est.get("cor_destaque", "#FFD400"))
    fonte = est.get("fonte", "Anton")
    tam = est.get("tamanho_legenda_short", 96) if vertical else est.get("tamanho_legenda_horizontal", 64)
    maiusc = est.get("maiusculas", True) if vertical else False
    linhas = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {PX}", f"PlayResY: {PY}", "WrapStyle: 0",
        "ScaledBorderAndShadow: yes", "", "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
        "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Leg,{fonte},{tam},&H00FFFFFF,&H00FFFFFF,&H00000000,&H96000000,0,0,0,0,100,100,1,0,1,{7 if vertical else 4},{3 if vertical else 2},5,60,60,0,1",
        f"Style: Gancho,{fonte},{est.get('tamanho_gancho', 66)},&H00111111,&H00111111,{cor},{cor},0,0,0,0,100,100,1,0,3,22,0,8,80,80,{est.get('gancho_margem_topo', 150)},1",
        f"Style: Credito,{fonte},{40 if vertical else 30},&H40FFFFFF,&H40FFFFFF,&H90000000,&H00000000,0,0,0,0,100,100,1,0,1,3,0,2,40,40,{60 if vertical else 30},1",
        f"Style: GanchoGrande,{fonte},{est.get('tamanho_gancho_grande', 104)},&H00111111,&H00111111,{cor},{cor},0,0,0,0,100,100,1,0,3,28,0,5,70,70,0,1",
        f"Style: Nome,{fonte},{est.get('tamanho_nome', 54)},&H00FFFFFF,&H00FFFFFF,&H50000000,&H50000000,0,0,0,0,100,100,2,0,3,12,0,5,80,80,0,1",
        f"Style: Marca,{fonte},{est.get('tamanho_marca', 44)},{cor},{cor},&H64000000,&H00000000,0,0,0,0,100,100,3,0,1,3,0,8,40,40,0,1",
        f"Style: GanchoK,{fonte},{est.get('tamanho_gancho', 66)},&H00111111,&HFF111111,{cor},{cor},0,0,0,0,100,100,1,0,3,22,0,8,80,80,{est.get('gancho_margem_topo', 150)},1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    fim_total = duracao_total or (palavras[-1]["e"] + 0.5 if palavras else 1)
    if gancho and vertical:
        g_fim = est.get("gancho_segundos") or fim_total
        some = "{\\fad(0,300)}" if est.get("encerramento") and g_fim >= fim_total - 0.05 else ""
        anim = est.get("animacao_gancho") or ("pop" if est.get("gancho_animado") else None)
        topo = est.get("gancho_margem_topo", 150)
        txt = _esc(gancho.upper())
        if anim == "digitar":
            passo = max(2, min(6, int(60 / max(1, len(txt)))))   # cs por letra: ~0,6 s pra frase toda
            txt = "".join(f"{{\\k{passo}}}{ch}" for ch in txt)
            linhas.append(f"Dialogue: 2,{_t_ass(0)},{_t_ass(g_fim)},GanchoK,,0,0,0,,{some}{txt}")
        else:
            tag = ANIM_GANCHO.get(anim, "").format(x=OW // 2, y=topo, y0=topo - 160, w=OW, h=OH) if anim else ""
            linhas.append(f"Dialogue: 2,{_t_ass(0)},{_t_ass(g_fim)},Gancho,,0,0,0,,{tag}{some}{txt}")
    if vertical and est.get("marca_rotulo"):
        # assinatura da marca logo acima do gancho, na cor do tema ("GATO PRETO · NEGÓCIOS")
        topo = est.get("gancho_margem_topo", 150)
        some_m = "\\fad(300,300)" if est.get("encerramento") else "\\fad(300,0)"
        linhas.append(f"Dialogue: 2,{_t_ass(0)},{_t_ass(fim_total)},Marca,,0,0,0,,"
                      f"{{\\an8\\pos({OW // 2},{topo - 82}){some_m}}}{_esc(est['marca_rotulo'])}")
    if nome and vertical and est.get("nome_convidado"):
        # logo abaixo da legenda (acompanha a legenda no meio quando a tela está dividida)
        p_nome = plano_em(planos, 1.4) if planos else {"modo": "unico"}
        y_leg = OH // 2 if p_nome.get("modo") == "dividido" else int(OH * est.get("legenda_altura_short", 0.70))
        y_nome = y_leg + int(OH * est.get("nome_distancia", 0.072))
        linhas.append(f"Dialogue: 2,{_t_ass(1.4)},{_t_ass(4.6)},Nome,,0,0,0,,"
                      f"{{\\pos({OW // 2},{y_nome})\\fad(200,250)}}{_esc(nome.upper())}")
    if credito:
        linhas.append(f"Dialogue: 1,{_t_ass(0)},{_t_ass(fim_total)},Credito,,0,0,0,,{_esc(credito)}")
    mp = est.get("palavras_por_bloco", 3) if vertical else 7
    mc = est.get("chars_por_bloco", 16) if vertical else 42
    blocos = blocos_legenda(palavras, mp, mc)
    ult_fim = 0.0
    for bi, bloco in enumerate(blocos):
        textos = [_limpar(w["w"], maiusc, est.get("censurar_palavroes")) for w in bloco]
        prox_bloco = blocos[bi + 1][0]["s"] if bi + 1 < len(blocos) else fim_total
        for j, w in enumerate(bloco):
            # nunca sobrepor eventos: começa depois do anterior, termina antes do próximo bloco
            ini = max(w["s"], ult_fim)
            fim = bloco[j + 1]["s"] if j + 1 < len(bloco) else min(w["e"] + 0.15, prox_bloco)
            fim = min(fim, prox_bloco)
            if fim - ini < 0.04:
                continue
            ult_fim = fim
            if vertical:
                p = plano_em(planos, ini) if planos else {"modo": "unico"}
                y = OH // 2 if p.get("modo") == "dividido" else int(OH * est.get("legenda_altura_short", 0.70))
            else:
                y = int(PY * 0.87)
            anim = est.get("animacao_legenda", "pop") if vertical else None
            partes = []
            for k, tx in enumerate(textos):
                if k == j:
                    entra = "\\fscx70\\fscy70\\t(0,90,\\fscx112\\fscy112)" if anim == "palavra" else "\\fscx112\\fscy112"
                    partes.append(f"{{\\c{cor}{entra}}}{_esc(tx)}{{\\r}}")
                elif k > j and anim == "palavra":
                    partes.append(f"{{\\alpha&HFF&}}{_esc(tx)}{{\\r}}")
                else:
                    partes.append(_esc(tx))
            if anim and j == 0:
                cab = ANIM_LEGENDA.get(anim, ANIM_LEGENDA["pop"]).format(x=PX // 2, y=y, y2=y + 55, x0=PX // 2 - 90, cor=cor)
            else:
                cab = f"{{\\pos({PX // 2},{y})}}"
            linhas.append(f"Dialogue: 0,{_t_ass(ini)},{_t_ass(fim)},Leg,,0,0,0,,{cab}{' '.join(partes)}")
    Path(saida).write_text("\n".join(linhas) + "\n", encoding="utf-8")

# ----------------------------------------------------------------------------- render final

def _filtro_ass(ass, cwd):
    rel = os.path.relpath(ass, cwd).replace("\\", "/")
    fontes = os.path.relpath(FONTES_DIR, cwd).replace("\\", "/")
    return f"ass={rel}:fontsdir={fontes}"


AUDIO = ["-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-c:a", "aac", "-b:a", "192k", "-ar", "48000"]


def zooms_de_enfase(palavras, nivel=1.12, minimo=2.2):
    """Corte seco de zoom (1.0 ↔ nível) quando começa frase nova — o "jump zoom" dos Shorts."""
    marcas, ult, z = [(0.0, 1.0)], 0.0, 1.0
    for a, b in zip(palavras, palavras[1:]):
        if a["w"].rstrip().endswith((".", "?", "!")) and b["s"] - ult >= minimo:
            z = nivel if z == 1.0 else 1.0
            marcas.append((b["s"] - 0.05, z))
            ult = b["s"]
    return marcas


def _zoom_em(marcas, t):
    z = 1.0
    for t0, v in marcas:
        if t0 > t:
            break
        z = v
    return z


def _intervalos(lista, n):
    """[[a,b,c,d]] ou [[a,b,c,d,t0,t1]] → [(valores, t0, t1)] (sem tempo = o corte todo)."""
    out = []
    for item in lista or []:
        item = item if isinstance(item, (list, tuple)) else [item]
        vals, resto = list(item[:n]), list(item[n:])
        out.append((vals, resto[0] if resto else -1, resto[1] if len(resto) > 1 else 1e9))
    return out


def _carregar_logo(caminho, tam=70, opacidade=0.8):
    im = cv2.imread(str(caminho), cv2.IMREAD_UNCHANGED)
    if im is None or im.shape[2] < 4:
        return None
    im = cv2.resize(im, (tam, tam), interpolation=cv2.INTER_AREA)
    alfa = (im[:, :, 3:4].astype(np.float32) / 255.0) * opacidade
    return im[:, :, :3].astype(np.float32), alfa


def render_short(bruto, enq, ass, saida, zooms=None, barra=None, esconder=None, cortar_embaixo=None, encerramento=None,
                 logo=None, logo_y=56):
    """logo: PNG com transparência (logo do canal), colado pequeno no topo, centralizado, acima do gancho."""
    """esconder: [[x0,y0,x1,y1(,t0,t1)]] em 0–1 do vídeo ORIGINAL → desfoca (logo, QR, anúncio).
    cortar_embaixo: [[y(,t0,t1)]] ou número → o recorte não desce abaixo de y (faixa de anúncio embaixo fica de fora).
    Marcados à mão no cortes.json na conferência (detecção automática dava falso positivo em cenário)."""
    W, H, fps = enq["W"], enq["H"], enq["fps"]
    esc = _intervalos(esconder, 4)
    cortes_baixo = _intervalos([[cortar_embaixo]] if isinstance(cortar_embaixo, (int, float)) else cortar_embaixo, 1)
    dur_total = duracao(bruto) if (barra or encerramento) else None
    marca = _carregar_logo(logo) if logo else None
    cwd = str(Path(ass).parent)
    vf, audio = _filtro_ass(ass, cwd), list(AUDIO)
    if encerramento:
        st = max(0.0, dur_total - encerramento)
        vf += f",fade=t=out:st={st:.3f}:d={encerramento:.3f}"
        audio[1] = f"afade=t=out:st={st:.3f}:d={encerramento:.3f}," + audio[1]
    enc = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24",
                            "-s", f"{OW}x{OH}", "-r", f"{fps:.5f}", "-i", "-", "-i", str(bruto),
                            "-map", "0:v", "-map", "1:a", "-vf", vf,
                            *args_encoder_video("alta"), *audio, "-shortest", "-movflags", "+faststart",
                            str(saida)], stdin=subprocess.PIPE, cwd=cwd)
    for i, f in enumerate(_ler_frames(bruto, W, H, "null")):
        t = i / fps
        caixas = [v for v, a, b in esc if a <= t <= b]
        teto = min([max(0.6, v[0]) for v, a, b in cortes_baixo if a <= t <= b] or [1.0])
        quadro = compor(desfocar_caixas(f, caixas), plano_em(enq["planos"], t), _zoom_em(zooms, t) if zooms else 1.0, teto)
        if marca:
            quadro = np.ascontiguousarray(quadro)
            img, alfa = marca
            h_, w_ = img.shape[:2]
            x0 = (OW - w_) // 2
            reg = quadro[logo_y:logo_y + h_, x0:x0 + w_].astype(np.float32)
            quadro[logo_y:logo_y + h_, x0:x0 + w_] = (img * alfa + reg * (1 - alfa)).astype(np.uint8)
        if barra:   # barra de progresso fina no topo
            quadro = np.ascontiguousarray(quadro)
            quadro[:10, :int(OW * min(1.0, t / max(dur_total, 0.1)))] = barra
        enc.stdin.write(np.ascontiguousarray(quadro).tobytes())
    enc.stdin.close()
    if enc.wait() != 0:
        raise RuntimeError(f"Falhou encode do short {saida}")


def render_horizontal(bruto, ass, saida):
    cwd = str(Path(ass).parent)
    vf = "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2," + _filtro_ass(ass, cwd)
    run(["ffmpeg", "-y", "-v", "error", "-i", str(bruto), "-vf", vf, *args_encoder_video("alta"), *AUDIO,
         "-movflags", "+faststart", str(saida)], cwd=cwd)


def escolher_quadros_thumb(bruto, enq, n=3):
    """Quadros candidatos pra thumbnail: rosto grande + nítido, espaçados no tempo."""
    cands = []
    for a in enq["amostras"]:
        if not a["faces"]:
            continue
        f = max(a["faces"], key=lambda x: x["w"])
        cands.append((f["w"] * min(a["nitidez"], 400) / 400, a["t"]))
    cands.sort(reverse=True)
    escolhidos = []
    for nota, t in cands:
        if all(abs(t - e) > 4 for e in escolhidos):
            escolhidos.append(t)
        if len(escolhidos) == n:
            break
    return sorted(escolhidos)
