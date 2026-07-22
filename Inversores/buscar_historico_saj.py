#!/usr/bin/env python3
"""
buscar_historico_saj.py — Preenche historico_geracao.json com dados históricos SAJ
====================================================================================
Usa a API SAJ (elekeeper) para buscar geração diária dos últimos 12 meses
para as usinas Cartório (cartorio) e Gama 1 (gama_1).

Uso:
  python3 Inversores/buscar_historico_saj.py
  python3 Inversores/buscar_historico_saj.py --meses 6
"""

import json
import os
import sys
import time
import argparse
from datetime import date, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv

BASE_DIR  = Path(__file__).parent
HIST_FILE = BASE_DIR / "historico_geracao.json"
load_dotenv(BASE_DIR / ".env")

SAJ_BASE     = "https://pro.saj-electric.com"
SAJ_USERNAME = os.getenv("SAJ_USERNAME", "")
SAJ_PASSWORD = os.getenv("SAJ_PASSWORD", "")

# Mapeamento plantUID → usina_id no nosso sistema
# Descubra o plantUID fazendo login e vendo as chamadas de rede em /plant/list
PLANT_MAP = {
    # "PLANT_UID_CARTORIO": "cartorio",
    # "PLANT_UID_GAMA":     "gama_1",
}


def saj_login(session: requests.Session) -> bool:
    url = f"{SAJ_BASE}/monitor/site/login"
    resp = session.post(url, json={
        "username": SAJ_USERNAME,
        "password": SAJ_PASSWORD,
        "languageCode": "pt_BR",
    }, timeout=20)
    data = resp.json()
    if data.get("result") == 1:
        print(f"✅ Login SAJ OK — usuário: {SAJ_USERNAME}")
        return True
    print(f"❌ Login SAJ falhou: {data}")
    return False


def saj_plant_list(session: requests.Session) -> list:
    url = f"{SAJ_BASE}/monitor/site/getPlantList"
    resp = session.post(url, json={"pageNo": 1, "pageSize": 100}, timeout=20)
    data = resp.json()
    plants = data.get("data", {}).get("records") or data.get("data") or []
    return plants


def saj_daily_energy(session: requests.Session, plant_uid: str,
                     year: int, month: int) -> dict[str, float]:
    """Retorna {YYYY-MM-DD: kWh} para o mês/ano dado."""
    url = f"{SAJ_BASE}/monitor/site/getPlantDetailChart"
    payload = {
        "plantUid":  plant_uid,
        "type":      "2",        # 2 = mês (detalhe diário)
        "date":      f"{year}-{month:02d}",
    }
    resp = session.post(url, json=payload, timeout=20)
    try:
        data = resp.json()
    except Exception:
        return {}

    # Estrutura esperada: data.chartData ou data.data.chartData
    chart = (data.get("data") or {}).get("chartData") or data.get("chartData") or []
    result = {}
    for entry in chart:
        dt  = entry.get("date") or entry.get("time") or ""
        kwh = entry.get("value") or entry.get("energy") or 0
        if dt and kwh is not None:
            try:
                result[str(dt)[:10]] = float(kwh)
            except (ValueError, TypeError):
                pass
    return result


def load_historico() -> dict:
    if HIST_FILE.exists():
        with open(HIST_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_historico(hist: dict):
    with open(HIST_FILE, "w", encoding="utf-8") as f:
        json.dump(hist, f, indent=2, ensure_ascii=False)
    print(f"✅ {HIST_FILE} atualizado")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--meses", type=int, default=12,
                        help="Quantos meses para trás buscar (padrão: 12)")
    args = parser.parse_args()

    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})

    if not saj_login(session):
        sys.exit(1)

    # Se PLANT_MAP estiver vazio, listar plantas e mostrar
    if not PLANT_MAP:
        plants = saj_plant_list(session)
        if not plants:
            print("⚠️  Nenhuma usina encontrada na conta SAJ.")
            print("    Verifique o endpoint de listagem.")
        else:
            print("\n=== Usinas encontradas na conta SAJ ===")
            for p in plants:
                uid   = p.get("plantUid") or p.get("uid") or p.get("id")
                nome  = p.get("plantName") or p.get("name") or "?"
                print(f"  uid={uid!r}  nome={nome!r}")
            print()
            print("👉 Adicione os UIDs ao PLANT_MAP no topo deste script e rode novamente.")
        return

    hist = load_historico()
    hoje = date.today()

    for plant_uid, usina_id in PLANT_MAP.items():
        print(f"\n📡 Buscando histórico de {usina_id} (UID={plant_uid})...")
        if usina_id not in hist:
            hist[usina_id] = {}

        novos = 0
        # Itera meses do mais antigo ao mais recente
        for m in range(args.meses - 1, -1, -1):
            # Calcula ano/mês
            target = date(hoje.year, hoje.month, 1) - timedelta(days=m * 30)
            y, mo  = target.year, target.month

            print(f"  {y}-{mo:02d}...", end=" ", flush=True)
            dados = saj_daily_energy(session, plant_uid, y, mo)
            print(f"{len(dados)} dias")

            for dt, kwh in dados.items():
                if kwh > 0:
                    hist[usina_id][dt] = round(kwh, 3)
                    novos += 1

            time.sleep(0.4)  # rate-limit gentil

        print(f"  → {novos} registros adicionados para {usina_id}")

    save_historico(hist)

    # Regenerar geracao_data.json
    try:
        import subprocess
        result = subprocess.run(
            ["python3", str(BASE_DIR / "gerar_geracao_data.py")],
            capture_output=True, text=True, cwd=str(BASE_DIR.parent)
        )
        print(result.stdout.strip())
    except Exception as e:
        print(f"⚠️  Não foi possível regenerar geracao_data.json: {e}")


if __name__ == "__main__":
    main()
