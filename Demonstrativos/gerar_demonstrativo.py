import sys, textwrap
from PIL import Image, ImageDraw, ImageFont

# ---------- Paleta ----------
NAVY        = (13, 27, 56)      # fundo principal
NAVY_CARD   = (20, 38, 74)      # cartões/linhas
NAVY_LINE   = (40, 58, 92)      # divisórias
WHITE       = (255, 255, 255)
LIGHT       = (200, 210, 226)   # texto secundário
GOLD        = (224, 168, 62)    # destaque "Valor Total do Boleto"
GOLD_DARK   = (15, 22, 38)      # texto sobre dourado
GREEN       = (84, 196, 138)    # economia

FONT_DIR = "/usr/share/fonts/truetype/dejavu/"
def F(name, size):
    return ImageFont.truetype(FONT_DIR + name, size)

def text_w(draw, txt, font):
    return draw.textbbox((0,0), txt, font=font)[2]

def center_text(draw, cx, y, txt, font, fill):
    w = text_w(draw, txt, font)
    draw.text((cx - w/2, y), txt, font=font, fill=fill)
    return w

def fmt_brl(v):
    s = f"{v:,.2f}"
    s = s.replace(",", "_").replace(".", ",").replace("_", ".")
    return f"R$ {s}"

def fmt_kwh(v):
    s = f"{v:,.2f}"
    s = s.replace(",", "_").replace(".", ",").replace("_", ".")
    return f"{s} kWh"

def gerar_demonstrativo(
    cliente, uc, tipo, desconto_pct,
    consumo_total_kwh, valor_equatorial, valor_luzi_energia,
    valor_total_boleto, valor_sem_luzi, economia_cliente,
    vencimento, mes_referencia, output_path
):
    W, H = 1000, 1280
    img = Image.new("RGB", (W, H), NAVY)
    d = ImageDraw.Draw(img)
    cx = W // 2

    f_logo_big   = F("DejaVuSans-Bold.ttf", 64)
    f_logo_small = F("DejaVuSans-Bold.ttf", 30)
    f_header     = F("DejaVuSans-Bold.ttf", 30)
    f_sub        = F("DejaVuSans.ttf", 22)
    f_label      = F("DejaVuSans.ttf", 24)
    f_value      = F("DejaVuSans-Bold.ttf", 26)
    f_total_lbl  = F("DejaVuSans-Bold.ttf", 24)
    f_total_val  = F("DejaVuSans-Bold.ttf", 56)
    f_foot       = F("DejaVuSans.ttf", 18)

    y = 70
    # ---------- Logo ----------
    center_text(d, cx, y, "LUZI", f_logo_big, WHITE)
    y += 78
    w = center_text(d, cx, y, "E N E R G I A", f_logo_small, WHITE)
    y += 60

    d.line([(80, y), (W-80, y)], fill=NAVY_LINE, width=2)
    y += 40

    # ---------- Cabeçalho do cliente ----------
    center_text(d, cx, y, f"Cliente: {cliente}", f_header, WHITE)
    y += 40
    sub = f"UC {uc}  ·  {tipo}  ·  {desconto_pct}% de desconto"
    center_text(d, cx, y, sub, f_sub, LIGHT)
    y += 36
    center_text(d, cx, y, f"Referência: {mes_referencia}", f_sub, LIGHT)
    y += 50

    center_text(d, cx, y, "DEMONSTRATIVO DE ECONOMIA", f_total_lbl, GOLD)
    y += 50

    # ---------- Linhas da tabela ----------
    rows = [
        ("Consumo Total", fmt_kwh(consumo_total_kwh)),
        ("Valor Equatorial", fmt_brl(valor_equatorial)),
        ("Valor Luzi Energia", fmt_brl(valor_luzi_energia)),
    ]
    row_h = 64
    pad_x = 70
    for label, value in rows:
        d.rectangle([pad_x, y, W-pad_x, y+row_h-10], fill=NAVY_CARD)
        d.text((pad_x+30, y+15), label, font=f_label, fill=LIGHT)
        vw = text_w(d, value, f_value)
        d.text((W-pad_x-30-vw, y+13), value, font=f_value, fill=WHITE)
        y += row_h

    y += 20

    # ---------- VALOR TOTAL DO BOLETO (destaque) ----------
    box_h = 170
    d.rounded_rectangle([pad_x-10, y, W-pad_x+10, y+box_h], radius=22, fill=GOLD)
    center_text(d, cx, y+24, "VALOR TOTAL DO BOLETO", f_total_lbl, GOLD_DARK)
    center_text(d, cx, y+62, fmt_brl(valor_total_boleto), f_total_val, GOLD_DARK)
    y += box_h + 30

    # ---------- Linhas finais ----------
    rows2 = [
        ("Valor que pagaria sem Luzi", fmt_brl(valor_sem_luzi)),
        ("Economia do Cliente", fmt_brl(economia_cliente)),
        ("Desconto Aplicado", f"{desconto_pct}%"),
    ]
    for label, value in rows2:
        d.rectangle([pad_x, y, W-pad_x, y+row_h-10], fill=NAVY_CARD)
        d.text((pad_x+30, y+15), label, font=f_label, fill=LIGHT)
        vw = text_w(d, value, f_value)
        color = GREEN if label == "Economia do Cliente" else WHITE
        d.text((W-pad_x-30-vw, y+13), value, font=f_value, fill=color)
        y += row_h

    y += 16
    d.rounded_rectangle([pad_x, y, W-pad_x, y+row_h-10], radius=10, outline=GOLD, width=2)
    d.text((pad_x+30, y+15), "Vencimento", font=f_label, fill=LIGHT)
    vw = text_w(d, vencimento, f_value)
    d.text((W-pad_x-30-vw, y+13), vencimento, font=f_value, fill=GOLD)
    y += row_h + 50

    d.line([(80, y), (W-80, y)], fill=NAVY_LINE, width=1)
    y += 20
    center_text(d, cx, y, "Luzi Energia · Anápolis, GO", f_foot, LIGHT)

    img.save(output_path)
    return output_path

if __name__ == "__main__":
    print("módulo gerar_demonstrativo.py carregado.")
