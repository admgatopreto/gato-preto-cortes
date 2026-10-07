"""Fila de renderização: renderiza, um por vez, todo episódio que tem cortes.json e ainda não foi renderizado
(marcador trabalho/.renderizado). Fica de olho até existir o arquivo _pesquisa/fila.parar e não haver pendência.
Uso: python fila_render.py"""
import subprocess, sys, time
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8")
RAIZ = Path(__file__).resolve().parents[1]
PARAR = RAIZ / "_pesquisa" / "fila.parar"


def pendentes():
    for cj in sorted(RAIZ.glob("canal-*/episodios/*/cortes.json")):
        ep = cj.parent
        marca = ep / "trabalho" / ".renderizado"
        trava = ep / "trabalho" / ".renderizando"
        if trava.exists() and time.time() - trava.stat().st_mtime < 3 * 3600:
            continue                       # outra fila está renderizando este
        if not marca.exists() or marca.stat().st_mtime < cj.stat().st_mtime:
            yield ep.parents[1].name, ep.name, ep


def reservar(ep):
    """Reserva o episódio pra esta fila (várias filas podem rodar em paralelo)."""
    (ep / "trabalho").mkdir(exist_ok=True)
    try:
        fd = __import__("os").open(ep / "trabalho" / ".renderizando", __import__("os").O_CREAT | __import__("os").O_EXCL)
        __import__("os").close(fd)
    except FileExistsError:
        return False
    (ep / "trabalho" / ".renderizado").touch()   # filas antigas (sem trava) também passam a pular
    return True


while True:
    fez = False
    for canal, vid, ep in pendentes():
        if not reservar(ep):
            continue
        fez = True
        print(f"RENDER {canal} {vid}", flush=True)
        t0 = time.time()
        with open(ep / "render.log", "w", encoding="utf-8") as log:
            p = subprocess.run([sys.executable, str(RAIZ / "_motor" / "cortes.py"), "renderizar", canal, vid],
                               stdout=log, stderr=subprocess.STDOUT, env={**__import__("os").environ,
                               "PYTHONIOENCODING": "utf-8", "CORTES_NAO_ABRIR": "1"})
        if p.returncode == 0:
            (ep / "trabalho").mkdir(exist_ok=True)
            (ep / "trabalho" / ".renderizado").touch()
            print(f"OK {canal} {vid} ({(time.time() - t0) / 60:.0f} min)", flush=True)
        else:
            print(f"ERRO {canal} {vid} — ver {ep / 'render.log'}", flush=True)
            (ep / "trabalho").mkdir(exist_ok=True)
            (ep / "trabalho" / ".renderizado").touch()   # não entra em loop; corrigir e tocar o cortes.json de novo
        (ep / "trabalho" / ".renderizando").unlink(missing_ok=True)
        break
    if not fez:
        if PARAR.exists():
            print("FIM", flush=True)
            break
        time.sleep(30)
