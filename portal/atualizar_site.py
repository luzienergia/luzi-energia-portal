"""
atualizar_site.py — Atualiza data.json e publica no GitHub/Netlify
====================================================================
Este script deve ser chamado toda vez que uma fatura for processada:
  python3 atualizar_site.py

Ele lê o status atual das UCs (gerado pelo pipeline de faturas),
atualiza o data.json na pasta portal/ e faz git push para o
repositório configurado abaixo.

Pré-requisitos:
  1. Repositório no GitHub criado e clonado
  2. Netlify conectado ao repositório (auto-deploy on push)
  3. Configurar GIT_REPO_PATH abaixo
"""

import json, os, subprocess
from pathlib import Path
from datetime import datetime

# ─── CONFIGURAÇÃO ────────────────────────────────────────────────────────────
# Caminho da pasta do repositório GitHub (onde fica o portal/)
GIT_REPO_PATH = Path(__file__).parent.parent  # ajuste se necessário
PORTAL_DIR    = Path(__file__).parent
DATA_JSON     = PORTAL_DIR / "data.json"
STATUS_JSON   = PORTAL_DIR / "status_ucs.json"  # gerado pelo pipeline

# ─── CARREGAR DADOS EXISTENTES ────────────────────────────────────────────────
def carregar_data():
    if DATA_JSON.exists():
        with open(DATA_JSON, encoding="utf-8") as f:
            return json.load(f)
    # Fallback: dados base
    return {"clientes":[], "usinas":[], "status_ucs":{}}

# ─── ATUALIZAR STATUS DAS UCS ────────────────────────────────────────────────
def atualizar_status(data: dict, status_ucs: dict) -> dict:
    data["status_ucs"] = status_ucs
    data["atualizado"]  = datetime.now().isoformat()
    return data

# ─── SALVAR E PUBLICAR ───────────────────────────────────────────────────────
def publicar(data: dict):
    # Salva data.json
    with open(DATA_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"✅ data.json salvo em {DATA_JSON}")

    # Git add + commit + push
    try:
        subprocess.run(["git", "-C", str(GIT_REPO_PATH), "add", "portal/data.json"], check=True)
        msg = f"[auto] Atualiza data.json — {datetime.now().strftime('%d/%m/%Y %H:%M')}"
        subprocess.run(["git", "-C", str(GIT_REPO_PATH), "commit", "-m", msg], check=True)
        subprocess.run(["git", "-C", str(GIT_REPO_PATH), "push"], check=True)
        print("🚀 Publicado no GitHub! Netlify atualizará em ~30 segundos.")
    except subprocess.CalledProcessError as e:
        print(f"⚠️  Git push falhou: {e}")
        print("   O data.json foi salvo localmente. Faça push manualmente.")

# ─── INTERFACE PÚBLICA ───────────────────────────────────────────────────────
def atualizar_e_publicar(status_ucs: dict | None = None):
    """
    Chame esta função passando o dict de status das UCs.
    Exemplo de status_ucs:
    {
      "70296501229": {
        "fatura_chegou": True,
        "ts_fatura": "2026-07-10T08:00:00",
        "boleto_emitido": True,
        "ts_boleto": "2026-07-10T08:05:00",
        "png_gerado": True,
        "ts_png": "2026-07-10T08:05:30",
        "wpp_enviado": True,
        "ts_wpp": "2026-07-10T08:06:00",
        "pago": False,
        "ts_pago": None,
        "fatura": {
          "mes": "06/2026",
          "valor": 1030.57,
          "venc": "2026-07-10",
          "linha": "00000.00000..."
        }
      }
    }
    """
    data = carregar_data()
    if status_ucs:
        data = atualizar_status(data, status_ucs)
    publicar(data)


if __name__ == "__main__":
    # Teste rápido: carrega status_ucs.json se existir
    if STATUS_JSON.exists():
        with open(STATUS_JSON, encoding="utf-8") as f:
            status = json.load(f)
        atualizar_e_publicar(status)
    else:
        print("ℹ️  Nenhum status_ucs.json encontrado. Publicando data.json atual...")
        atualizar_e_publicar()
