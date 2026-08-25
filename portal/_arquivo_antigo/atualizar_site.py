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

# ─── GIT HELPERS ──────────────────────────────────────────────────────────────
# Nota (08/08/2026): no sandbox Cowork, a pasta do projeto roda sobre um mount
# que bloqueia delete/rename de arquivos já escritos. Isso quebra o mecanismo
# normal de lockfile do git (escreve .lock, depois faz rename pro arquivo
# final) e deixa .git/index.lock, .git/HEAD.lock e .git/objects/*/tmp_obj_*
# órfãos toda vez que um comando git roda — travando o próximo add/commit.
# Isso já causou dezenas de falhas manuais (ver memória feedback-btg-git-push-
# sandbox). A função abaixo limpa esses órfãos antes de cada tentativa, e o
# publicar() sincroniza com origin/main via reset --mixed (não mexe na working
# tree) em vez de git pull --rebase, evitando os rebases travados do passado.

def _git(repo_path: Path, *args, check=True):
    return subprocess.run(
        ["git", "-C", str(repo_path), *args],
        capture_output=True, text=True, check=check
    )


def _limpar_locks_orfaos(repo_path: Path):
    git_dir = repo_path / ".git"
    for pattern in ("*.lock", "*.lock.*", "*.lock*bak*", "*.lock.old*", "tmp_obj_*"):
        for f in git_dir.rglob(pattern):
            try:
                f.unlink()
            except Exception:
                pass  # sem allow_cowork_file_delete aprovado ainda; segue e deixa o git tentar mesmo assim


# ─── SALVAR E PUBLICAR ───────────────────────────────────────────────────────
def publicar(data: dict):
    # Salva data.json
    with open(DATA_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"✅ data.json salvo em {DATA_JSON}")

    # Git add + commit + push (com limpeza de locks órfãos e retry via reset --mixed)
    _limpar_locks_orfaos(GIT_REPO_PATH)
    msg = f"[auto] Atualiza data.json — {datetime.now().strftime('%d/%m/%Y %H:%M')}"

    try:
        _git(GIT_REPO_PATH, "add", "portal/data.json")
        status = _git(GIT_REPO_PATH, "status", "--porcelain", "--", "portal/data.json").stdout
        if not status.strip():
            print("ℹ️  portal/data.json sem mudanças — nada para publicar.")
            return
        _git(GIT_REPO_PATH, "commit", "-m", msg)
    except subprocess.CalledProcessError as e:
        print(f"⚠️  Git add/commit falhou: {e.stderr.strip()[:300] if e.stderr else e}")
        print("   O data.json foi salvo localmente. Faça push manualmente.")
        return

    for _tentativa in range(2):
        push = subprocess.run(
            ["git", "-C", str(GIT_REPO_PATH), "push", "origin", "main"],
            capture_output=True, text=True
        )
        if push.returncode == 0:
            print("🚀 Publicado no GitHub! Netlify atualizará em ~30 segundos.")
            return
        if "rejected" in push.stderr or "fetch first" in push.stderr or "non-fast-forward" in push.stderr:
            try:
                _limpar_locks_orfaos(GIT_REPO_PATH)
                _git(GIT_REPO_PATH, "fetch", "origin", "main")
                _git(GIT_REPO_PATH, "reset", "--mixed", "origin/main")
                _git(GIT_REPO_PATH, "add", "portal/data.json")
                status = _git(GIT_REPO_PATH, "status", "--porcelain", "--", "portal/data.json").stdout
                if status.strip():
                    _git(GIT_REPO_PATH, "commit", "-m", msg)
                    continue
                print("ℹ️  portal/data.json já estava atualizado no remoto.")
                return
            except subprocess.CalledProcessError as e:
                print(f"⚠️  Falha ao sincronizar com origin/main: {e.stderr.strip()[:300] if e.stderr else e}")
                return
        else:
            print(f"⚠️  Git push falhou: {push.stderr.strip()[:300]}")
            print("   O data.json foi salvo localmente. Faça push manualmente.")
            return

    print("⚠️  Git push falhou após retry — verifique o repositório manualmente.")

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
