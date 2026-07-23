#!/usr/bin/env python3
"""
buscar_geracao_playwright.py — Coleta de geração via Playwright (headless browser)
===================================================================================
Usado para portais com CAPTCHA que não têm API pública simples:
  - TSUN / TsunSmart  → pro.talent-monitoring.com  (Escola)
  - Sungrow / iSolarCloud → web3.isolarcloud.com.hk (Gama 2)

Ambos usam sessão persistente (login apenas na primeira vez).

Uso direto:
  python3 Inversores/buscar_geracao_playwright.py tsun
  python3 Inversores/buscar_geracao_playwright.py sungrow
  python3 Inversores/buscar_geracao_playwright.py ambos

Importado por buscar_geracao.py:
  from buscar_geracao_playwright import tsun_fetch_playwright, sungrow_fetch_playwright
"""

from __future__ import annotations
import math, random, re, sys, time, json, os
from pathlib import Path
from datetime import date

try:
    from dotenv import load_dotenv
except ImportError:
    sys.exit("❌ pip install python-dotenv")

try:
    import requests as _requests
except ImportError:
    _requests = None

BASE_DIR  = Path(__file__).parent
ENV_FILE  = BASE_DIR / ".env"
load_dotenv(ENV_FILE)

TSUN_USERNAME     = os.getenv("TSUN_USERNAME", "")
TSUN_PASSWORD     = os.getenv("TSUN_PASSWORD", "")
TSUN_GATEWAY_SN   = os.getenv("TSUN_GATEWAY_SN", "")   # SN do data logger da Escola
SUNGROW_USERNAME  = os.getenv("SUNGROW_USERNAME", "")
SUNGROW_PASSWORD  = os.getenv("SUNGROW_PASSWORD", "")

# Diretórios de sessão persistente (cookies salvos entre execuções)
TSUN_SESSION_DIR     = BASE_DIR / "sessions" / "tsun"
SUNGROW_SESSION_DIR  = BASE_DIR / "sessions" / "sungrow"
TSUN_TOKEN_FILE      = BASE_DIR / "sessions" / "tsun_token.json"


# ══════════════════════════════════════════════════════════════════════════════
# MÓDULO TSUN — pro.talent-monitoring.com
# Login: OAuth2 password grant + Alibaba AWSC slider captcha
# ══════════════════════════════════════════════════════════════════════════════

TSUN_BASE = "https://pro.talent-monitoring.com"


def _tsun_drag_slider(page) -> bool:
    """
    Resolve o slider captcha Alibaba AWSC arrastando o elemento
    #aliyunCaptcha-sliding-slider até o final da track.
    Retorna True se aprovado ('验证通过!' apareceu no texto).
    """
    try:
        page.wait_for_selector("#aliyunCaptcha-sliding-slider", timeout=12_000)
        time.sleep(0.6)

        slider = page.locator("#aliyunCaptcha-sliding-slider")
        body   = page.locator("#aliyunCaptcha-sliding-body")

        sb = slider.bounding_box()
        bb = body.bounding_box()
        if not sb or not bb:
            print("   ⚠️  TSUN: bounding_box do slider não encontrado")
            return False

        sx = sb["x"] + sb["width"]  / 2
        sy = sb["y"] + sb["height"] / 2
        ex = bb["x"] + bb["width"]  - sb["width"] / 2

        # Hover antes de pressionar (mais natural)
        page.mouse.move(sx - 10, sy + random.uniform(-3, 3))
        time.sleep(0.15)
        page.mouse.move(sx, sy)
        time.sleep(0.25)
        page.mouse.down()
        time.sleep(0.12)

        # Arrastar com aceleração/desaceleração humana (ease-in-out)
        steps = 35
        for i in range(steps + 1):
            t = i / steps
            # Ease-in-out cubic
            ease = t * t * (3 - 2 * t)
            x = sx + (ex - sx) * ease
            y = sy + math.sin(t * math.pi) * 3 + random.uniform(-0.8, 0.8)
            page.mouse.move(x, y)
            time.sleep(random.uniform(0.008, 0.025))

        # Pausar no final antes de soltar
        time.sleep(0.3 + random.uniform(0, 0.2))
        page.mouse.up()
        time.sleep(1.5)

        # Verificar resultado
        txt = page.locator("#aliyunCaptcha-sliding-text").text_content(timeout=3000) or ""
        if "通过" in txt:
            print("   ✅ TSUN captcha aprovado")
            return True
        else:
            print(f"   ⚠️  TSUN captcha: '{txt}'")
            return False

    except Exception as e:
        print(f"   ⚠️  TSUN drag_slider erro: {e}")
        return False


def _tsun_save_token(token: str):
    """Persiste token OAuth2 em disco para reutilização sem browser."""
    TSUN_TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(TSUN_TOKEN_FILE, "w") as f:
        json.dump({"token": token, "saved_at": time.time()}, f)


def _tsun_load_token() -> str | None:
    """Carrega token salvo se tiver menos de 22 horas (expira em ~24h)."""
    if not TSUN_TOKEN_FILE.exists():
        return None
    try:
        with open(TSUN_TOKEN_FILE) as f:
            d = json.load(f)
        age_h = (time.time() - d.get("saved_at", 0)) / 3600
        if age_h < 22:
            return d.get("token")
    except Exception:
        pass
    return None


def _tsun_api_fetch(token: str) -> dict | None:
    """
    Busca geração via API direta usando Bearer token OAuth2 (POST, não GET).
    O portal TSUN usa POST em todos os endpoints de dados.
    """
    if not _requests:
        return None

    hdrs = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json, */*",
        "Origin": TSUN_BASE,
        "Referer": f"{TSUN_BASE}/",
    }

    def _post(path, body=None, params=None):
        """POST helper com debug."""
        url = f"{TSUN_BASE}{path}"
        try:
            r = _requests.post(url, headers=hdrs, json=body or {}, params=params, timeout=12)
            preview = r.text[:200].strip()
            print(f"   🔍 POST {path} → HTTP {r.status_code} | {preview[:120]!r}")
            if r.status_code == 200 and preview:
                return r.json()
        except Exception as e:
            print(f"   ⚠️  POST {path}: {e}")
        return None

    # ── Passo 1: Listar dispositivos (terminal user acessa por device-monitor) ──
    devices = []
    dev_resp = _post("/device-s/device-monitor/list",
                     body={"language": "en"},
                     params={"pageNum": 1, "pageSize": 50})
    if dev_resp:
        data = dev_resp.get("data") or dev_resp.get("result") or {}
        recs = (data.get("records") or data.get("list") or data.get("rows")
                if isinstance(data, dict) else data if isinstance(data, list) else [])
        devices = recs or dev_resp.get("rows") or []
        if devices:
            print(f"   ✅ {len(devices)} dispositivo(s) encontrado(s)")

    # ── Passo 1b: se device-monitor/list não retornou, tentar por station (POST) ──
    stations = []
    if not devices:
        st_resp = _post("/station-s/station/query/day/overview",
                        body={"language": "en",
                              "date": date.today().strftime("%Y-%m-%d")})
        if st_resp:
            data = st_resp.get("data") or {}
            # Tentar extrair kWh direto do overview
            _tsun_extract_energy("/station-s/station/query/day/overview", st_resp, {})
            hoje_kwh_overview = None
            for k in ["todayEnergy", "dailyEnergy", "dayEnergy", "eToday", "generationToday"]:
                if data.get(k) is not None:
                    try:
                        kwh = float(data[k])
                        if kwh > 10_000:
                            kwh /= 1000.0
                        if 0 < kwh < 5000:
                            hoje_kwh_overview = kwh
                            print(f"   ✅ TSUN day/overview: {kwh:.3f} kWh")
                            break
                    except Exception:
                        pass
            if hoje_kwh_overview:
                return {"hoje_kwh": hoje_kwh_overview,
                        "estacoes": [{"nome": "Escola", "hoje_kwh": hoje_kwh_overview}]}

    if not devices and not stations:
        print("   ⚠️  TSUN API: nenhum dispositivo ou estação encontrado via POST")
        return None

    # ── Passo 2: Extrair Etdy_ge0 diretamente dos dados do list ──────────────
    # O endpoint current-data não é acessível para usuários terminais (roleId=-1),
    # mas o list já retorna characteristicValueMap.Etdy_ge0 (geração do dia em kWh).
    gw_sn = TSUN_GATEWAY_SN
    hoje_total = 0.0
    estacoes   = []

    for dev in devices:
        # Filtra inversores (tipo 15) do gateway da Escola
        if dev.get("deviceType") != 15:
            continue
        if gw_sn and dev.get("gatewaySn") != gw_sn:
            continue
        cvm  = dev.get("characteristicValueMap") or {}
        nome = dev.get("deviceSn") or "?"
        raw  = cvm.get("Etdy_ge0")
        if raw is None:
            continue
        try:
            kwh = float(raw)
        except (ValueError, TypeError):
            continue
        if kwh > 10_000:
            kwh /= 1000.0   # Wh → kWh
        if 0 <= kwh < 5000:
            hoje_total += kwh
            alert = (dev.get("alertNames") or [])
            print(f"   📊 TSUN {nome}: Etdy_ge0={kwh:.3f} kWh  alert={alert}")
            estacoes.append({"nome": nome, "hoje_kwh": kwh})

    if estacoes:
        print(f"   ✅ TSUN total: {hoje_total:.3f} kWh  ({len(estacoes)} microinversor(es))")
        return {"hoje_kwh": hoje_total, "estacoes": estacoes}

    # Se não encontrou pelo gatewaySn, tentar qualquer tipo-15 com siteId≥0
    for dev in devices:
        if dev.get("deviceType") != 15:
            continue
        if (dev.get("siteId") or -1) < 0:
            continue
        cvm = dev.get("characteristicValueMap") or {}
        raw = cvm.get("Etdy_ge0")
        if raw is None:
            continue
        try:
            kwh = float(raw)
        except (ValueError, TypeError):
            continue
        if kwh > 10_000:
            kwh /= 1000.0
        if 0 <= kwh < 5000:
            hoje_total += kwh
            nome = dev.get("deviceSn") or "?"
            estacoes.append({"nome": nome, "hoje_kwh": kwh})
            print(f"   📊 TSUN fallback {nome}: {kwh:.3f} kWh")

    if estacoes:
        print(f"   ✅ TSUN fallback total: {hoje_total:.3f} kWh")
        return {"hoje_kwh": hoje_total, "estacoes": estacoes}

    return None


def _tsun_do_login(page, username: str, password: str) -> dict:
    """
    Faz login no TSUN via browser: resolve slider AWSC, captura token OAuth2 e
    intercepta dados de energia que o portal carrega após o login.
    Retorna dict {"token": str|None, "today_kwh": float|None}.
    """
    captured: dict = {"token": None, "today_kwh": None}

    def _on_response(response):
        url = response.url
        # Capturar token OAuth2
        if "oauth2-s/oauth/token" in url:
            try:
                data = response.json()
                t = data.get("access_token")
                if t:
                    captured["token"] = t
                    _tsun_save_token(t)   # salvar imediatamente
                    print("   💾 Token salvo em disco")
            except Exception:
                pass
        # Ignorar assets estáticos
        elif any(s in url for s in (".js", ".css", ".png", ".ico", ".woff", ".svg", ".ttf", ".map")):
            pass
        else:
            # Logar TODAS as chamadas de API do portal para descobrir os endpoints corretos
            rel = url.replace(TSUN_BASE, "").split("?")[0]
            try:
                body = response.body()
                body_preview = body[:120].decode("utf-8", errors="replace").strip()
                print(f"   📡 API: {rel} [{response.status}] {body_preview!r}")
                data = response.json()
                _tsun_extract_energy(url, data, captured)
            except Exception:
                pass

    page.on("response", _on_response)

    page.goto(f"{TSUN_BASE}/login", wait_until="load", timeout=60_000)

    # Aba "邮箱" (Email)
    tabs = page.locator('[role="tab"]')
    if tabs.count() >= 2:
        tabs.nth(1).click()
    time.sleep(0.4)

    page.fill('input[placeholder="邮箱"]', username)
    page.fill('input[type="password"]', password)

    # Resolver slider
    ok = _tsun_drag_slider(page)
    if not ok:
        time.sleep(1)
        ok = _tsun_drag_slider(page)
        if not ok:
            return captured

    # Submeter login e aguardar redirecionamento para dashboard
    page.click('button:has-text("登")')

    # Fase 1: aguardar token OAuth2 (até 15s)
    t0 = time.time()
    while time.time() - t0 < 15 and not captured["token"]:
        time.sleep(0.4)

    # Fechar dialog "终端用户不允许登录" se aparecer (antes de aguardar dados)
    time.sleep(1.5)
    for sel in ['button:has-text("确定")', 'button:has-text("确 定")', 'button:has-text("OK")']:
        try:
            if page.locator(sel).count() > 0:
                page.click(sel)
                print("   ℹ️  TSUN: dialog fechado — aguardando dashboard...")
                break
        except Exception:
            pass

    # Fase 2: aguardar dados de energia via interceptor (mais 10s após fechar dialog)
    t1 = time.time()
    while time.time() - t1 < 10:
        if captured["today_kwh"] is not None:
            break
        time.sleep(0.5)

    # Fase 3: DOM scraping — o portal exibe os dados visualmente mesmo para terminal users
    if captured["today_kwh"] is None:
        print("   ℹ️  TSUN: interceptor sem dados — tentando DOM scraping...")
        try:
            # Garantir que estamos no dashboard (não na tela de login)
            cur_url = page.url
            print(f"   🌐 URL: {cur_url}")
            if "login" in cur_url.lower():
                page.goto(f"{TSUN_BASE}/", wait_until="load", timeout=30_000)
                time.sleep(5)

            dom_text = page.evaluate("() => document.body.innerText") or ""
            print(f"   📄 DOM preview: {dom_text[:400]!r}")

            # Padrões usados em portais chineses de solar
            dom_patterns = [
                r'今日发电[量]*\s*[:：]?\s*([\d.]+)\s*(?:kWh|度)',
                r'日发电[量]*\s*[:：]?\s*([\d.]+)',
                r'([\d]{1,4}\.[\d]{1,3})\s*kWh',
                r'([\d]{1,4}\.[\d]{1,3})\s*度',
            ]
            for pat in dom_patterns:
                for m in re.findall(pat, dom_text, re.IGNORECASE):
                    try:
                        kwh = float(m)
                        if 0 < kwh < 5000:
                            captured["today_kwh"] = kwh
                            print(f"   🎯 TSUN DOM: {kwh:.3f} kWh (padrão: {pat})")
                            break
                    except ValueError:
                        pass
                if captured["today_kwh"] is not None:
                    break
        except Exception as e:
            print(f"   ⚠️  TSUN DOM scraping erro: {e}")

    return captured




def _tsun_extract_energy(url: str, data, captured: dict):
    """
    Varre recursivamente uma resposta JSON do TSUN em busca de campos de geração do dia.
    Atualiza captured["today_kwh"] e captured["stations"] se encontrar algo.
    """
    ENERGY_KEYS = {
        "todayEnergy", "dailyEnergy", "dayEnergy", "energyToday",
        "daily_energy", "today_yield", "dayYield", "todayYield",
        "powerToday", "generationToday", "eToday", "eTodayKwh",
    }

    def _walk(obj, depth=0):
        if depth > 6:
            return
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k in ENERGY_KEYS and v is not None:
                    try:
                        kwh = float(v)
                        if kwh > 10_000:      # provável Wh → converter
                            kwh /= 1000.0
                        if 0 < kwh < 5000:    # sanity check
                            old = captured.get("today_kwh")
                            if old is None or kwh > old:
                                captured["today_kwh"] = kwh
                                seg = url.split("?")[0].split("/")[-1]
                                print(f"   🎯 TSUN [{seg}] {k}={kwh:.3f} kWh")
                    except (ValueError, TypeError):
                        pass
                else:
                    _walk(v, depth + 1)
        elif isinstance(obj, list):
            for item in obj:
                _walk(item, depth + 1)

    if isinstance(data, dict):
        _walk(data)


def tsun_fetch_playwright(username: str = "", password: str = "") -> dict | None:
    """
    Busca geração TSUN (Escola):
    1. Tenta API direta com token OAuth2 salvo em disco (sem abrir browser)
    2. Se token ausente/expirado: abre browser → resolve captcha → salva token → API direta
    Retorna { "hoje_kwh": float, "estacoes": [...] } ou None.
    """
    u = username or TSUN_USERNAME
    pw = password or TSUN_PASSWORD
    if not u or not pw:
        print("⚠️  TSUN credenciais não configuradas em Inversores/.env")
        return None

    print("🔌 TSUN (escola): verificando token salvo...")

    # ── Caminho rápido: token em disco ─────────────────────────────────────────
    cached_token = _tsun_load_token()
    if cached_token:
        print("   ✅ Token em cache — chamando API diretamente (sem browser)")
        result = _tsun_api_fetch(cached_token)
        if result:
            return result
        print("   ⚠️  Token expirado ou API falhou — renovando via browser...")

    # ── Caminho lento: browser para novo token ──────────────────────────────────
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("❌ playwright não instalado. Execute: pip install playwright && playwright install chromium")
        return None

    print("🔌 TSUN (escola): abrindo browser para novo login...")
    TSUN_SESSION_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(TSUN_SESSION_DIR),
            headless=False,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )

        page.goto(f"{TSUN_BASE}/", wait_until="load", timeout=60_000)
        time.sleep(2)

        # Detectar login pelo conteúdo DOM — a URL pode ser "/" mesmo na tela de login
        page_text = page.evaluate("() => document.body.innerText") or ""
        on_login = (
            "/login" in page.url
            or "login" in page.url.lower()
            or ("登" in page_text and "邮箱" in page_text)   # formulário em chinês
            or (len(page_text.strip()) < 600 and "TSUN" in page_text)
        )

        login_result: dict = {}
        if on_login:
            print("   ℹ️  TSUN: sem sessão — fazendo login (browser)...")
            login_result = _tsun_do_login(page, u, pw)
            if not login_result.get("token"):
                print("❌ TSUN: falha no login (captcha ou credenciais)")
                ctx.close()
                return None
            print("   ✅ TSUN: token obtido e salvo")
        else:
            # Sessão ativa — interceptar as chamadas de API que o portal faz ao carregar
            print("   ℹ️  TSUN: sessão ativa — aguardando API do portal...")
            captured_live: dict = {"today_kwh": None}

            def _live_intercept(response):
                if any(s in response.url for s in (".js", ".css", ".png", ".ico", ".woff")):
                    return
                try:
                    _tsun_extract_energy(response.url, response.json(), captured_live)
                except Exception:
                    pass

            page.on("response", _live_intercept)
            page.goto(f"{TSUN_BASE}/", wait_until="load", timeout=60_000)
            time.sleep(10)
            login_result = {"token": None, "today_kwh": captured_live.get("today_kwh")}

        ctx.close()

    # token do login OU do cache (caso sessão ativa sem novo login)
    new_token   = login_result.get("token") or cached_token
    energy_now  = login_result.get("today_kwh")

    # Se o interceptor capturou dados de energia direto do portal, usar
    if energy_now and energy_now > 0:
        print(f"   ✅ TSUN (portal): {energy_now:.3f} kWh capturado via interceptor do browser")
        return {"hoje_kwh": energy_now, "estacoes": [{"nome": "Escola", "hoje_kwh": energy_now}]}

    # Tentar API direta com o novo token
    if new_token:
        result = _tsun_api_fetch(new_token)
        if result:
            return result
        print("   ⚠️  Token novo mas API ainda vazia — endpoints podem diferir do esperado")

    print("❌ TSUN: nenhum dado de geração obtido")
    return None



# ══════════════════════════════════════════════════════════════════════════════
# MÓDULO SUNGROW — web3.isolarcloud.com.hk
# Login: email + senha (sem captcha conhecido)
# Leitura: DOM da lista de plantas (campo 当日发电 = geração do dia)
# ══════════════════════════════════════════════════════════════════════════════

SUNGROW_BASE = "https://web3.isolarcloud.com.hk"


def _sungrow_read_plant_list(page) -> list[dict]:
    """
    Navega para #/plantList e extrai a geração de hoje de cada usina.
    O portal mostra os valores em '度' (kWh em chinês).
    """
    page.goto(f"{SUNGROW_BASE}/#/plantList", wait_until="load", timeout=60_000)
    time.sleep(3)

    body = page.evaluate("() => document.body.innerText") or ""

    # Padrão: 当日发电 (Today's generation) → X.X 度
    # Formato real observado: "120.4 度" após a coluna 当日发电
    patterns = [
        # Tabela com formato "X.X 度"
        r"当日发电[\s\S]{0,200}?([\d,]+\.?\d*)\s*度",
        # Alternativa: valores kWh diretos
        r"([\d,]+\.?\d+)\s*kWh",
    ]

    plants = []
    for pat in patterns:
        matches = re.findall(pat, body)
        if matches:
            for i, m in enumerate(matches):
                kwh = float(m.replace(",", ""))
                # Converter 万度 (10,000 kWh) se necessário
                # Valores de hoje geralmente < 1000 kWh — filtrar valores mensais/anuais
                if kwh < 5000:
                    plants.append({"nome": f"Gama2_planta_{i+1}", "hoje_kwh": kwh})
            break

    # Se não encontrou com regex, tentar extração estruturada da tabela
    if not plants:
        rows = page.evaluate("""() => {
            const tds = [...document.querySelectorAll('td')];
            const result = [];
            tds.forEach((td, i) => {
                const text = td.innerText.trim();
                if (/^\\d+\\.?\\d*\\s*度$/.test(text)) {
                    result.push(parseFloat(text.replace('度','').trim()));
                }
            });
            return result;
        }""")
        for i, kwh in enumerate(rows or []):
            if 0 < kwh < 5000:
                plants.append({"nome": f"Gama2_planta_{i+1}", "hoje_kwh": float(kwh)})

    return plants


def _sungrow_login(page, username: str, password: str) -> bool:
    """Tenta fazer login no iSolarCloud. Retorna True se bem-sucedido."""
    page.goto(SUNGROW_BASE, wait_until="load", timeout=60_000)
    time.sleep(2)

    # Se não redirecionou para login, já está logado
    if "/login" not in page.url and "login" not in page.url.lower():
        return True

    # Preencher email e senha
    try:
        email_sel = 'input[type="email"], input[placeholder*="mail"], input[placeholder*="账号"], input[placeholder*="Email"]'
        pwd_sel   = 'input[type="password"]'
        page.wait_for_selector(email_sel, timeout=8000)
        page.fill(email_sel, username)
        page.fill(pwd_sel, password)

        # Clicar em login
        page.click('button[type="submit"], button:has-text("登录"), button:has-text("Login")')
        page.wait_for_load_state("networkidle")
        time.sleep(2)
        return "/login" not in page.url
    except Exception as e:
        print(f"   ⚠️  Sungrow login erro: {e}")
        return False


def sungrow_fetch_playwright(username: str = "", password: str = "") -> dict | None:
    """
    Acessa iSolarCloud com sessão persistente e lê a geração de hoje da lista de usinas.
    Retorna { "hoje_kwh": float, "plantas": [...] } ou None.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("❌ playwright não instalado. Execute: pip install playwright && playwright install chromium")
        return None

    u  = username or SUNGROW_USERNAME
    pw = password or SUNGROW_PASSWORD
    if not u or not pw:
        print("⚠️  SUNGROW credenciais não configuradas em Inversores/.env")
        return None

    print("🔌 Sungrow (gama 2): conectando via Playwright...")
    SUNGROW_SESSION_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(SUNGROW_SESSION_DIR),
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        # Checar sessão
        page.goto(f"{SUNGROW_BASE}/#/plantList", wait_until="load", timeout=60_000)
        time.sleep(2)

        if "/login" in page.url or "login" in page.url.lower():
            print("   ℹ️  Sungrow: sem sessão — fazendo login...")
            ok = _sungrow_login(page, u, pw)
            if not ok:
                print("❌ Sungrow: falha no login")
                ctx.close()
                return None

        plants = _sungrow_read_plant_list(page)
        ctx.close()

    if not plants:
        print("❌ Sungrow: nenhuma planta encontrada no DOM")
        return None

    hoje_total = sum(p["hoje_kwh"] for p in plants)
    for plant in plants:
        print(f"   📊 Sungrow {plant['nome']}: hoje={plant['hoje_kwh']:.2f} kWh")

    return {"hoje_kwh": hoje_total, "plantas": plants}


# ══════════════════════════════════════════════════════════════════════════════
# CLI de teste
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "ambos"

    if cmd in ("tsun", "escola", "ambos"):
        result = tsun_fetch_playwright()
        if result:
            print(f"\n✅ TSUN total hoje: {result['hoje_kwh']:.3f} kWh")
        else:
            print("\n❌ TSUN falhou")

    if cmd in ("sungrow", "gama2", "ambos"):
        result = sungrow_fetch_playwright()
        if result:
            print(f"\n✅ Sungrow total hoje: {result['hoje_kwh']:.2f} kWh")
        else:
            print("\n❌ Sungrow falhou")
