#!/usr/bin/env python3
"""
gerar_geracao_data.py — Gera portal/geracao_data.json a partir de historico_geracao.json
=========================================================================================
Chamado após cada coleta de geração (horária ou diária) para atualizar os dados
do gráfico no admin portal.

Uso:
  python3 Inversores/gerar_geracao_data.py
"""

import json
from datetime import datetime, date, timedelta
from pathlib import Path

BASE_DIR    = Path(__file__).parent
HIST_FILE   = BASE_DIR / "historico_geracao.json"
PORTAL_DIR  = BASE_DIR.parent / "portal"
OUTPUT_FILE = PORTAL_DIR / "geracao_data.json"

USINAS_CONFIG = {
    "cartorio": {"nome": "Cartório",   "cor": "#3b82f6", "cor_fundo": "rgba(59,130,246,.18)"},
    "escola":   {"nome": "Escola",     "cor": "#f59e0b", "cor_fundo": "rgba(245,158,11,.18)"},
    "gama_1":   {"nome": "Gama SAJ",   "cor": "#10b981", "cor_fundo": "rgba(16,185,129,.18)"},
    "gama_2":   {"nome": "Gama Sungrow","cor": "#8b5cf6","cor_fundo": "rgba(139,92,246,.18)"},
}


def load_historico() -> dict:
    if not HIST_FILE.exists():
        return {}
    with open(HIST_FILE, encoding="utf-8") as f:
        return json.load(f)


def build_geracao_data() -> dict:
    hist = load_historico()
    hoje = date.today().isoformat()

    usinas_out = {}
    hoje_totals = {}

    for usina_id, cfg in USINAS_CONFIG.items():
        dados_raw = hist.get(usina_id, {})
        # Ordena por data
        dados = {k: round(float(v), 3) for k, v in sorted(dados_raw.items()) if v is not None}

        hoje_kwh = dados.get(hoje, 0.0)
        hoje_totals[usina_id] = hoje_kwh

        # Total acumulado
        total_kwh = round(sum(dados.values()), 3)

        # Médias
        n = len(dados)
        media_diaria = round(total_kwh / n, 3) if n > 0 else 0.0

        usinas_out[usina_id] = {
            **cfg,
            "historico": dados,
            "hoje_kwh": hoje_kwh,
            "total_kwh": total_kwh,
            "media_diaria_kwh": media_diaria,
            "dias_registrados": n,
        }

    # Total geral hoje
    total_hoje = round(sum(hoje_totals.values()), 3)

    resultado = {
        "atualizado_em": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "hoje": hoje,
        "total_hoje_kwh": total_hoje,
        "usinas": usinas_out,
    }

    PORTAL_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(resultado, f, indent=2, ensure_ascii=False)

    print(f"✅ {OUTPUT_FILE} gerado | hoje={hoje} | total={total_hoje:.1f} kWh")
    for uid, v in usinas_out.items():
        print(f"   {v['nome']:<14}: hoje={v['hoje_kwh']:.2f} kWh | total={v['total_kwh']:.1f} kWh | {v['dias_registrados']} dias")

    return resultado


if __name__ == "__main__":
    build_geracao_data()
