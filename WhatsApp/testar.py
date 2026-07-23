"""
Teste rápido — envia mensagem/PNG para o seu próprio WhatsApp.
Execute: python3 testar.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from enviar_whatsapp import _enviar
from pathlib import Path

NUMERO = "5562999741225"   # seu número

# Busca o primeiro PNG disponível em Demonstrativos/
DEMOS_DIR = Path(__file__).parent.parent / "Demonstrativos"
pngs = sorted(DEMOS_DIR.glob("*.png"))

if not pngs:
    print("❌ Nenhum PNG encontrado em Demonstrativos/")
    sys.exit(1)

png = str(pngs[0])
print(f"📎 Usando: {pngs[0].name}")

_enviar(
    numero=NUMERO,
    texto="✅ Teste Luzi Energia — demonstrativo enviado automaticamente!",
    arquivo_png=png,
)
