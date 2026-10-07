# Regras aprendidas com as correções do usuário

A curadoria automática lê este arquivo antes de cada episódio. Uma regra por linha.

- 2026-10-06 · visual · Sem texto de marca e sem nome do convidado no Short; só o logo discreto.
- 2026-10-06 · enquadramento · Pessoa ao fundo/plateia não entra em tela dividida; close em quem fala.
- 2026-10-06 · enquadramento · Trecho de slide com o vídeo numa janelinha: usar janela_original.
- 2026-10-06 · conteúdo · Vídeo de imagem parada (só áudio) não serve; descartar.
- 2026-10-06 · curadoria · Evitar Short que é quase só plano aberto de plateia.
- 2026-10-07 · enquadramento · Antes de fechar de/ate, ver a câmera do original no trecho (mosaico ffmpeg 1 quadro/2s): se ela mostra os ouvintes ou o plano aberto enquanto o convidado fala (sobretudo na frase de abertura e no final), mudar de/ate pra cair no close dele e cortar com remover_texto a conversa paralela em que a câmera fica nos outros.
- 2026-10-07 · curadoria · Short não pode abrir com conector ou pronome sem referente ("Por exemplo, ele…", "E aí ele…"): recuar o de até a frase que diz QUEM é o assunto (ex.: a pergunta do quadro) e usar remover_texto pra tirar a enrolação do meio.
