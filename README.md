# Gato Preto · Fábrica de Cortes

Fábrica de canais de cortes de podcast para YouTube Shorts — a família **Gato Preto** (Ciência, Negócios, Mistério,
História, Fé, Esporte, Política, Games).

Do episódio completo ao Short agendado no YouTube:

1. **Radar** — acha episódios novos das fontes de cada canal, dá nota pelo desempenho e filtra antes de baixar
   (imagem parada, política fora do canal, caso criminal com suspeito nomeado, transmissão com Content ID…).
2. **Radar de fontes** — procura podcasts que liberam cortes publicamente e guarda a prova.
3. **Download + transcrição** (yt-dlp + Whisper na GPU).
4. **Curadoria automática** — sessão do Claude Code sem janela escolhe os cortes, valida, renderiza e confere.
5. **Render** — Short 9:16 com close em quem fala, zoom de ênfase, legenda animada, gancho, logo do canal,
   barra de progresso e encerramento; auditoria automática de enquadramento.
6. **Painel** (`_motor/painel`) — revisão em sequência (A aprova, R reprova, F fora do padrão), correção automática
   do que for reprovado, piloto automático por estoque, publicação agendada pela API do YouTube.

Só publica cortes de fontes que **liberaram** (por escrito, publicamente ou por e-mail), sempre com crédito e link do
episódio completo.

## Rodar

Windows, Python 3.11, ffmpeg, yt-dlp e uma GPU NVIDIA. Venv em `_motor/venv`
(`pip install -r` com faster-whisper, opencv-python, numpy, pillow, google-api-python-client, google-auth-oauthlib).

- Painel: `ABRIR-PAINEL.bat` (ou `cortes painel`) → http://localhost:8765
- Linha de comando: `cortes.bat` (ver `COMO-USAR.md`)

Arquivos de acesso ao YouTube ficam em `_segredos/` (fora do git). Os e-mails de contato dos podcasts são removidos
automaticamente das versões que vão pro repositório (filtro em `_motor/git_sem_emails.py`).
