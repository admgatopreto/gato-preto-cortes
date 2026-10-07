"""Registra as DLLs CUDA instaladas via pip (nvidia-cublas/cudnn) pro ctranslate2 achar no Windows."""
import os, sys, glob

def preparar_cuda():
    base = os.path.join(sys.prefix, "Lib", "site-packages", "nvidia")
    for d in glob.glob(os.path.join(base, "*", "bin")):
        os.add_dll_directory(d)
        os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")

def tem_gpu():
    preparar_cuda()
    try:
        import ctranslate2
        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False
