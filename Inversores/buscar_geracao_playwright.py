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
SUNGROW_USERNAME  = os.getenv("SUNGROW_USERNAME", "")
SUNGROW_PASSWORD  = os.getenv("SUNGROW_PASSWORD", "")

# Diretórios de sessão persistente (cookies salvos entre execuções)
TSUN_SESSION_DIR     = BASE_DIR / "sessions" / "tsun"
SUNGROW_SESSION_DIR  = BASE_DIR / "sessions" / "sungrow"


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


def _tsun_do_login(page, username: str, password: str) -> str | None:
    """
    Preenche o formulário de login TSUN, resolve o captcha e retorna
    o access_token OAuth2 interceptado da resposta de rede.
    """
    token_box: dict = {"token": None}

    def _on_response(response):
        if "oauth2-s/oauth/token" in response.url:
            try:
                data = response.json()
                t = data.get("access_token")
                if t:
                    token_box["token"] = t
            except Exception:
                pass

    page.on("response", _on_response)

    page.goto(f"{TSUN_BASE}/login", wait_until="networkidle")

    # Clicar na aba "邮箱" (Email) — índice 1 entre as 3 abas
    tabs = page.locator('[role="tab"]')
    if tabs.count() >= 2:
        tabs.nth(1).click()
    time.sleep(0.4)

    # Preencher credenciais
    page.fill('input[placeholder="邮箱"]', username)
    page.fill('input[type="password"]', password)

    # Resolver slider
    ok = _tsun_drag_slider(page)
    if not ok:
        # Tentar uma segunda vez (às vezes o slider precisa de retry)
        time.sleep(1)
        ok = _tsun_drag_slider(page)
        if not ok:
            return None

    # Clicar em "登 录" (Login)
    page.click('button:has-text("登")')
    time.sleep(3.5)

    # Fechar dialog "终端用户不允许登录" (usuário final não pode usar web portal)
    # O token OAuth2 já foi capturado antes do dialog aparecer
    for sel in ['button:has-text("确定")', 'button:has-text("确 定")', 'button:has-text("OK")']:
        try:
            if page.locator(sel).count() > 0:
                page.click(sel)
                break
        except Exception:
            pass

    return token_box.get("token")




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
    Login TSUN com sessão persistente + slider captcha.
    Intercepta TODAS as respostas JSON do portal enquanto carrega,
    extrai dados de geração sem precisar conhecer o endpoint exato.
    Retorna { "hoje_kwh": float, "estacoes": [...] } ou None.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("❌ playwright não instalado. Execute: pip install playwright && playwright install chromium")
        return None

    u = username or TSUN_USERNAME
    pw = password or TSUN_PASSWORD
    if not u or not pw:
        print("⚠️  TSUN credenciais não configuradas em Inversores/.env")
        return None

    print("🔌 TSUN (escola): conectando via Playwright...")
    TSUN_SESSION_DIR.mkdir(parents=True, exist_ok=True)

    captured: dict = {"today_kwh": None}

    def _on_response(response):
        url = response.url
        # Ignorar recursos estáticos
        if any(s in url for s in (".js", ".css", ".png", ".jpg", ".ico", ".woff", ".svg")):
            return
        ct = response.headers.get("content-type", "")
        if "json" not in ct:
            return
        try:
            data = response.json()
            _tsun_extract_energy(url, data, captured)
        except Exception:
            pass

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

        # Interceptar ANTES de qualquer navegação
        page.on("response", _on_response)

        page.goto(f"{TSUN_BASE}/", wait_until="networkidle")
        time.sleep(1.5)

        if "/login" in page.url or "login" in page.url.lower():
            print("   ℹ️  TSUN: sem sessão — fazendo login...")
            token = _tsun_do_login(page, u, pw)
            if not token:
                print("❌ TSUN: falha no login (captcha ou credenciais)")
                ctx.close()
                return None
            print("   ✅ TSUN: login OK")
            # Navegar para o dashboard — as APIs serão chamadas automaticamente
            page.goto(f"{TSUN_BASE}/", wait_until="networkidle")
            time.sleep(3)
        else:
            print("   ℹ️  TSUN: sessão ativa")

        # Se ainda não capturou, navegar por algumas rotas do SPA para triggar as APIs
        if captured["today_kwh"] is None:
            for route in ["/home", "/station/list", "/dashboard", "/overview"]:
                try:
                    page.goto(f"{TSUN_BASE}{route}", wait_until="networkidle")
                    time.sleep(2)
                    if captured["today_kwh"] is not None:
                        break
                except Exception:
                    continue

        # Último recurso: DOM scraping
        if captured["today_kwh"] is None:
            body = page.evaluate("() => document.body.innerText") or ""
            matches = re.findall(r"([\d]+\.?\d*)\s*(?:kWh|度|kwh)", body)
            if matches:
                captured["today_kwh"] = float(matches[0])
                print(f"   📊 TSUN (DOM): {captured['today_kwh']:.3f} kWh")

        ctx.close()

    kwh = captured.get("today_kwh")
    if kwh is None:
        print("❌ TSUN: nenhum dado de geração encontrado")
        return None

    print(f"   📊 TSUN Escola: hoje={kwh:.3f} kWh")
    return {"hoje_kwh": kwh, "estacoes": [{"nome": "Escola", "hoje_kwh": kwh}]}



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
    page.goto(f"{SUNGROW_BASE}/#/plantList", wait_until="networkidle")
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
    page.goto(SUNGROW_BASE, wait_until="networkidle")
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
        page.goto(f"{SUNGROW_BASE}/#/plantList", wait_until="networkidle")
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
