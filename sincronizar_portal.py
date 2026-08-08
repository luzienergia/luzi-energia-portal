#!/usr/bin/env python3
"""
sincronizar_portal.py — Sincroniza data.json → portal/data.json e faz git push.
Chamado automaticamente após cada boleto emitido pelo Sicredi.
Também pode ser rodado manualmente:
  python3 "/Users/luiz/Claude/Projects/Sistema Luzi Energia/sincronizar_portal.py"
"""

import json
import os
import subprocess
from datetime import date, datetime
from pathlib import Path

_BASE         = Path(__file__).parent
DATA_FILE     = _BASE / "data.json"           # boletos Sicredi (flat list)
PORTAL_FILE   = _BASE / "portal" / "data.json"  # site (dict por CPF)
VENC_FILE     = _BASE / "vencimentos_faturas.json"
CLIENTES_FILE = _BASE / "clientes.json"

# Mapeamento fixo: nome_cliente → CPF/CNPJ (doc), desconto_pct
CLIENTES_MAP = {
    "Cartório":     {"doc": "02790574000136", "uc": "70296501229", "desconto": 15},
    "Casa Leandro": {"doc": "80372422187",    "uc": "365716101232", "desconto": 20},
    "Casa Neneto":  {"doc": "62432594000167", "uc": "77762501286",  "desconto": 20},
    "Escola":       {"doc": "50802328000108", "uc": "73940201205",  "desconto": 20},
    "Firma Marrula":{"doc": "70182543102",    "uc": "430857301280", "desconto": 20},
    "Apto 100":     {"doc": "03774987181",    "uc": "371372701262", "desconto": 0},
    "Térreo":       {"doc": "03774987181",    "uc": "79163601288",  "desconto": 20},
}
# Inverso: doc → nome
DOC_MAP = {v["doc"]: k for k, v in CLIENTES_MAP.items()}


def _calcular_status(venc_str: str) -> str:
    """Retorna 'pago', 'vencido' ou 'em_aberto' com base na data de vencimento."""
    try:
        venc = date.fromisoformat(venc_str)
        hoje = date.today()
        if venc < hoje:
            return "vencido"
        return "em_aberto"
    except Exception:
        return "em_aberto"


def _ref_from_mes(mes: str) -> str:
    """'08/2026' → 'ago/26'"""
    meses = ["jan","fev","mar","abr","mai","jun","jul","ago","set","out","nov","dez"]
    try:
        m, a = mes.split("/")
        return f"{meses[int(m)-1]}/{a[2:]}"
    except Exception:
        return mes


def sincronizar():
    """Lê vencimentos_faturas.json + data.json e atualiza portal/data.json."""
    # Carregar portal/data.json existente
    if PORTAL_FILE.exists():
        with open(PORTAL_FILE, encoding="utf-8") as f:
            portal = json.load(f)
    else:
        portal = {}

    if "faturas" not in portal or not isinstance(portal["faturas"], dict):
        portal["faturas"] = {}

    # Carregar boletos Sicredi (para pegar linhaDigitavel, nossoNumero)
    # Indexados por (doc_limpo, mes_referencia) → boleto
    sicredi_boletos = {}   # (doc, "MM/YYYY") → boleto dict
    if DATA_FILE.exists():
        with open(DATA_FILE, encoding="utf-8") as f:
            root_data = json.load(f)
        for b in root_data.get("faturas", []) + root_data.get("boletos", []):
            # 1) Preferir metadado explícito _doc/_mesReferencia (salvo pelo emitir_boleto_sicredi.py)
            doc = str(b.get("_doc") or "").strip()
            mes = str(b.get("_mesReferencia") or "").strip()

            # 2) Fallback: doc vem de documento/cpfCnpj do payload
            if not doc:
                doc = str(b.get("documento") or b.get("cpfCnpj") or "")
                doc = doc.replace(".", "").replace("-", "").replace("/", "")

            # 3) Fallback: inferir doc pelo nomePagador
            if not doc:
                nome_pag = b.get("nomePagador", "").lower()
                for nome_cl, info in CLIENTES_MAP.items():
                    if nome_cl.lower() in nome_pag or nome_pag in nome_cl.lower():
                        doc = info["doc"].replace(".", "").replace("-", "").replace("/", "")
                        break

            # 4) Fallback: inferir mes pela dataVencimento
            if not mes:
                venc_str = b.get("dataVencimento", "")
                try:
                    y, m, _ = venc_str.split("-")
                    mes = f"{m}/{y}"
                except Exception:
                    pass

            if doc and mes:
                # Guardar o mais recente (emitidoEm maior)
                key = (doc, mes)
                prev = sicredi_boletos.get(key)
                if prev is None or b.get("emitidoEm", "") >= prev.get("emitidoEm", ""):
                    sicredi_boletos[key] = b

    # Carregar vencimentos atuais
    vencimentos = []
    if VENC_FILE.exists():
        with open(VENC_FILE, encoding="utf-8") as f:
            v = json.load(f)
        vencimentos = v.get("clientes", [])

    # Atualizar portal/data.json com vencimentos atuais
    for v in vencimentos:
        nome = v.get("nome", "")
        if nome not in CLIENTES_MAP:
            continue

        info  = CLIENTES_MAP[nome]
        doc   = info["doc"]
        mes   = v.get("mes_referencia", "")
        venc  = v.get("vencimento", "")
        valor = float(v.get("valor_boleto") or 0)
        desc  = info["desconto"]

        if not mes or not valor:
            continue

        # Calcular semDesc aproximado (desconto sobre toda a base — aproximação)
        # O cálculo exato depende da composição, mas servimos aproximação para display
        sem_desc = round(valor / (1 - desc / 100), 2) if desc > 0 else valor

        # Construir entrada da fatura
        nova_fatura = {
            "mes":     mes,
            "ref":     _ref_from_mes(mes),
            "semDesc": sem_desc,
            "comDesc": valor,
            "venc":    venc,
            "status":  _calcular_status(venc),
        }

        # Adicionar linha digitável do Sicredi se disponível
        # Chave: (doc_limpo, "MM/YYYY")
        doc_limpo = doc.replace(".", "").replace("-", "").replace("/", "")
        boleto_sicredi = sicredi_boletos.get((doc_limpo, mes))
        if boleto_sicredi:
            nova_fatura["linhaDigitavel"] = boleto_sicredi.get("linhaDigitavel", "")
            nova_fatura["nossoNumero"]    = boleto_sicredi.get("nossoNumero", "")
            # Atualizar status com situação real do Sicredi se disponível
            situacao = boleto_sicredi.get("situacao", {})
            if isinstance(situacao, dict):
                sit = situacao.get("situacao", "")
            else:
                sit = str(situacao)
            if sit in ("LIQUIDADO", "PAGO", "LIQUIDADA"):
                nova_fatura["status"] = "pago"
            elif sit in ("BAIXADO", "CANCELADO"):
                nova_fatura["status"] = "cancelado"
            nova_fatura["seuNumero"] = boleto_sicredi.get("seuNumero", "")

        # Inserir/atualizar entrada do cliente
        if doc not in portal["faturas"]:
            portal["faturas"][doc] = {
                "nome":     nome,
                "uc":       info["uc"],
                "doc":      doc,
                "desconto": desc,
                "faturas":  [],
            }

        # Remover entrada do mesmo mês se já existir
        portal["faturas"][doc]["faturas"] = [
            f for f in portal["faturas"][doc]["faturas"]
            if f.get("mes") != mes
        ]
        portal["faturas"][doc]["faturas"].insert(0, nova_fatura)

        # Manter só os últimos 12 meses
        portal["faturas"][doc]["faturas"] = portal["faturas"][doc]["faturas"][:12]

    # Atualizar timestamp
    portal["atualizado"] = datetime.now().isoformat()

    # Copiar usinas e clientes do clientes.json se disponível
    if CLIENTES_FILE.exists():
        with open(CLIENTES_FILE, encoding="utf-8") as f:
            cl = json.load(f)
        portal["usinas"]   = cl.get("usinas", portal.get("usinas", []))
        portal["clientes"] = cl.get("clientes", portal.get("clientes", []))

    # Salvar portal/data.json
    PORTAL_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(PORTAL_FILE, "w", encoding="utf-8") as f:
        json.dump(portal, f, indent=2, ensure_ascii=False)

    print(f"✅ portal/data.json atualizado: {len(portal['faturas'])} clientes")
    return True


def _git(*args, check=True):
    return subprocess.run(
        ["git", "-C", str(_BASE), *args],
        capture_output=True, text=True, check=check
    )


def _limpar_locks_orfaos():
    """Remove arquivos .lock/.bak órfãos dentro de .git (best-effort).

    O diretório do projeto roda sobre um mount que bloqueia delete/rename de
    arquivos já escritos. Isso quebra o mecanismo normal de lockfile do git
    (grava .lock, depois faz rename para o arquivo final): o rename falha,
    o lock fica órfão e todo git subsequente trava. Só é possível limpar
    depois que o usuário aprova via allow_cowork_file_delete; se ainda não
    aprovou, o erro abaixo é ignorado e o publicar() vai falhar de forma
    clara mais adiante.
    """
    git_dir = _BASE / ".git"
    for pattern in ("*.lock", "*.lock.*", "*.lock*bak*", "*.lock.old*"):
        for f in git_dir.rglob(pattern):
            try:
                f.unlink()
            except Exception:
                pass


def publicar():
    """Publica portal/data.json via git push real (commit + push para origin/main).

    Histórico: antes usávamos a API REST do GitHub (api.github.com) para
    evitar o problema de lock do mount, mas api.github.com não é alcançável
    a partir do sandbox (github.com é). git push real funciona desde que
    não existam locks órfãos em .git — ver _limpar_locks_orfaos().
    """
    _limpar_locks_orfaos()

    try:
        _git("add", "portal/data.json")

        status = _git("status", "--porcelain", "--", "portal/data.json").stdout
        if not status.strip():
            print("ℹ️  portal/data.json sem mudanças — nada para publicar.")
            return True

        msg = f"[auto] Atualiza portal/data.json — {datetime.now().strftime('%d/%m/%Y %H:%M')}"
        _git("commit", "-m", msg)
    except subprocess.CalledProcessError as e:
        print(f"⚠️  git add/commit falhou: {e.stderr.strip()[:300]}")
        return False

    # Tenta push; se o remoto avançou (outra execução publicou antes), sincroniza
    # o branch com origin/main SEM tocar na working tree (reset --mixed) e tenta
    # de novo. Só a snapshot de portal/data.json é recriada a cada rodada, então
    # não há conflito real de conteúdo a resolver.
    for tentativa in range(2):
        push = subprocess.run(
            ["git", "-C", str(_BASE), "push", "origin", "main"],
            capture_output=True, text=True
        )
        if push.returncode == 0:
            commit_sha = _git("rev-parse", "--short", "HEAD").stdout.strip()
            print(f"🚀 Site atualizado no GitHub! (commit {commit_sha}) — Netlify deploy em ~30s.")
            return True

        if "rejected" in push.stderr or "fetch first" in push.stderr or "non-fast-forward" in push.stderr:
            try:
                _git("fetch", "origin", "main")
                _git("reset", "--mixed", "origin/main")
                _git("add", "portal/data.json")
                status = _git("status", "--porcelain", "--", "portal/data.json").stdout
                if status.strip():
                    _git("commit", "-m", msg)
                    continue
                else:
                    print("ℹ️  portal/data.json já estava atualizado no remoto.")
                    return True
            except subprocess.CalledProcessError as e:
                print(f"⚠️  Falha ao sincronizar com origin/main: {e.stderr.strip()[:300]}")
                return False
        else:
            print(f"⚠️  git push falhou: {push.stderr.strip()[:300]}")
            return False

    print("⚠️  git push falhou após retry — verifique o repositório manualmente.")
    return False


def sincronizar_e_publicar():
    """Ponto de entrada principal: sincroniza e publica."""
    ok = sincronizar()
    if ok:
        publicar()


if __name__ == "__main__":
    sincronizar_e_publicar()
