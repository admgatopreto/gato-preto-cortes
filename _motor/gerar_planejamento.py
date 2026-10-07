"""Preenche as pastas canal-temaN-<nicho> com o resultado de pesquisar_nicho.py:
PLANEJAMENTO.md (fontes ranqueadas + concorrência + pendências) e 'candidatos' no canal.json.
Uso: python gerar_planejamento.py ..\\_pesquisa\\nichos_resultado.json"""
import json, sys
from datetime import date
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "lib"))
sys.stdout.reconfigure(encoding="utf-8")
from util import RAIZ, ler_json, salvar_json
sys.path.insert(0, str(Path(__file__).parent))
from pesquisar_nicho import idioma

# falam de tudo: aparecem em vários nichos. Viram seção própria ("cortar só episódios do tema").
GENERALISTAS_FIXOS = {"Flow Podcast", "Inteligência Ltda", "Podpah TV"}

NOMES = {"negocios": "Negócios e dinheiro", "ciencia": "Ciência e curiosidades", "misterio": "Mistério e paranormal",
         "historia": "História", "fe": "Fé", "esporte": "Esporte",
         "politica": "Política", "games": "Games"}


def fmt_n(n):
    n = n or 0
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f} mi".replace(".", ",")
    if n >= 1000:
        return f"{n / 1000:.0f} mil"
    return str(n)


def main():
    dados = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    from collections import Counter
    for v in dados.values():                          # idioma recalculado com o detector atual
        for c in v["podcasts"].values():
            if "perfil" in c:
                c["perfil"]["idioma"] = idioma(c["perfil"].get("sobre", ""))
    aud = {c["url"]: c["auditoria"] for v in dados.values() for c in v["podcasts"].values() if "auditoria" in c}
    for v in dados.values():                          # mesma fonte auditada num nicho vale pros outros
        for c in v["podcasts"].values():
            if "auditoria" not in c and c["url"] in aud:
                c["auditoria"] = aud[c["url"]]
    presenca = Counter(c["canal"] for v in dados.values() for c in v["podcasts"].values()
                       if c.get("perfil", {}).get("longos", 0) >= 3 and c["perfil"].get("idioma") != "outro")
    generalistas = GENERALISTAS_FIXOS | {n for n, k in presenca.items() if k >= 3}
    for pasta in sorted(RAIZ.glob("canal-tema*")):
        nicho = pasta.name.split("-", 2)[2]
        d = dados.get(nicho)
        if not d:
            print(f"{pasta.name}: sem dados de pesquisa ainda")
            continue
        pods = sorted(d["podcasts"].values(), key=lambda c: -(c["inscritos"] or 0))
        todos = [c for c in pods if c.get("perfil", {}).get("longos", 0) >= 3
                 and c["perfil"].get("idioma") != "outro"]
        confirmados = [c for c in todos if c["canal"] not in generalistas]
        gerais = [c for c in todos if c["canal"] in generalistas]
        cortes = [c for c in sorted(d["cortes"].values(), key=lambda c: -(c["inscritos"] or 0))
                  if c.get("perfil", {}).get("idioma") != "outro"][:8]

        L = [f"# {pasta.name} — {NOMES.get(nicho, nicho)}", "",
             f"Canal provisório (nome/identidade ainda não definidos). Pesquisa de {date.today():%d/%m/%Y}.", "",
             "## Maiores podcasts do nicho (fontes possíveis)", "",
             "Formato confirmado = pelo menos 3 dos últimos 15 vídeos com 40 min ou mais.", "",
             "| # | Podcast | Inscritos | Episódios longos | Permissão | Contato |",
             "|---|---|---|---|---|---|"]
        for i, c in enumerate(confirmados[:15], 1):
            a = c.get("auditoria", {})
            st = a.get("status", "não auditado")
            if a.get("espera_horas"):
                st += f" ({a['espera_horas']}h)"
            L.append(f"| {i} | [{c['canal']}]({c['url']}) | {fmt_n(c['inscritos'])} | "
                     f"{c['perfil']['longos']}/{c['perfil']['lidos']} (~{c['perfil']['mediana_min']} min) | {st} | "
                     f"{', '.join(a.get('emails', [])) or '—'} |")
        if gerais:
            L += ["", "**Generalistas** (falam de tudo; usar só episódios com convidado/tema do nicho):", ""]
            for c in gerais:
                a = c.get("auditoria", {})
                L.append(f"- [{c['canal']}]({c['url']}) — {fmt_n(c['inscritos'])} — {a.get('status', 'não auditado')}"
                         + (f" — {', '.join(a['emails'])}" if a.get("emails") else ""))
        trechos = [(c["canal"], t) for c in confirmados + gerais for t in c.get("auditoria", {}).get("trechos", [])]
        if trechos:
            L += ["", "Regras de cortes encontradas por escrito:", ""]
            L += [f"- **{n}**: {t}" for n, t in trechos]
        L += ["", "## Maiores canais de cortes do nicho (concorrência / referência)", "",
              "| Canal | Inscritos | Duração mediana dos vídeos | Sobre o canal |", "|---|---|---|---|"]
        for c in cortes:
            p = c.get("perfil", {})
            L.append(f"| [{c['canal']}]({c['url']}) | {fmt_n(c['inscritos'])} | ~{p.get('mediana_min', '?')} min | "
                     f"{(p.get('sobre') or '').replace('|', '/').replace(chr(10), ' ')[:80]} |")
        L += ["", "## Pendências", "",
              "- [ ] Escolher nome, @ e identidade (cor de destaque no canal.json, avatar e banner via GPT)",
              "- [ ] Mandar e-mail pedindo autorização às fontes escolhidas; com resposta positiva → status LIBERADO em `canal.json` + prova em `evidencia`",
              "- [ ] Primeiro episódio: `cortes preparar " + pasta.name + " <url>`",
              "- [ ] Agenda de postagem e playlists", ""]
        (pasta / "PLANEJAMENTO.md").write_text("\n".join(L), encoding="utf-8")

        cfg = ler_json(pasta / "canal.json")
        cfg["nicho"] = NOMES.get(nicho, nicho)
        cfg["candidatos"] = [{"canal": c["canal"], "canal_url": c["url"], "inscritos": c["inscritos"],
                              "status": c.get("auditoria", {}).get("status", "NÃO AUDITADO"),
                              "emails": c.get("auditoria", {}).get("emails", [])} for c in confirmados[:15]]
        cfg["concorrentes"] = [{"canal": c["canal"], "canal_url": c["url"], "inscritos": c["inscritos"]} for c in cortes]
        salvar_json(pasta / "canal.json", cfg)
        print(f"{pasta.name}: {len(confirmados)} podcasts confirmados, {len(cortes)} concorrentes")


if __name__ == "__main__":
    main()
