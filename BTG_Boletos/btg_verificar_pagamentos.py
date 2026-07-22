"""
btg_verificar_pagamentos.py — Verifica status de pagamento de todos os boletos em aberto
==========================================================================================
Roda a cada hora (via tarefa agendada). Para cada boleto em aberto no data.json,
consulta o BTG e atualiza se foi pago. Depois publica automaticamente no site.

Uso:
  python3 btg_verificar_pagamentos.py
"""

from __future__ import annotations
import os, sys, json, requests
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

# ─── Caminhos ─────────────────────────────────────────────────────────────────
BASE_DIR   = Path(__file__).parent.parent
PORTAL_DIR = BASE_DIR / "portal"
DATA_JSON  = PORTAL_DIR / "data.json"

# ─── BTG Config ───────────────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent))
load_dotenv(Path(__file__).parent / ".env")

from btg_auth import obter_token

ENVIRONMENT = os.getenv("BTG_ENVIRONMENT", "sandbox")
COMPANY_ID  = os.getenv("BTG_COMPANY_ID")

if ENVIRONMENT == "production":
    API_BASE = "https://api.empresas.btgpactual.com"
else:
    API_BASE = "https://api.sandbox.empresas.btgpactual.com"

# ─── Status BTG → status interno ──────────────────────────────────────────────
# Os status que o BTG retorna para a cobrança (boleto)
STATUS_PAGO = {"PAID", "SETTLED", "PAGO", "LIQUIDADO"}

# ─── Verificar um boleto específico ───────────────────────────────────────────
def verificar_boleto(boleto_id: str) -> dict | None:
    """
    Consulta o BTG e retorna os dados do boleto.
    Retorna None se houver erro.
    """
    try:
        token = obter_token()
        url = f"{API_BASE}/{COMPANY_ID}/banking/collections/{boleto_id}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type":  "application/json",
        }
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.ok:
            return resp.json()
        else:
            print(f"  ⚠️  BTG retornou {resp.status_code} para boleto {boleto_id}: {resp.text[:100]}")
            return None
    except Exception as e:
        print(f"  ⚠️  Erro ao consultar BTG: {e}")
        return None

# ─── Verificar todos os boletos em aberto ─────────────────────────────────────
def verificar_todos() -> int:
    """
    Lê o data.json, verifica cada boleto em aberto no BTG,
    atualiza o status e salva de volta.
    Retorna o número de boletos marcados como pagos.
    """
    if not DATA_JSON.exists():
        print("❌ data.json não encontrado. Execute o pipeline de faturas primeiro.")
        return 0

    with open(DATA_JSON, encoding="utf-8") as f:
        data = json.load(f)

    status_ucs: dict = data.get("status_ucs", {})
    pagos_agora = 0
    total_verificados = 0

    print(f"\n🔍 Verificando pagamentos — {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print(f"   {len(status_ucs)} UCs com status registrado")

    for uc, st in status_ucs.items():
        # Pula UCs que já foram marcadas como pagas
        if st.get("pago"):
            continue

        boleto_id = st.get("boleto_id")
        if not boleto_id:
            continue  # Boleto ainda não emitido para essa UC

        nome = st.get("fatura", {}).get("cliente", uc)
        print(f"\n  📄 {nome} (UC {uc}) — boleto {boleto_id[:12]}...")

        dados_btg = verificar_boleto(boleto_id)
        if not dados_btg:
            print(f"     ↳ Sem resposta do BTG")
            continue

        total_verificados += 1

        # Extrai status do BTG (pode variar por versão da API)
        status_btg = (
            dados_btg.get("status") or
            dados_btg.get("collectionStatus") or
            dados_btg.get("situacao") or
            ""
        ).upper()

        print(f"     ↳ Status BTG: {status_btg}")

        if status_btg in STATUS_PAGO:
            # Marca como pago
            ts_pago = (
                dados_btg.get("paymentDate") or
                dados_btg.get("dataPagamento") or
                datetime.now().isoformat()
            )
            st["pago"]    = True
            st["ts_pago"] = ts_pago
            pagos_agora  += 1
            print(f"     ✅ PAGO em {ts_pago}")
        elif status_btg in {"EXPIRED", "EXPIRADO", "CANCELLED", "CANCELADO"}:
            # Marca como expirado (para visualização no painel)
            st["expirado"] = True
            print(f"     🔴 Boleto expirado/cancelado")

    # Sincroniza status de pagamento em data.faturas (portal admin)
    if pagos_agora > 0:
        sincronizar_faturas_db(data, status_ucs)

    # Atualiza data.json
    data["status_ucs"]  = status_ucs
    data["atualizado"]  = datetime.now().isoformat()
    data["ultima_verificacao_btg"] = datetime.now().isoformat()

    with open(DATA_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\n✅ Verificação concluída: {total_verificados} consultados, {pagos_agora} marcados como pagos")
    return pagos_agora


# ─── Sincronizar status de pagamento em data.faturas ──────────────────────────
def sincronizar_faturas_db(data: dict, status_ucs: dict):
    """
    Quando um boleto é marcado como pago no BTG, atualiza o status
    na estrutura data['faturas'] para que o portal admin reflita corretamente.
    """
    faturas_db = data.get("faturas", {})
    if not faturas_db:
        return

    # Mapeia UC → doc (para encontrar a entrada correta em faturas_db)
    uc_para_doc: dict[str, str] = {}
    for doc_key, cli in faturas_db.items():
        uc = cli.get("uc", "")
        if uc:
            uc_para_doc[uc] = doc_key

    atualizados = 0
    for uc, st in status_ucs.items():
        if not st.get("pago"):
            continue  # Não pago — nada a fazer

        doc_key = uc_para_doc.get(uc)
        if not doc_key or doc_key not in faturas_db:
            continue

        cli_faturas = faturas_db[doc_key].get("faturas", [])
        # Procura a fatura em aberto mais recente para este UC e marca como paga
        # (a primeira entrada com status != 'pago' e cujo vencimento corresponde ao boleto atual)
        boleto_venc = st.get("fatura", {}).get("venc", "")
        for fat in cli_faturas:
            if fat.get("status") == "vencer" and (not boleto_venc or fat.get("venc") == boleto_venc):
                fat["status"] = "pago"
                ts_pago = st.get("ts_pago", "")
                if ts_pago:
                    fat["ts_pago"] = ts_pago
                atualizados += 1
                print(f"  ✅ {doc_key} — {fat.get('mes', '?')} marcado como PAGO em data.faturas")
                break  # Apenas uma fatura por boleto

    data["faturas"] = faturas_db
    if atualizados:
        print(f"  📋 {atualizados} fatura(s) sincronizada(s) no portal admin")


# ─── Publicar no site após verificação ────────────────────────────────────────
def verificar_e_publicar():
    """Verifica pagamentos e publica no site se houver mudança."""
    pagos = verificar_todos()

    # Publica no site (git push → Netlify)
    try:
        sys.path.insert(0, str(PORTAL_DIR))
        from atualizar_site import publicar
        with open(DATA_JSON, encoding="utf-8") as f:
            data = json.load(f)
        publicar(data)
    except Exception as e:
        print(f"⚠️  Não foi possível publicar no site: {e}")
        print("   O data.json foi atualizado localmente.")

    return pagos


if __name__ == "__main__":
    verificar_e_publicar()
