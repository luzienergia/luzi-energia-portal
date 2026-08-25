"""
servidor_admin.py — Servidor local do painel admin da Luzi Energia
===================================================================
Execute este script no Mac antes de abrir o painel admin.
Ele serve o painel e salva/publica mudanças automaticamente.

Como usar:
  cd /Users/luiz/Claude/Projects/Sistema\ Luzi\ Energia/portal
  python3 servidor_admin.py

Depois abra no navegador: http://localhost:8080

O painel vai:
  - Salvar qualquer mudança que você fizer instantaneamente
  - Fazer push para o GitHub automaticamente
  - O site Netlify atualiza em ~30 segundos
"""

from __future__ import annotations
import json, os, sys, subprocess, webbrowser, threading, time
from datetime import datetime
from pathlib import Path
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse

PORTAL_DIR = Path(__file__).parent
DATA_JSON  = PORTAL_DIR / "data.json"
GIT_ROOT   = PORTAL_DIR.parent   # raiz do repositório git
PORT       = 8080

# ─── Carregar / salvar data.json ──────────────────────────────────────────────
def carregar():
    if DATA_JSON.exists():
        with open(DATA_JSON, encoding="utf-8") as f:
            return json.load(f)
    return {"clientes": [], "usinas": [], "status_ucs": {}, "atualizado": datetime.now().isoformat()}

def salvar(data: dict):
    data["atualizado"] = datetime.now().isoformat()
    with open(DATA_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ─── Git push em background (sem travar o servidor) ───────────────────────────
_push_timer = None

def agendar_push(delay=3):
    """Aguarda 3s após a última mudança e faz um único push."""
    global _push_timer
    if _push_timer:
        _push_timer.cancel()
    _push_timer = threading.Timer(delay, fazer_push)
    _push_timer.start()

def fazer_push():
    try:
        subprocess.run(["git", "-C", str(GIT_ROOT), "add", "portal/data.json"], capture_output=True)
        msg = f"[admin] Atualiza data.json — {datetime.now().strftime('%d/%m %H:%M')}"
        r = subprocess.run(["git", "-C", str(GIT_ROOT), "commit", "-m", msg], capture_output=True)
        if b"nothing to commit" in r.stdout:
            return  # Nada mudou, sem push
        subprocess.run(["git", "-C", str(GIT_ROOT), "push"], capture_output=True)
        print(f"  🚀 Publicado no GitHub às {datetime.now().strftime('%H:%M:%S')}")
    except Exception as e:
        print(f"  ⚠️  Push falhou: {e}")

# ─── Handler HTTP ─────────────────────────────────────────────────────────────
class AdminHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(PORTAL_DIR), **kwargs)

    def log_message(self, fmt, *args):
        # Silencia logs de arquivos estáticos (CSS, JS, fontes)
        if args and ('.css' in str(args[0]) or '.js' in str(args[0]) or 'font' in str(args[0])):
            return
        print(f"  [{datetime.now().strftime('%H:%M:%S')}] {fmt % args}")

    def do_GET(self):
        parsed = urlparse(self.path)
        path   = parsed.path

        if path == "/api/data":
            self._json(carregar())
        elif path == "/api/ping":
            self._json({"ok": True, "modo": "local", "versao": "1.0"})
        else:
            super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        path   = parsed.path

        length = int(self.headers.get("Content-Length", 0))
        body   = self.rfile.read(length) if length else b"{}"

        if path == "/api/save":
            try:
                data = json.loads(body)
                salvar(data)
                agendar_push()
                self._json({"ok": True, "ts": datetime.now().isoformat()})
                print(f"  💾 data.json salvo — push agendado")
            except Exception as e:
                self._json({"ok": False, "erro": str(e)}, 500)

        elif path == "/api/verificar-pagamentos":
            # Roda verificação BTG em background e responde imediatamente
            def rodar():
                try:
                    sys.path.insert(0, str(PORTAL_DIR.parent / "BTG_Boletos"))
                    from btg_verificar_pagamentos import verificar_todos
                    verificar_todos()
                    agendar_push(1)
                except Exception as e:
                    print(f"  ⚠️  Erro ao verificar pagamentos: {e}")
            threading.Thread(target=rodar, daemon=True).start()
            self._json({"ok": True, "msg": "Verificando pagamentos BTG em background..."})

        else:
            self._json({"erro": "Rota não encontrada"}, 404)

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors_headers()
        self.end_headers()

    def _json(self, data: dict, status=200):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self._cors_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def _cors_headers(self):
        self.send_header("Access-Control-Allow-Origin",  "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")


# ─── Iniciar servidor ─────────────────────────────────────────────────────────
def iniciar():
    # Garante que data.json existe
    if not DATA_JSON.exists():
        salvar({"clientes": [], "usinas": [], "status_ucs": {}, "atualizado": datetime.now().isoformat()})

    server = HTTPServer(("localhost", PORT), AdminHandler)

    print("=" * 55)
    print("  🌟 Servidor Admin — Luzi Energia")
    print("=" * 55)
    print(f"  Acesse: http://localhost:{PORT}/admin.html")
    print(f"  Pasta:  {PORTAL_DIR}")
    print(f"  Git:    {GIT_ROOT}")
    print()
    print("  Qualquer mudança no painel é salva automaticamente")
    print("  e publicada no site em ~30 segundos.")
    print()
    print("  Pressione Ctrl+C para parar.")
    print("=" * 55)

    # Abre o navegador automaticamente após 1 segundo
    def abrir_navegador():
        time.sleep(1)
        webbrowser.open(f"http://localhost:{PORT}/admin.html")
    threading.Thread(target=abrir_navegador, daemon=True).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n\n  🛑 Servidor parado.")


if __name__ == "__main__":
    iniciar()
