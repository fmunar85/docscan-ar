"""
Script de arranque — lee PORT del entorno y lanza gunicorn sin depender del shell.
Railway, Heroku, Render, etc. siempre inyectan PORT como entero en os.environ.
"""
import os
import subprocess
import sys

port = os.environ.get("PORT", "5000")
print(f"[start] Arrancando en 0.0.0.0:{port}", flush=True)

cmd = [
    "gunicorn", "app:app",
    "--bind", f"0.0.0.0:{port}",
    "--workers", "1",
    "--timeout", "120",
    "--access-logfile", "-",
]

sys.exit(subprocess.call(cmd))
