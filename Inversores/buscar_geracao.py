#!/usr/bin/env python3
"""
buscar_geracao.py — Coleta diária de geração dos inversores
============================================================
Conecta ao elekeeper (SAJ — Cartório + Gama 1),
ao TsunSmart (TSUN — Escola) e ao iSolarCloud (Sungrow — Gama 2).

Uso:
  python3 buscar_geracao.py              # coleta e salva hoje
  python3 buscar_geracao.py periodo cartorio 2026-06-10 2026-07-10
  python3 buscar_geracao.py periodo escola 2026-06-11 2026-07-11
  python3 buscar_geracao.py periodo gama_2 2026-06-01 2026-07-01
  python3 buscar_geracao.py historico
  python3 buscar_geracao.py hoje

Credenciais em Inversores/.env:
  SAJ_USERNAME=...
  SAJ_PASSWORD=...
  TSUN_USERNAME=...
  TSUN_PASSWORD=...
  SUNGROW_USERNAME=...
  SUNGROW_PASSWORD=...
"""

from __future__ import annotations
import os, sys, json, hashlib, random, string
from datetime import date, timedelta
from pathlib import Path

# ── Dependências ─────────────────────────────────────────────────────────────
try:
    import requests
except ImportError:
    sys.exit("❌ pip install requests --break-system-packages")

try:
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import pad as aes_pad
except ImportError:
    sys.exit("❌ pip install pycryptodome --break-system-packages")

try:
    from dotenv import load_dotenv
except ImportError:
    sys.exit("❌ pip install python-dotenv --break-system-packages")

# ── Caminhos ──────────────────────────────────────────────────────────────────
BASE_DIR     = Path(__file__).parent
ENV_FILE     = BASE_DIR / ".env"
HIST_FILE    = BASE_DIR / "historico_geracao.json"

load_dotenv(ENV_FILE)

SAJ_USERNAME      = os.getenv("SAJ_USERNAME", "")
SAJ_PASSWORD      = os.getenv("SAJ_PASSWORD", "")
TSUN_USERNAME     = os.getenv("TSUN_USERNAME", "")
TSUN_PASSWORD     = os.getenv("TSUN_PASSWORD", "")
SUNGROW_USERNAME  = os.getenv("SUNGROW_USERNAME", "")
SUNGROW_PASSWORD  = os.getenv("SUNGROW_PASSWORD", "")

# ══════════════════════════════════════════════════════════════════════════════
# MÓDULO SAJ / elekeeper
# Base URL: https://eop.saj-electric.com/dev-api/api/v1
# Créditos: reverse-engineering da integração Homey (telenut/be.telenut.elekeeper)
# ══════════════════════════════════════════════════════════════════════════════

SAJ_BASE     = "https://intl-eop.saj-electric.com/dev-api/api/v1"  # Nó Internacional (Brasil)
SAJ_AES_KEY  = bytes.fromhex("ec1840a7c53cf0709eb784be480379b6")
SAJ_SIGN_KEY = "ktoKRLgQPjvNyUZO8lVc9kU1Bsip6XIe"


def _saj_encrypt_password(password: str) -> str:
    """AES-128-ECB com PKCS7 padding, retorna hex."""
    cipher = AES.new(SAJ_AES_KEY, AES.MODE_ECB)
    padded = aes_pad(password.encode("utf-8"), 16)
    return cipher.encrypt(padded).hex()


def _saj_random_str(n: int = 32) -> str:
    return "".join(random.choices(string.ascii_letters + string.digits, k=n))


def _saj_sign(payload: dict) -> dict:
    """Assina payload: MD5(sorted_kvs + &key=SIGN_KEY) → SHA1 → uppercase."""
    keys = sorted(payload.keys())
    keys_str = ",".join(keys)
    qs = "&".join(f"{k}={payload[k]}" for k in keys) + "&key=" + SAJ_SIGN_KEY
    md5 = hashlib.md5(qs.encode("latin-1")).hexdigest()
    sig = hashlib.sha1(md5.encode("utf-8")).hexdigest().upper()
    return {**payload, "signParams": keys_str, "signature": sig}


def _saj_base_payload() -> dict:
    return {
        "appProjectName": "elekeeper",
        "clientDate": date.today().isoformat(),
        "lang": "en",
        "timeStamp": str(int(__import__("time").time() * 1000)),
        "random": _saj_random_str(32),
        "clientId": "esolar-monitor-admin",
    }


SAJ_NODES = [
    "https://eop.saj-electric.com/dev-api/api/v1",   # EU/Internacional (elekeeper padrão)
    "https://iop.saj-electric.com/dev-api/api/v1",   # Índia/Ásia
    "https://op.saj-electric.cn/dev-api/api/v1",     # China
]

def saj_login(username: str, password: str) -> tuple[str | None, str | None]:
    """Login no elekeeper. Testa múltiplos nós. Retorna (token, base_url) ou (None, None)."""
    enc_pass = _saj_encrypt_password(password)
    for base in SAJ_NODES:
        url = f"{base}/sys/login"
        bp = _saj_base_payload()
        payload = _saj_sign(bp)
        payload["username"] = username
        payload["password"] = enc_pass
        payload["rememberMe"] = "false"
        payload["loginType"] = "1"
        try:
            r = requests.post(url,
                              data=payload,
                              headers={"Content-Type": "application/x-www-form-urlencoded"},
                              timeout=10)
            d = r.json()
            if d.get("errCode") == 0 and d.get("data"):
                head  = d["data"].get("tokenHead", "")
                token = d["data"].get("token", "")
                print(f"✅ SAJ conectou em: {base}")
                return head + token, base
            else:
                print(f"   {base} → errCode={d.get('errCode')} msg={d.get('errMsg','?')}")
        except Exception as e:
            print(f"   {base} → erro: {str(e)[:80]}")
    return None, None


def saj_get_plants(token: str, node_url: str) -> list[dict]:
    """Lista de plantas/usinas do usuário."""
    base = _saj_base_payload()
    params = _saj_sign({**base, "pageNo": "1", "pageSize": "50"})
    try:
        r = requests.get(f"{node_url}/monitor/plant/getEndUserPlantList",
                         params=params,
                         headers={"Authorization": token},
                         timeout=15)
        d = r.json()
        if d.get("errCode") == 0:
            return d.get("data", {}).get("list", [])
    except Exception as e:
        print(f"❌ SAJ get_plants error: {e}")
    return []


def saj_get_devices(token: str, plant_uid: str, node_url: str) -> list[dict]:
    """Lista de inversores de uma usina."""
    base = _saj_base_payload()
    params = _saj_sign({
        **base,
        "plantUid": plant_uid,
        "pageSize": "100",
        "pageNo": "1",
        "searchOfficeIdArr": "1",
    })
    try:
        r = requests.get(f"{node_url}/monitor/device/getDeviceList",
                         params=params,
                         headers={"Authorization": token},
                         timeout=15)
        d = r.json()
        if d.get("errCode") == 0:
            return d.get("data", {}).get("list", [])
    except Exception as e:
        print(f"❌ SAJ get_devices error: {e}")
    return []


def saj_fetch(usina_label: str = "cartorio") -> dict | None:
    """
    Busca dados de todas as plantas SAJ do usuário.
    Retorna { "hoje_kwh": float, "total_kwh": float, "plantas": [...] }
    ou None se falhar.

    usina_label é usado só para logging.
    """
    if not SAJ_USERNAME or not SAJ_PASSWORD:
        print("⚠️  SAJ_USERNAME/SAJ_PASSWORD não configurados em Inversores/.env")
        return None

    print(f"🔌 SAJ ({usina_label}): conectando...")
    token, node_url = saj_login(SAJ_USERNAME, SAJ_PASSWORD)
    if not token:
        print("❌ SAJ: falha no login")
        return None

    plants = saj_get_plants(token, node_url)
    if not plants:
        print("❌ SAJ: nenhuma planta encontrada")
        return None

    hoje_total   = 0.0
    acum_total   = 0.0
    plantas_info = []

    for plant in plants:
        uid  = plant.get("plantUid", "")
        nome = plant.get("plantName", uid)
        devices = saj_get_devices(token, uid, node_url)

        planta_hoje = 0.0
        planta_acum = 0.0
        for dev in devices:
            # A API pode usar diferentes nomes de campo conforme firmware
            hoje = float(
                dev.get("daily_yield") or
                dev.get("todayEnergy") or
                dev.get("dailyYield") or
                dev.get("today_yield") or 0
            )
            acum = float(
                dev.get("total_yield") or
                dev.get("totalEnergy") or
                dev.get("energy_total") or
                dev.get("totalYield") or 0
            )
            planta_hoje += hoje
            planta_acum += acum

        plantas_info.append({"nome": nome, "uid": uid, "hoje_kwh": planta_hoje, "total_kwh": planta_acum})
        hoje_total += planta_hoje
        acum_total += planta_acum
        print(f"   📊 {nome}: hoje={planta_hoje:.2f} kWh | acumulado={planta_acum:.2f} kWh")

    return {"hoje_kwh": hoje_total, "total_kwh": acum_total, "plantas": plantas_info}


# ══════════════════════════════════════════════════════════════════════════════
# MÓDULO TSUN / talent-monitoring.com
# Base URL: https://www.talent-monitoring.com/prod-api
# Créditos: asciidisco/tsun-talent-monitoring
# ══════════════════════════════════════════════════════════════════════════════

TSUN_BASE = "https://www.talent-monitoring.com/prod-api"


def _tsun_solve_captcha(base: str) -> tuple[str, str]:
    """
    Busca captchaImage do servidor, resolve a equação matemática com OCR (tesseract),
    e retorna (uuid, code_resposta).
    O captcha é sempre do tipo "X op Y = ?" — ex: "9+1=?" → resposta "10".
    """
    import base64, io, tempfile, subprocess, re

    try:
        r = requests.get(f"{base}/captchaImage", timeout=8)
        d = r.json()
        uid = d.get("uuid", "")
        img_b64 = d.get("img", "")

        # Remove prefixo data:image se presente
        if "," in img_b64:
            img_b64 = img_b64.split(",", 1)[1]

        if uid and img_b64:
            img_bytes = base64.b64decode(img_b64)
            try:
                import ddddocr, re as _re
                ocr = ddddocr.DdddOcr(show_ad=False)
                ocr_text = ocr.classification(img_bytes).strip().replace(" ", "")
                # Extrai a primeira operação aritmética (ddddocr pode ler =? como lixo)
                match = _re.search(r"([0-9]+[+\-*/][0-9]+)", ocr_text)
                if match:
                    expr = match.group(1)
                    answer = str(int(eval(expr)))  # eval seguro: só dígitos e operadores
                    print(f"   🧮 Captcha OCR: '{ocr_text}' → {expr}={answer}")
                    return uid, answer
                else:
                    print(f"   ⚠️  OCR captcha não reconhecido: '{ocr_text}'")
            except Exception as e:
                print(f"   ⚠️  OCR erro: {e}")

        return uid, ""
    except Exception as e:
        print(f"   ⚠️  captchaImage erro: {e}")
        return str(__import__("uuid").uuid4()), ""


def tsun_login(username: str, password: str) -> str | None:
    """Login no talent-monitoring. Retorna Bearer token ou None."""
    servidores = [
        "https://www.talent-monitoring.com/prod-api",
        "https://pro.talent-monitoring.com/prod-api",
        "https://api.talent-monitoring.com/prod-api",
        "https://cloud.tsun-ess.com/prod-api",
    ]
    for base in servidores:
        try:
            # 1) Busca UUID e resolve captcha matemático
            captcha_uuid, captcha_code = _tsun_solve_captcha(base)
            payload = {
                "username": username,
                "password": password,
                "uuid": captcha_uuid,
                "code": captcha_code,
            }
            r = requests.post(f"{base}/login",
                              json=payload,
                              headers={"Content-Type": "application/json;charset=utf-8"},
                              timeout=8)
            d = r.json()
            tok = d.get("token")
            if tok:
                print(f"✅ TSUN conectou em: {base}")
                return tok
            else:
                print(f"   {base} → {d.get('msg','?')} (code={d.get('code','?')})")
        except Exception as e:
            print(f"   {base} → erro: {str(e)[:60]}")
    return None


def _tsun_headers(token: str) -> dict:
    return {
        "Content-Type": "application/json;charset=utf-8",
        "Authorization": f"Bearer {token}",
    }


def tsun_get_stations(token: str) -> list[dict]:
    url = f"{TSUN_BASE}/system/station/list"
    params = {"pageNum": 1, "pageSize": 10, "businessType": 1, "status": "", "searchOr": ""}
    try:
        r = requests.get(url, params=params, headers=_tsun_headers(token), timeout=15)
        d = r.json()
        return d.get("rows", [])
    except Exception as e:
        print(f"❌ TSUN get_stations error: {e}")
        return []


def tsun_get_inverters(token: str, station_guid: str) -> list[dict]:
    url = f"{TSUN_BASE}/tools/device/selectDeviceInverter"
    params = {
        "searchOr": "", "status": "", "deviceTypeEn": "inverter",
        "powerStationGuid": station_guid, "businessType": 0,
        "pageNum": 1, "pageSize": 10,
    }
    try:
        r = requests.get(url, params=params, headers=_tsun_headers(token), timeout=15)
        d = r.json()
        return d.get("rows", [])
    except Exception as e:
        print(f"❌ TSUN get_inverters error: {e}")
        return []


def tsun_get_inverter_data(token: str, device_guid: str) -> dict | None:
    url = f"{TSUN_BASE}/tools/device/selectDeviceInverterInfo"
    params = {"deviceGuid": device_guid, "timezone": "-03:00"}
    try:
        r = requests.get(url, params=params, headers=_tsun_headers(token), timeout=15)
        d = r.json()
        return d.get("data")
    except Exception as e:
        print(f"❌ TSUN get_inverter_data error: {e}")
        return None


def tsun_fetch() -> dict | None:
    """
    Busca dados de todos os inversores TSUN.
    Retorna { "hoje_kwh": float, "total_kwh": float, "estacoes": [...] }
    energyToday está em Wh → convertemos para kWh.
    """
    if not TSUN_USERNAME or not TSUN_PASSWORD:
        print("⚠️  TSUN_USERNAME/TSUN_PASSWORD não configurados em Inversores/.env")
        return None

    print("🔌 TSUN (escola): conectando...")
    token = tsun_login(TSUN_USERNAME, TSUN_PASSWORD)
    if not token:
        print("❌ TSUN: falha no login")
        return None

    stations = tsun_get_stations(token)
    if not stations:
        print("❌ TSUN: nenhuma estação encontrada")
        return None

    hoje_total   = 0.0
    acum_total   = 0.0
    estacoes_info = []

    for station in stations:
        guid = station.get("powerStationGuid", "")
        nome = station.get("stationName", guid)
        inverters = tsun_get_inverters(token, guid)

        est_hoje = 0.0
        est_acum = 0.0

        for inv in inverters:
            dev_guid = inv.get("deviceGuid", "")
            data = tsun_get_inverter_data(token, dev_guid)
            if not data:
                continue

            # energyToday em Wh → kWh
            hoje_wh = float(data.get("energyToday") or 0)
            hoje_kwh = hoje_wh / 1000.0

            # monthEnergyNamed e yearEnergyNamed são strings como "18.92 kWh"
            # Não há total acumulado direto — usamos soma mensal como proxy
            month_str = data.get("monthEnergyNamed", "0 kWh")
            month_kwh = float(month_str.split()[0])

            est_hoje += hoje_kwh
            est_acum += month_kwh  # nota: apenas proxy mensal, não acumulado total

        estacoes_info.append({"nome": nome, "guid": guid, "hoje_kwh": est_hoje, "mes_kwh": est_acum})
        hoje_total += est_hoje
        acum_total += est_acum
        print(f"   📊 {nome}: hoje={est_hoje:.3f} kWh | este mês={est_acum:.2f} kWh")

    return {"hoje_kwh": hoje_total, "mes_kwh": acum_total, "estacoes": estacoes_info}


# ══════════════════════════════════════════════════════════════════════════════
# MÓDULO SUNGROW / iSolarCloud
# Gateways: augateway.isolarcloud.com  (América do Sul / Austrália)
#           gateway.isolarcloud.com.hk (Ásia / Global)
#           gateway.isolarcloud.eu     (Europa)
# AppKey Android (comunidade): ANDROIDE13EC118BD7892FE7AB5A3F20
# ══════════════════════════════════════════════════════════════════════════════

SUNGROW_APPKEY = "ANDROIDE13EC118BD7892FE7AB5A3F20"
SUNGROW_GATEWAYS = [
    "https://augateway.isolarcloud.com",     # América do Sul / Austrália
    "https://gateway.isolarcloud.com.hk",    # Ásia / Global
    "https://gateway.isolarcloud.eu",         # Europa
]


def sungrow_login(username: str, password: str) -> tuple[str | None, str | None]:
    """
    Login no iSolarCloud. Testa múltiplos gateways e formatos de senha.
    Retorna (token, gateway_url) ou (None, None).
    """
    import hashlib as _hl
    # Alguns firmwares pedem senha em MD5, outros em plain text
    passwords = [password, _hl.md5(password.encode()).hexdigest()]

    for gateway in SUNGROW_GATEWAYS:
        for pwd in passwords:
            try:
                payload = {
                    "appkey": SUNGROW_APPKEY,
                    "user_account": username,
                    "user_password": pwd,
                    "lang": "_en_US",
                    "sys_code": "900",
                    "token": "null",
                }
                r = requests.post(
                    f"{gateway}/openapi/login",
                    json=payload,
                    headers={
                        "Content-Type": "application/json",
                        "x-access-key": SUNGROW_APPKEY,
                    },
                    timeout=12,
                )
                d = r.json()
                rc = str(d.get("result_code", ""))
                if rc == "1" and d.get("result_data", {}).get("token"):
                    token = d["result_data"]["token"]
                    print(f"✅ Sungrow conectou em: {gateway}")
                    return token, gateway
                else:
                    msg = d.get("result_msg", "?")
                    print(f"   {gateway} → {msg} (code={rc})")
                    # Se retornou erro de appkey/criptografia, não tenta MD5
                    if any(x in str(msg).lower() for x in ("appkey", "encrypt", "key")):
                        break
            except Exception as e:
                print(f"   {gateway} → erro: {str(e)[:80]}")
                break  # Sem DNS — pula para próximo gateway

    return None, None


def sungrow_get_plants(token: str, gateway: str) -> list[dict]:
    """Lista usinas cadastradas no iSolarCloud."""
    payload = {
        "appkey": SUNGROW_APPKEY,
        "token": token,
        "curPage": "1",
        "size": "50",
        "lang": "_en_US",
        "sys_code": "900",
    }
    try:
        r = requests.post(
            f"{gateway}/openapi/getPowerStationList",
            json=payload,
            headers={"Content-Type": "application/json", "x-access-key": SUNGROW_APPKEY},
            timeout=15,
        )
        d = r.json()
        if str(d.get("result_code", "")) == "1":
            return d.get("result_data", {}).get("pageList", [])
        else:
            print(f"   Sungrow plants → {d.get('result_msg','?')}")
    except Exception as e:
        print(f"❌ Sungrow get_plants error: {e}")
    return []


def sungrow_get_today_kwh(token: str, gateway: str, ps_id: str) -> float:
    """
    Retorna a geração de hoje (kWh) de uma usina.
    p83033 = today_energy_purchase_kwh (geração total do dia).
    """
    payload = {
        "appkey": SUNGROW_APPKEY,
        "token": token,
        "ps_id_list": str(ps_id),
        "lang": "_en_US",
        "sys_code": "900",
    }
    try:
        r = requests.post(
            f"{gateway}/openapi/getPowerStationRealKpi",
            json=payload,
            headers={"Content-Type": "application/json", "x-access-key": SUNGROW_APPKEY},
            timeout=15,
        )
        d = r.json()
        if str(d.get("result_code", "")) == "1":
            station_map = d.get("result_data", {}).get("stationDataMap", {})
            for data in station_map.values():
                # p83033 = energia gerada hoje (kWh)
                val = data.get("p83033") or data.get("daily_yield") or data.get("today_energy")
                if val is not None:
                    return float(val)
        else:
            print(f"   Sungrow kpi → {d.get('result_msg','?')}")
    except Exception as e:
        print(f"❌ Sungrow get_today error: {e}")
    return 0.0


def sungrow_fetch() -> dict | None:
    """
    Busca dados de todas as usinas Sungrow (Gama 2 e demais).
    Retorna { "plantas": [ {nome, ps_id, hoje_kwh} ], "hoje_kwh": float }
    """
    if not SUNGROW_USERNAME or not SUNGROW_PASSWORD:
        print("ℹ️  SUNGROW_USERNAME/PASSWORD não configurados em Inversores/.env")
        return None

    print("🔌 Sungrow (gama 2): conectando...")
    token, gateway = sungrow_login(SUNGROW_USERNAME, SUNGROW_PASSWORD)
    if not token:
        print("❌ Sungrow: falha no login")
        return None

    plants = sungrow_get_plants(token, gateway)
    if not plants:
        print("❌ Sungrow: nenhuma usina encontrada")
        return None

    plantas_info = []
    hoje_total = 0.0

    for plant in plants:
        ps_id = str(plant.get("ps_id", ""))
        nome  = plant.get("ps_name", ps_id)
        hoje_kwh = sungrow_get_today_kwh(token, gateway, ps_id)
        plantas_info.append({"nome": nome, "ps_id": ps_id, "hoje_kwh": hoje_kwh})
        hoje_total += hoje_kwh
        print(f"   📊 {nome}: hoje={hoje_kwh:.2f} kWh")

    return {"hoje_kwh": hoje_total, "plantas": plantas_info}


# ══════════════════════════════════════════════════════════════════════════════
# HISTÓRICO E CÁLCULO DE PERÍODO
# ══════════════════════════════════════════════════════════════════════════════

def load_historico() -> dict:
    if HIST_FILE.exists():
        with open(HIST_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {"cartorio": {}, "escola": {}, "gama_1": {}, "gama_2": {}}


def save_historico(hist: dict):
    with open(HIST_FILE, "w", encoding="utf-8") as f:
        json.dump(hist, f, indent=2, ensure_ascii=False)


def registrar_hoje(usina: str, hoje_kwh: float):
    """Salva a geração de hoje no histórico."""
    hist = load_historico()
    if usina not in hist:
        hist[usina] = {}
    hoje = date.today().isoformat()
    hist[usina][hoje] = round(hoje_kwh, 3)
    save_historico(hist)
    print(f"💾 Salvo: {usina} {hoje} = {hoje_kwh:.3f} kWh")


def buscar_geracao_periodo(usina: str, data_inicio: str, data_fim: str) -> float:
    """
    Retorna a geração total (kWh) de uma usina entre data_inicio e data_fim,
    ambas no formato 'AAAA-MM-DD', inclusivas.

    Usa o histórico diário acumulado em historico_geracao.json.
    Dias sem registro são ignorados com aviso.
    """
    hist = load_historico()
    usina_hist = hist.get(usina, {})

    inicio = date.fromisoformat(data_inicio)
    fim    = date.fromisoformat(data_fim)

    total   = 0.0
    faltam  = []
    d = inicio
    while d <= fim:
        ds = d.isoformat()
        if ds in usina_hist:
            total += usina_hist[ds]
        else:
            faltam.append(ds)
        d += timedelta(days=1)

    if faltam:
        print(f"⚠️  {usina}: {len(faltam)} dia(s) sem registro no período ({faltam[0]} … {faltam[-1]})")
        print(f"   Total calculado com dados disponíveis: {total:.2f} kWh")
    else:
        print(f"✅ {usina} [{data_inicio} → {data_fim}]: {total:.2f} kWh")

    return round(total, 2)


# ══════════════════════════════════════════════════════════════════════════════
# COLETA DIÁRIA — roda automático via tarefa agendada às 22h
# ══════════════════════════════════════════════════════════════════════════════

def coletar_hoje():
    """Busca e salva a geração de hoje de todas as usinas configuradas."""
    print(f"\n{'='*55}")
    print(f"  COLETA DE GERAÇÃO — {date.today()}")
    print(f"{'='*55}\n")

    erros = []

    # ── SAJ / elekeeper → Cartório + Usina 1 Gama (mesma conta) ─────────────
    if SAJ_USERNAME and SAJ_PASSWORD:
        saj_data = saj_fetch("SAJ")
        if saj_data:
            for planta in saj_data["plantas"]:
                nome_lower = planta["nome"].lower()
                kwh = planta["hoje_kwh"]
                if "cartorio" in nome_lower or "cartório" in nome_lower:
                    registrar_hoje("cartorio", kwh)
                elif "gama" in nome_lower:
                    registrar_hoje("gama_1", kwh)
                else:
                    print(f"   ⚠️  Planta SAJ não mapeada: {planta['nome']} ({kwh:.2f} kWh)")
        else:
            erros.append("SAJ/elekeeper: falha na coleta")
    else:
        print("ℹ️  SAJ não configurado — pulando Cartório")

    print()

    # ── TSUN / TsunSmart → Escola ─────────────────────────────────────────
    # Usa Playwright (slider captcha + OAuth2) via buscar_geracao_playwright.py
    if TSUN_USERNAME and TSUN_PASSWORD:
        try:
            from buscar_geracao_playwright import tsun_fetch_playwright
            tsun_data = tsun_fetch_playwright()
        except ImportError:
            tsun_data = tsun_fetch()   # fallback para API direta (sem captcha)
        if tsun_data:
            registrar_hoje("escola", tsun_data["hoje_kwh"])
        else:
            erros.append("TSUN/TsunSmart: falha na coleta")
    else:
        print("ℹ️  TSUN não configurado — pulando Escola")

    print()

    # ── Sungrow / iSolarCloud → Gama 2 ────────────────────────────────────
    # Usa Playwright (DOM scraping da lista de plantas) via buscar_geracao_playwright.py
    if SUNGROW_USERNAME and SUNGROW_PASSWORD:
        try:
            from buscar_geracao_playwright import sungrow_fetch_playwright
            sg_data = sungrow_fetch_playwright()
        except ImportError:
            sg_data = sungrow_fetch()   # fallback para openapi (pode falhar com E912)
        if sg_data:
            for planta in sg_data["plantas"]:
                nome_lower = planta["nome"].lower()
                kwh = planta["hoje_kwh"]
                # Mapeamento por nome da usina no iSolarCloud
                # Ajustar se o nome no portal for diferente
                if "gama" in nome_lower:
                    registrar_hoje("gama_2", kwh)
                else:
                    # Salva com chave baseada no nome (sanitizado)
                    chave = "sg_" + "".join(c if c.isalnum() else "_" for c in nome_lower)[:20]
                    registrar_hoje(chave, kwh)
                    print(f"   ⚠️  Planta Sungrow não mapeada: {planta['nome']} → chave='{chave}'")
        else:
            erros.append("Sungrow/iSolarCloud: falha na coleta")
    else:
        print("ℹ️  Sungrow não configurado — pulando Gama 2")

    if erros:
        print(f"\n⚠️  Erros: {'; '.join(erros)}")
    else:
        print("\n✅ Coleta concluída com sucesso!")

    return len(erros) == 0


# ══════════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    args = sys.argv[1:]

    if not args or args[0] == "coletar":
        # Coleta diária — modo padrão chamado pelo agendador
        ok = coletar_hoje()
        sys.exit(0 if ok else 1)

    elif args[0] == "periodo" and len(args) == 4:
        # Consulta período para billing
        _, usina, inicio, fim = args
        kwh = buscar_geracao_periodo(usina, inicio, fim)
        print(f"\nGERACAO_APP_kWh = {kwh}")

    elif args[0] == "historico":
        # Mostra histórico completo
        hist = load_historico()
        print(json.dumps(hist, indent=2, ensure_ascii=False))

    elif args[0] == "hoje":
        # Mostra apenas o último dia salvo de cada usina
        hist = load_historico()
        for usina, dias in hist.items():
            if dias:
                ultimo_dia = sorted(dias.keys())[-1]
                print(f"{usina}: {ultimo_dia} = {dias[ultimo_dia]} kWh")
            else:
                print(f"{usina}: sem dados")

    else:
        print(__doc__)
        sys.exit(1)
