"""
btg_auth.py — Módulo de autenticação BTG Empresas
=================================================
Obtém token de acesso usando Client Credentials (sem precisar abrir o navegador).

Como funciona:
  - Envia client_id + client_secret diretamente para o BTG
  - Recebe um token de acesso válido por 24h
  - Salva o token em disco e reutiliza até expirar
"""

from __future__ import annotations

import os
import json
import time
import requests
from dotenv import load_dotenv

# Carrega as credenciais do arquivo .env
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

# ── Configurações ──────────────────────────────────────────
CLIENT_ID     = os.getenv("BTG_CLIENT_ID")
CLIENT_SECRET = os.getenv("BTG_CLIENT_SECRET")
ENVIRONMENT   = os.getenv("BTG_ENVIRONMENT", "sandbox")

if ENVIRONMENT == "production":
    AUTH_BASE = "https://id.btgpactual.com"
else:
    AUTH_BASE = "https://id.sandbox.btgpactual.com"

SCOPES      = "brn:btg:empresas:banking:collections"
TOKENS_FILE = os.path.join(os.path.dirname(__file__), "tokens.json")

# ── Salvar / carregar tokens ───────────────────────────────
def _salvar_tokens(dados: dict):
    dados["salvo_em"] = time.time()
    with open(TOKENS_FILE, "w") as f:
        json.dump(dados, f, indent=2)

def _carregar_tokens() -> dict | None:
    if not os.path.exists(TOKENS_FILE):
        return None
    with open(TOKENS_FILE) as f:
        return json.load(f)

# ── Verificar se o token ainda é válido ───────────────────
def _token_valido(tokens: dict | None) -> bool:
    if not tokens or "access_token" not in tokens:
        return False
    salvo_em   = tokens.get("salvo_em", 0)
    expires_in = tokens.get("expires_in", 86400)
    # Considera inválido 5 minutos antes do vencimento
    return time.time() < (salvo_em + expires_in - 300)

# ── Obter novo token via Client Credentials ───────────────
def _obter_token_novo() -> dict:
    print("🔑 Obtendo token de acesso BTG...")
    resp = requests.post(
        f"{AUTH_BASE}/oauth2/token",
        auth=(CLIENT_ID, CLIENT_SECRET),   # client_secret_basic
        data={
            "grant_type": "client_credentials",
            "scope":      SCOPES,
        },
    )
    if not resp.ok:
        raise RuntimeError(
            f"Erro ao obter token BTG ({resp.status_code}): {resp.text}"
        )
    print("✅ Token obtido com sucesso.")
    return resp.json()

# ── Função principal: retorna um access_token válido ──────
def obter_token() -> str:
    """
    Retorna um access_token pronto para usar na API do BTG.
    Reutiliza o token salvo se ainda for válido; caso contrário, obtém um novo.
    """
    tokens = _carregar_tokens()

    if _token_valido(tokens):
        return tokens["access_token"]

    # Token expirado ou inexistente → solicita novo
    novos = _obter_token_novo()
    _salvar_tokens(novos)
    return novos["access_token"]
