# Fábrica de Canais de Cortes

Um motor só (`_motor\`) serve todos os canais. Cada canal é uma pasta com um `canal.json`.

```
F:\CORTES\
  cortes.bat              ← atalho de tudo (rodar no PowerShell/CMD dentro de F:\CORTES)
  _motor\                 ← código, fontes de legenda, modelo de rosto, venv (não mexer)
  _pesquisa\              ← auditoria de podcasts candidatos
  <canal>\
    canal.json            ← nome, nicho, fontes liberadas, estilo da legenda, textos de descrição
    PLANEJAMENTO.md       ← decisões do canal, identidade, agenda
    fontes_auditoria.json ← histórico das auditorias de permissão
    episodios\<id>\       ← video.mp4, transcricao.json, leitura.txt, cortes.json
    prontos\<data>_<id>\  ← shorts\ (mp4 + txt juntos), verificacao\, relatorio.md
  ABRIR-PAINEL.bat        ← painel de progresso no navegador (duplo clique)
  painel-estado.json      ← o que o painel guarda: Shorts aprovados/reprovados/publicados e avisos
```

## Painel de progresso

Atalho **"Fábrica de Cortes"** na área de trabalho: abre o painel numa janela própria (como aplicativo), sem janela
preta. Ele desliga sozinho uns 5 minutos depois que você fecha a janela. (Alternativa com console: `ABRIR-PAINEL.bat`
ou `cortes painel`; endereço `http://localhost:8765`.)

Na tela do episódio dá pra revisar só pelo teclado: **← →** passa de Short, **A** aprova, **R** reprova (e já vai pro
próximo), **Espaço** toca/pausa, **T / D / G** copiam título, descrição e tags.

- **Visão geral:** canais, etapas de todos os episódios, Shorts aprovados/publicados e o que está renderizando agora.
- **Canal:** status de permissão de cada fonte (gravado no `canal.json`), botão que copia o e-mail de pedido já com o
  nome do podcast, "marcar enviado hoje". Para LIBERADO o painel pede onde está a autorização.
- **Episódio:** assiste cada Short, aprova ou reprova, copia título/descrição/tags pro upload e marca como publicado
  (só deixa se a fonte estiver LIBERADA e o Short aprovado). Mostra palavrão na legenda e os avisos da conferência.

O progresso vem das próprias pastas, então o painel nunca fica desatualizado.

### Novos episódios (radar)
Aba **★ Novos episódios** do painel. O radar (`_motor\radar.py`) roda sozinho todo dia às 9h (Agendador do
Windows, tarefa "Fabrica de Cortes - Radar") ou pelo botão **Procurar agora**. Para cada canal ele olha os últimos
episódios longos das fontes e dos candidatos e dá uma **nota de 0 a 100** (metade desempenho contra a média do próprio
canal, metade visualizações por dia no nicho). Antes de baixar, já descarta ou avisa:
imagem parada (pela tira de miniaturas do YouTube), fora do português, política fora do canal de Política, tema
eleitoral no canal de Política até 25/10, caso criminal com suspeito nomeado, transmissão de jogo/NASA/TV (Content ID),
live de vendas, live lendo chat. Fontes fora do nicho ficam com `nao_usar` no `canal.json`
(lista em `_pesquisa\candidatos_nao_usar.json`); episódios removidos ficam em `_pesquisa\descartados.json`.
**Quero esse** coloca na fila e o painel faz TUDO sozinho, um episódio por vez: baixa → transcreve → descarta se for
imagem parada → **curadoria automática** (o Claude Code da extensão do VS Code roda sem janela, seguindo a skill
`cortes`: escolhe os Shorts, valida, renderiza no visual padrão, confere 100% das legendas e mosaicos, corrige e grava
os avisos em `episodios\<id>\avisos.json`) → aparece como **Shorts prontos para aprovar**. Log da sessão em
`_pesquisa\auto_<id>.log`. Episódio já transcrito sem cortes: botão **Curadoria automática** na página dele.
O painel não desliga sozinho enquanto houver download, transcrição ou curadoria rodando.

**Enviar para o YouTube (automático):**
1. Uma vez só (vale para os 8 canais): no Google Cloud (console.cloud.google.com) crie um projeto, ative a
   **YouTube Data API v3**, configure a tela de consentimento (tipo Externo, adicione seu e-mail como usuário de teste)
   e crie uma credencial **ID do cliente OAuth → App para computador**. Baixe o JSON e salve como
   `F:\CORTES\_segredos\youtube_client.json`.
2. Na página do canal no painel: **Conectar YouTube** → o navegador abre → escolha a conta e o canal → autorize.
3. Ligue **Enviar automaticamente**. O painel agenda nos horários do canal (12h e 19h) os Shorts **aprovados** de
   fonte **LIBERADA**, até 5 por dia (cota grátis da API). App não verificado pelo Google → vídeos ficam privados
   até pedir a verificação do app no Google Cloud.

**Piloto automático (Ciência):** na página do canal, quadro "Piloto automático". Com "Escolher episódios sozinho"
ligado, o painel mantém um estoque de Shorts (alvo: 7 dias de publicação). Quando baixa do alvo, ele escolhe sozinho o
melhor episódio novo de fonte LIBERADA, baixa, corta, renderiza e confere. Você só revisa no **▶ Revisar** e aprova; os
aprovados entram na agenda do YouTube sozinhos. Às 20h chega um resumo do dia. O painel fica sempre ligado (tarefa
"Gato Preto Cortes - Painel" do Windows, no login); o atalho só abre a janela.

**Corrigir um Short:** marque **Fora do padrão** (com os motivos e uma observação) e ele volta para a produção; ou
**Reprovar** (escreva o motivo) e ele volta para a conferência. Uns 45 s depois do último clique o Claude pega o Short,
corrige na causa (ou troca por um trecho melhor do mesmo episódio), renderiza só ele, confere e devolve para você revisar
com um aviso "Refeito: …". O que valer como regra vai para `_pesquisa\regras_aprendidas.md` e passa a valer para os
próximos episódios.

### Visual novo do Short (em teste)
Comparação lado a lado em `F:\CORTES\_comparacao\`. Liga por canal no `canal.json` → `estilo`:
`falante_ativo` (close em quem fala no plano aberto), `zoom_enfase`, `barra_progresso`, `gancho_animado`,
`nome_convidado`, `censurar_palavroes`. Por corte, no `cortes.json`: `"esconder": [[x0,y0,x1,y1]]` desfoca uma área
(logo/QR/anúncio; valores de 0 a 1 do vídeo original, opcionalmente com `t0,t1`) e `"cortar_embaixo": 0.77` fecha o
enquadramento acima de uma faixa de anúncio.

## Fluxo de um episódio

| Passo | Quem | Comando / ação |
|---|---|---|
| 1. Auditar a fonte (1x por podcast, e de novo de tempos em tempos) | motor | `cortes auditar <url do canal do podcast> --canal <canal> --adicionar` |
| 2. Baixar + transcrever | motor | `cortes preparar <canal> <url do episódio>` |
| 3. Escolher os cortes | Claude | lê `leitura.txt` e escreve `cortes.json` (ver abaixo) |
| 4. Renderizar | motor | `cortes renderizar <canal> <id>` |
| 5. Conferir | Claude + você | mosaicos em `verificacao\`, `relatorio.md`, assistir 1-2 |
| 6. Thumbnails dos horizontais | você (GPT) | Claude escreve o prompt a partir de `thumbnails\referencias\` |
| 7. Upload | você | cada `.mp4` tem o `.txt` ao lado com TÍTULO / DESCRIÇÃO / TAGS |

**Regra de permissão:** o motor só baixa de fonte com status `LIBERADO` no `canal.json`.
- `CONDICIONAL` = "permitido desde que…" com contato por e-mail. Mandar e-mail, guardar a resposta, mudar pra `LIBERADO` e anotar a prova em `evidencia`.
- `SEM MENÇÃO` não é permissão.
- Se a fonte tem `espera_horas` (ex.: 24h), o motor avisa. Não publicar antes disso.

## cortes.json (escrito pelo Claude na curadoria)

```json
{
  "cortes": [
    {
      "id": "01",
      "inicio": "00:12:03.5", "fim": "00:13:20",
      "formatos": ["short"],
      "remover": [["00:12:40", "00:12:48"]],
      "gancho": "TEXTO FIXO NO TOPO DO SHORT",
      "titulo": "Título do vídeo horizontal (até 100 caracteres)",
      "titulo_short": "Título do Short",
      "descricao": "1-3 frases sobre o corte",
      "convidado": "Nome do convidado",
      "tags": ["tag1", "tag2"]
    }
  ]
}
```

- **Jeito preferido:** `"de": "primeiras palavras do corte"` e `"ate": "últimas palavras do corte"` + `inicio`/`fim` aproximados (±2 min). O motor acha o tempo exato pelo texto; se não achar, para com erro mostrando o texto da região. Trecho do meio a tirar: `"remover_texto": [["começo do trecho", "fim do trecho"]]`.
- Alternativa: `inicio` = tempo exato da 1ª palavra; `fim` = qualquer tempo depois do início da última palavra. Pra ver os tempos: `cortes palavras <canal> <id> 00:12:00 00:13:30`.
- `correcoes` (no topo do cortes.json, ou no canal.json pra valer sempre): `{"Quarto Milionários": "Cortes Bilionários"}` corrige erro de transcrição na legenda.
- O texto exato de cada legenda sai em `verificacao\NN_formato_legenda.txt` — revisar antes de publicar.
- `formatos`: `short` (9:16, até 3 min), `horizontal` (16:9) ou os dois.
- `remover`: trechos a tirar do meio (tangente, interrupção, propaganda).
- Pausas longas entre falas são apertadas automaticamente (configurável em `canal.json` → `short.pausa_max`).

## O que o motor faz no Short

- Detecta troca de câmera quadro a quadro e rostos em cada plano:
  - 1 pessoa: close nela.
  - 2 pessoas longe uma da outra: tela dividida (uma em cima, outra embaixo, legenda na emenda).
  - Sem rosto: vídeo inteiro no meio com fundo desfocado.
- Legenda animada de 3 em 3 palavras, com a palavra falada em destaque.
- Gancho fixo no topo e crédito do podcast embaixo.
- Áudio normalizado (-14 LUFS, padrão do YouTube).

## Canais provisórios

`canal-tema1-negocios` … `canal-tema6-esporte`: cada pasta tem `PLANEJAMENTO.md` com os maiores podcasts do nicho
(permissão + e-mail de contato), os generalistas e os maiores canais de cortes concorrentes, além de `email-permissao.txt`
(modelo do pedido de autorização). Quando o nome do canal for definido, é só renomear a pasta e ajustar o `canal.json`.

## Canal novo

```
cortes novo-canal <pasta> --nome "Nome do Canal"
```
Depois é só ajustar `canal.json` (cor, nicho, textos de descrição) e auditar as fontes.
