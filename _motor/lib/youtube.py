"""Conexão com o YouTube (API oficial, YouTube Data API v3) e envio de Shorts.

Arquivos (NÃO compartilhar):
  F:\\CORTES\\_segredos\\youtube_client.json        app OAuth do Google Cloud (um só pra todos os canais)
  F:\\CORTES\\_segredos\\youtube_<canal>.json       autorização de cada canal (gerada ao conectar)

Regras de segurança (iguais às do painel):
  - só envia Short APROVADO pelo usuário e de fonte com status LIBERADO no canal.json;
  - confere se o canal conectado é o @ do canal.json antes de enviar;
  - respeita a espera da fonte (espera_horas) e a agenda do canal (horários).
Obs.: app não verificado pelo Google sobe vídeo como PRIVADO até passar na verificação (audit) do Google."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from util import RAIZ

SEGREDOS = RAIZ / "_segredos"
CLIENTE = SEGREDOS / "youtube_client.json"
ESCOPOS = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.readonly"]
CATEGORIA = {"negocios": "22", "ciencia": "28", "misterio": "24", "historia": "27", "fe": "22",
             "esporte": "17", "politica": "25", "games": "20"}   # 22 Pessoas e blogs, 28 Ciência e tecnologia, 24 Entretenimento,
                                                                  # 27 Educação, 17 Esportes, 25 Notícias e política, 20 Jogos
FUSO = timezone(timedelta(hours=-3))   # horário de Brasília


def arquivo_token(pasta):
    return SEGREDOS / f"youtube_{pasta}.json"


def conectado(pasta):
    return arquivo_token(pasta).exists()


def _credenciais(pasta):
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    cred = Credentials.from_authorized_user_file(str(arquivo_token(pasta)), ESCOPOS)
    if cred.expired and cred.refresh_token:
        cred.refresh(Request())
        arquivo_token(pasta).write_text(cred.to_json(), encoding="utf-8")
    return cred


def _servico(pasta):
    from googleapiclient.discovery import build
    return build("youtube", "v3", credentials=_credenciais(pasta), cache_discovery=False)


def autenticar(pasta):
    """Abre o navegador pra o usuário escolher a conta/canal e autorizar. Devolve o canal conectado."""
    from google_auth_oauthlib.flow import InstalledAppFlow
    if not CLIENTE.exists():
        raise RuntimeError(f"Falta o app do Google: salve o arquivo baixado do Google Cloud como {CLIENTE}")
    SEGREDOS.mkdir(exist_ok=True)
    fluxo = InstalledAppFlow.from_client_secrets_file(str(CLIENTE), ESCOPOS)
    cred = fluxo.run_local_server(port=0, prompt="consent", open_browser=True,
                                  success_message="Pronto! O canal foi conectado à fábrica Gato Preto. Pode fechar esta aba.")
    arquivo_token(pasta).write_text(cred.to_json(), encoding="utf-8")
    return canal_conectado(pasta)


def canal_conectado(pasta):
    r = _servico(pasta).channels().list(part="snippet", mine=True).execute()
    itens = r.get("items") or []
    if not itens:
        raise RuntimeError("A conta autorizada não tem canal do YouTube.")
    sn = itens[0]["snippet"]
    return {"channel_id": itens[0]["id"], "titulo": sn.get("title"), "handle": sn.get("customUrl", "")}


def confere_canal(pasta, cfg):
    """O canal autorizado é o mesmo do canal.json? (evita subir Short de Ciência no canal de Games)"""
    yt = canal_conectado(pasta)
    esperado = (cfg.get("handle") or "").lstrip("@").lower()
    real = (yt.get("handle") or "").lstrip("@").lower()
    if esperado and real and esperado != real:
        raise RuntimeError(f"Canal conectado é @{real}, mas este canal é @{esperado}. Conecte de novo com a conta certa.")
    return yt


def proximo_horario(cfg, ocupados, minimo=None):
    """Próximo horário livre da agenda do canal (canal.json → publicacao.agenda.horarios), em UTC ISO."""
    agenda = cfg.get("publicacao", {}).get("agenda", {})
    horarios = agenda.get("horarios") or ["12:00", "19:00"]
    agora = datetime.now(FUSO) + timedelta(minutes=30)
    base = max(agora, minimo.astimezone(FUSO)) if minimo else agora
    ocup = {o[:16] for o in ocupados}
    for dia in range(0, 60):
        d = (base + timedelta(days=dia)).date()
        for h in horarios:
            hh, mm = (int(x) for x in h.split(":"))
            t = datetime(d.year, d.month, d.day, hh, mm, tzinfo=FUSO)
            iso = t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M")
            if t > base and iso not in ocup:
                return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:00Z")
    raise RuntimeError("Agenda cheia nos próximos 60 dias.")


def enviar_short(pasta, cfg, mp4, titulo, descricao, tags, publicar_em):
    """Sobe o Short agendado (privado até publicar_em). Devolve o id do vídeo."""
    from googleapiclient.http import MediaFileUpload
    nicho = pasta.split("-", 2)[2]
    corpo = {
        "snippet": {"title": titulo[:100], "description": descricao[:4900], "tags": [t for t in tags if t][:30],
                    "categoryId": CATEGORIA.get(nicho, "22"), "defaultLanguage": "pt-BR", "defaultAudioLanguage": "pt-BR"},
        "status": {"privacyStatus": "private", "publishAt": publicar_em, "selfDeclaredMadeForKids": False,
                   "embeddable": True, "license": "youtube"},
    }
    mid = MediaFileUpload(str(mp4), mimetype="video/mp4", chunksize=8 * 1024 * 1024, resumable=True)
    req = _servico(pasta).videos().insert(part="snippet,status", body=corpo, media_body=mid, notifySubscribers=True)
    resp = None
    while resp is None:
        _, resp = req.next_chunk()
    return resp["id"]
