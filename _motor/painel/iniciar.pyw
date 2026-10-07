"""Atalho da área de trabalho: liga o painel (sem janela preta) e abre numa janela própria, como aplicativo.
Se o painel já estiver ligado, só abre a janela. O painel fica sempre ligado (tarefa "Gato Preto Cortes - Painel" do Windows)."""
import os, socket, subprocess, sys, time, webbrowser
from pathlib import Path

AQUI = Path(__file__).resolve().parent
PORTA = 8765
URL = f"http://localhost:{PORTA}"


def no_ar():
    try:
        socket.create_connection(("127.0.0.1", PORTA), 0.4).close()
        return True
    except OSError:
        return False


if not no_ar():
    pyw = Path(sys.executable).with_name("pythonw.exe")
    if not pyw.exists():
        pyw = Path(sys.executable)
    subprocess.Popen([str(pyw), str(AQUI / "servidor.py"), "--porta", str(PORTA), "--nao-abrir"],
                     cwd=str(AQUI), close_fds=True,
                     creationflags=0x00000008 | 0x00000200)   # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    for _ in range(60):
        if no_ar():
            break
        time.sleep(0.2)

edge = None
for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
    if base and (Path(base) / "Microsoft/Edge/Application/msedge.exe").exists():
        edge = Path(base) / "Microsoft/Edge/Application/msedge.exe"
        break
if edge:
    subprocess.Popen([str(edge), f"--app={URL}", "--window-size=1440,920"], close_fds=True)
else:
    webbrowser.open(URL)
