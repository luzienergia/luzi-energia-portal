"""
emitir_boleto.py — Emite boletos no BTG Empresas automaticamente
================================================================
Uso pelo terminal:
  python emitir_boleto.py

Ou chamado por outro script (ex: rotina de faturas).
"""

import os
import uuid
import json
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv
from btg_auth import obter_token

# Carrega configurações do arquivo .env
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

ENVIRONMENT  = os.getenv("BTG_ENVIRONMENT", "sandbox")
COMPANY_ID   = os.getenv("BTG_COMPANY_ID")    # CNPJ da Luzi Energia
BRANCH_CODE  = os.getenv("BTG_BRANCH_CODE", "50")
ACCOUNT_NUM  = os.getenv("BTG_ACCOUNT_NUMBER")

if ENVIRONMENT == "production":
    API_BASE = "https://api.empresas.btgpactual.com"
else:
    API_BASE = "https://api.sandbox.empresas.btgpactual.com"


def emitir_boleto(
    nome_cliente: str,
    cpf_cnpj_cliente: str,
    tipo_pessoa: str,        # "F" = pessoa física, "J" = empresa/CNPJ
    valor: float,            # valor em reais, ex: 1030.57
    data_vencimento: str,    # formato "AAAA-MM-DD", ex: "2026-08-10"
    descricao: str = "",
    dias_apos_vencimento: int = 30,  # quantos dias ainda aceita pagamento
) -> dict:
    """
    Emite um boleto no BTG e retorna as informações para pagamento.

    Retorna dicionário com:
      - linha_digitavel : código para pagar no banco/app
      - codigo_barras   : código de barras
      - boleto_id       : ID interno do BTG
      - vencimento      : data de vencimento
      - valor           : valor em reais
    """

    # Valida conta BTG preenchida
    if not ACCOUNT_NUM or ACCOUNT_NUM == "PREENCHER_AQUI":
        raise ValueError(
            "⚠️  Preencha o BTG_ACCOUNT_NUMBER no arquivo .env\n"
            "    (Veja no portal BTG: Conta Digital → Dados da conta)"
        )

    # Calcula a data limite para pagamento (após o vencimento)
    dt_venc = datetime.strptime(data_vencimento, "%Y-%m-%d")
    dt_limite = dt_venc + timedelta(days=dias_apos_vencimento)

    # Monta o payload do boleto
    payload = {
        "type":       "BANKSLIP",          # boleto simples (sem QR code Pix)
        "amount":     valor,
        "dueDate":    data_vencimento,
        "overDueDate": dt_limite.strftime("%Y-%m-%d"),
        "description": descricao or f"Energia solar – {nome_cliente}",

        # Quem paga
        "payer": {
            "name":       nome_cliente,
            "taxId":      cpf_cnpj_cliente.replace(".", "").replace("/", "").replace("-", ""),
            "personType": tipo_pessoa,    # "F" ou "J"
        },

        # Conta da Luzi Energia que recebe (nova API: só number + branch)
        "account": {
            "number": ACCOUNT_NUM,
            "branch": BRANCH_CODE.lstrip("0") or "50",  # "0050" → "50"
        },

        # Detalhes do boleto (documentNumber obrigatório na nova API)
        "detail": {
            "documentNumber": f"LUZ-{nome_cliente[:4].upper()}-{datetime.now().strftime('%m%y')}",
        },
    }

    # Obtém token de autenticação (faz login se necessário)
    token = obter_token()

    url = f"{API_BASE}/{COMPANY_ID}/banking/collections"

    headers = {
        "Authorization":    f"Bearer {token}",
        "Content-Type":     "application/json",
        "X-Idempotency-Key": str(uuid.uuid4()),   # evita duplicatas
    }

    print(f"📤 Emitindo boleto para {nome_cliente} — R$ {valor:.2f} ...")
    resp = requests.post(url, headers=headers, json=payload)

    if not resp.ok:
        print(f"❌ Erro {resp.status_code}: {resp.text}")
        resp.raise_for_status()

    dados = resp.json()

    resultado = {
        "boleto_id":      dados.get("collectionId", ""),
        "linha_digitavel": dados.get("detail", {}).get("digitableLine", ""),
        "codigo_barras":  dados.get("detail", {}).get("barCode", ""),
        "vencimento":     data_vencimento,
        "valor":          valor,
        "cliente":        nome_cliente,
        "ambiente":       ENVIRONMENT,
    }

    print(f"✅ Boleto emitido com sucesso!")
    print(f"   Linha digitável: {resultado['linha_digitavel']}")
    print(f"   Vencimento: {data_vencimento}  |  Valor: R$ {valor:.2f}")

    return resultado


def salvar_boleto_no_json(resultado: dict, arquivo_json: str):
    """Registra o boleto emitido no vencimentos_faturas.json"""
    if not os.path.exists(arquivo_json):
        print(f"⚠️  Arquivo {arquivo_json} não encontrado.")
        return

    with open(arquivo_json, "r", encoding="utf-8") as f:
        dados = json.load(f)

    # Encontra o cliente e adiciona os dados do boleto
    for cliente in dados.get("clientes", []):
        if cliente["nome"] == resultado["cliente"]:
            cliente["boleto_id"]       = resultado["boleto_id"]
            cliente["linha_digitavel"] = resultado["linha_digitavel"]
            cliente["boleto_emitido_em"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            break

    with open(arquivo_json, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)

    print(f"💾 Boleto salvo em {arquivo_json}")


def registrar_em_data_json(
    resultado: dict,
    doc: str,          # CPF/CNPJ do cliente (chave em data.json.faturas)
    uc: str,           # UC do cliente (chave em data.json.status_ucs)
    mes: str,          # Ex: "07/2026"
    ref: str,          # Ex: "jul/26"
    sem_desc: float,   # Valor sem desconto (tarifa cheia)
    com_desc: float,   # Valor cobrado (com desconto Luzi)
    desconto: int,     # Percentual de desconto (ex: 15 ou 20)
    nome_cliente: str,
    data_json_path: str = None,
):
    """
    Registra um boleto recém-emitido em data.json:
    - data.json.status_ucs[uc]  → boleto_id, linha_digitavel, status, fatura
    - data.json.faturas[doc]    → prepend nova entrada no histórico de faturas

    Chamada logo após emitir_boleto() para manter o portal admin e o portal
    do cliente sempre sincronizados automaticamente.
    """
    from pathlib import Path

    if data_json_path is None:
        data_json_path = str(
            Path(__file__).parent.parent / "portal" / "data.json"
        )

    if not os.path.exists(data_json_path):
        print(f"⚠️  data.json não encontrado em {data_json_path}")
        return

    with open(data_json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    venc    = resultado["vencimento"]
    boleto_id = resultado["boleto_id"]
    linha   = resultado.get("linha_digitavel", "")

    # ── Atualiza status_ucs ──────────────────────────────────
    status_ucs = data.get("status_ucs", {})
    status_ucs[uc] = {
        "boleto_id":       boleto_id,
        "pago":            False,
        "linha_digitavel": linha,
        "emitido_em":      datetime.now().isoformat(),
        "fatura": {
            "cliente": nome_cliente,
            "venc":    venc,
            "valor":   com_desc,
            "mes":     mes,
            "ref":     ref,
            "doc":     doc,
        }
    }
    data["status_ucs"] = status_ucs

    # ── Atualiza faturas[doc] ────────────────────────────────
    faturas_db = data.get("faturas", {})
    nova_entrada = {
        "mes":      mes,
        "ref":      ref,
        "semDesc":  round(sem_desc, 2),
        "comDesc":  round(com_desc, 2),
        "venc":     venc,
        "status":   "vencer",
        "linha":    linha,
        "boleto_id": boleto_id,
    }

    if doc in faturas_db:
        cli_fat = faturas_db[doc]
        # Remove entrada com mesmo mês se já existir (re-emissão)
        cli_fat["faturas"] = [f for f in cli_fat.get("faturas", []) if f.get("mes") != mes]
        cli_fat["faturas"].insert(0, nova_entrada)  # mais recente primeiro
    else:
        # Cria entrada nova para este cliente
        faturas_db[doc] = {
            "nome":     nome_cliente,
            "uc":       uc,
            "doc":      doc,
            "desconto": desconto,
            "faturas":  [nova_entrada],
        }

    data["faturas"]    = faturas_db
    data["atualizado"] = datetime.now().isoformat()

    with open(data_json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"✅ data.json atualizado: {nome_cliente} {mes} registrado (UC {uc})")


# ── Exemplo de uso direto ──────────────────────────────────
if __name__ == "__main__":
    # Exemplo: emite boleto para o Cartório
    resultado = emitir_boleto(
        nome_cliente      = "Cartório",
        cpf_cnpj_cliente  = "PREENCHER_CNPJ_CARTORIO",   # ← preencha
        tipo_pessoa       = "J",
        valor             = 1030.57,
        data_vencimento   = "2026-07-10",
        descricao         = "Energia solar Jul/2026 – Cartório",
    )

    # Salva no arquivo de faturas
    json_faturas = os.path.join(
        os.path.dirname(__file__), "..", "vencimentos_faturas.json"
    )
    salvar_boleto_no_json(resultado, json_faturas)
