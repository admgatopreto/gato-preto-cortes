"""Filtro do git ("clean"): troca qualquer endereço de e-mail por [e-mail removido] na versão que vai pro repositório.
No seu PC os arquivos continuam com os contatos (o painel usa); no GitHub (público) vai sem.
Configurado em .git/config (filter.sememails) e .gitattributes."""
import re
import sys

EMAIL = re.compile(rb"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}")
dados = sys.stdin.buffer.read()
sys.stdout.buffer.write(EMAIL.sub(b"[e-mail removido]", dados))
