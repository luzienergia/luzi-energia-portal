"""
Teste: envia fatura Sobreloja (equatorial_direto) para o próprio WhatsApp.
UC 000078431901209  R$ 141,08  Vencimento 03/08/2026
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from enviar_whatsapp import _enviar
from pathlib import Path

NUMERO = "5562999741225"  # Luiz (próprio)

PNG = str(Path(__file__).parent.parent / "Demonstrativos" / "demonstrativo_sobreloja_07-2026.png")

TEXTO = (
    "⚡ *Fatura Equatorial — 07/2026*\n\n"
    "🏢 Imóvel: Sobreloja\n"
    "📋 UC: 000078431901209\n"
    "💰 *Valor: R$ 141,08*\n"
    "📅 Vencimento: 03/08/2026\n\n"
    "Pague pelo app Equatorial, PIX ou boleto em anexo (PDF no email).\n\n"
    "☀️ Luzi Energia"
)

print(f"📱 Enviando para {NUMERO}...")
print(f"📎 PNG: {PNG}")
_enviar(numero=NUMERO, texto=TEXTO, arquivo_png=PNG)
