"""
enviar_whatsapp.py — Envia mensagem e PNG via WhatsApp Web (Playwright)
=======================================================================
Funciona com sessão persistente: escaneie o QR code uma única vez e o
script reutiliza a sessão automaticamente nas próximas execuções.

Uso direto no terminal:
  python3 enviar_whatsapp.py

Ou importado por outro script:
  from enviar_whatsapp import enviar_boleto_cliente, enviar_equatorial_direto
"""

from __future__ import annotations
import os, time, json
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# ── Caminhos ────────────────────────────────────────────────────────────────
BASE_DIR      = Path(__file__).parent.parent          # .../Sistema Luzi Energia/
SESSION_DIR   = Path.home() / ".luzienergia_wpp"      # sessão WhatsApp salva
CLIENTES_FILE = BASE_DIR / "clientes.json"
DEMOS_DIR     = BASE_DIR / "Demonstrativos"

# ── Carregar cadastro de clientes ───────────────────────────────────────────
def _carregar_clientes() -> dict:
    with open(CLIENTES_FILE, encoding="utf-8") as f:
        return json.load(f)

def _buscar_cliente(nome: str) -> dict:
    dados = _carregar_clientes()
    for c in dados["clientes"]:
        if c["nome"].lower() == nome.lower():
            return c
    raise ValueError(f"Cliente '{nome}' não encontrado em clientes.json")

# ── Núcleo: abre WhatsApp Web e envia ───────────────────────────────────────
def _enviar(numero: str, texto: str, arquivo_png: str | None = None):
    """
    Abre WhatsApp Web, navega para o número e envia texto + opcional PNG.
    Na primeira execução: escaneia QR code.  Depois: sessão salva.
    """
    SESSION_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(SESSION_DIR),
            headless=False,                   # mostra o navegador
            args=["--no-sandbox", "--disable-dev-shm-usage"],
            slow_mo=200,                      # pequena pausa entre ações
        )
        page = ctx.new_page()

        # ── Passo 1: abre WhatsApp Web principal ─────────────────────────
        print("📱 Abrindo WhatsApp Web...")
        page.goto("https://web.whatsapp.com", wait_until="domcontentloaded")

        # ── Passo 2: aguarda login (QR ou sessão salva) ──────────────────
        print("⏳ Aguardando login (escaneia QR se pedido — pode levar até 2 min)...")
        try:
            # Aguarda a lista de conversas aparecer (prova que está logado)
            page.wait_for_selector(
                '[data-testid="chat-list"], [aria-label="Lista de conversas"]',
                timeout=120_000
            )
            print("✅ WhatsApp logado!")
        except PWTimeout:
            print("❌ Não foi possível fazer login. Tente novamente.")
            ctx.close()
            return False

        time.sleep(2)

        # ── Passo 3: navega para o número ────────────────────────────────
        print(f"📲 Abrindo conversa com {numero}...")
        page.goto(
            f"https://web.whatsapp.com/send?phone={numero}",
            wait_until="domcontentloaded"
        )

        # ── Passo 4: aguarda a caixa de mensagem ─────────────────────────
        try:
            page.wait_for_selector(
                '[data-testid="conversation-compose-box-input"]',
                timeout=30_000
            )
        except PWTimeout:
            print("❌ Conversa não abriu. Verifique se o número está correto.")
            ctx.close()
            return False

        time.sleep(1)

        # ── Envia PNG se fornecido ───────────────────────────────────────
        if arquivo_png and os.path.exists(arquivo_png):
            print(f"🖼️  Anexando demonstrativo: {os.path.basename(arquivo_png)}")

            import subprocess

            # Copia PNG para o clipboard do macOS
            subprocess.run([
                "osascript", "-e",
                f'set the clipboard to (read (POSIX file "{arquivo_png}") as «class PNGf»)'
            ], check=True)
            time.sleep(0.5)

            # Cola na caixa de mensagem (Cmd+V)
            caixa = page.locator('[data-testid="conversation-compose-box-input"]')
            caixa.click()
            page.keyboard.press("Meta+V")
            time.sleep(3)   # aguarda o preview carregar

            # Pressiona Enter para enviar a imagem (sem legenda)
            page.keyboard.press("Enter")
            print("📤 Imagem enviada!")
            time.sleep(1)

            # Envia o texto como mensagem separada
            caixa2 = page.locator('[data-testid="conversation-compose-box-input"]')
            caixa2.click()
            caixa2.type(texto, delay=20)
            time.sleep(0.5)
            page.keyboard.press("Enter")
            print("✅ PNG + mensagem enviados!")

        else:
            # ── Só texto ─────────────────────────────────────────────────
            print("💬 Enviando mensagem de texto...")
            caixa = page.locator('[data-testid="conversation-compose-box-input"]')
            caixa.click()
            caixa.type(texto, delay=20)
            time.sleep(0.5)
            page.keyboard.press("Enter")
            print("✅ Mensagem enviada!")

        time.sleep(2)   # aguarda envio confirmar
        ctx.close()
        return True


# ── API pública ──────────────────────────────────────────────────────────────

def enviar_boleto_cliente(
    nome_cliente: str,
    valor: float,
    vencimento: str,       # "DD/MM/AAAA"
    mes_referencia: str,   # "MM/AAAA"
    linha_digitavel: str,
    arquivo_png: str | None = None,
):
    """
    Envia demonstrativo PNG + linha digitável para um cliente ativo da Luzi.
    Busca o número de WhatsApp automaticamente do clientes.json.
    """
    cliente = _buscar_cliente(nome_cliente)

    if cliente.get("acao_boleto") != "luzi_boleto_e_png":
        print(f"⚠️  {nome_cliente} não recebe boleto Luzi (ação: {cliente.get('acao_boleto')}). Abortando.")
        return False

    numero = cliente["whatsapp_numero"]
    if not numero or numero == "PENDENTE":
        print(f"❌ WhatsApp de {nome_cliente} não cadastrado.")
        return False

    nome_exibir = cliente.get("nome_cliente", nome_cliente)

    texto = (
        f"Olá, {nome_exibir}! 👋\n\n"
        f"Segue o demonstrativo de energia solar referente a *{mes_referencia}*.\n\n"
        f"💰 *Valor do boleto:* R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") +
        f"\n📅 *Vencimento:* {vencimento}\n\n"
        f"*Linha de pagamento:*\n{linha_digitavel}\n\n"
        f"Qualquer dúvida, estou à disposição! ☀️"
    )

    print(f"\n📤 Enviando para {nome_exibir} ({nome_cliente}) — {numero}")
    return _enviar(numero, texto, arquivo_png)


def enviar_lembrete_vencimento(
    nome_cliente: str,
    valor: float,
    linha_digitavel: str,
    mes_referencia: str,
):
    """
    Envia lembrete D-1 de vencimento (apenas texto, sem PNG).
    """
    cliente = _buscar_cliente(nome_cliente)
    numero  = cliente["whatsapp_numero"]

    if not numero or numero == "PENDENTE":
        print(f"❌ WhatsApp de {nome_cliente} não cadastrado.")
        return False

    nome_exibir = cliente.get("nome_cliente", nome_cliente)
    valor_fmt   = f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    texto = (
        f"Olá, {nome_exibir}! 👋\n\n"
        f"Seu boleto de energia solar *({mes_referencia})* no valor de *{valor_fmt}* "
        f"vence *amanhã*.\n\n"
        f"*Linha de pagamento:*\n{linha_digitavel}\n\n"
        f"Qualquer dúvida é só chamar! ☀️"
    )

    print(f"\n⏰ Lembrete D-1 → {nome_exibir} ({numero})")
    return _enviar(numero, texto)


def enviar_equatorial_direto(
    contato_wpp: str,     # nome do contato no WhatsApp (ex: "Eu", "Dindinho")
    numero_wpp: str,      # número com DDI (ex: "5562999991234")
    mes_referencia: str,
    linha_digitavel: str | None = None,
    arquivo_pdf_path: str | None = None,
):
    """
    Encaminha o boleto da Equatorial direto para o contato (próprios de Luiz
    ou pass-through como Apto 300, Térreo, Casa Marrula etc).
    """
    texto = (
        f"Fatura Equatorial — *{mes_referencia}* ☀️\n"
    )
    if linha_digitavel:
        texto += f"\n*Linha de pagamento:*\n{linha_digitavel}"

    print(f"\n📨 Equatorial direto → {contato_wpp} ({numero_wpp})")
    return _enviar(numero_wpp, texto, arquivo_pdf_path)


# ── Teste manual ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 55)
    print("  TESTE — Envio WhatsApp Luzi Energia")
    print("=" * 55)
    print("\nEscolha o teste:")
    print("  1. Enviar mensagem de texto simples para 'Eu'")
    print("  2. Enviar PNG de demonstrativo para 'Eu'")
    opcao = input("\nOpção (1 ou 2): ").strip()

    # Número de Luiz (lido do clientes.json como whatsapp_numero do "Apto 100")
    # Para teste, usa o número direto
    numero_luiz = input("Seu número completo com DDI (ex: 5562999741225): ").strip()

    if opcao == "1":
        _enviar(
            numero=numero_luiz,
            texto="✅ Teste do sistema Luzi Energia — mensagem automática funcionando!",
        )
    elif opcao == "2":
        # Busca o primeiro PNG de demonstrativo disponível
        pngs = list(DEMOS_DIR.glob("*.png"))
        if not pngs:
            print("❌ Nenhum PNG encontrado em Demonstrativos/")
        else:
            png = str(pngs[0])
            print(f"📎 Usando: {pngs[0].name}")
            _enviar(
                numero=numero_luiz,
                texto="✅ Teste Luzi Energia — demonstrativo enviado automaticamente!",
                arquivo_png=png,
            )
