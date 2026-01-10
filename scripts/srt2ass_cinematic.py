#!/usr/bin/env python3
import pysubs2
import re
import sys
import os

# === Uso ===
# python3 srt2ass_karaoke.py input.srt output.ass width height
if len(sys.argv) < 5:
    print("Uso: python3 srt2ass_karaoke.py input.srt output.ass width height")
    sys.exit(1)

insrt, outass, width, height = sys.argv[1:5]

# === Checagens ===
if not os.path.exists(insrt):
    sys.exit(f"❌ Arquivo SRT não encontrado: {insrt}")

# === Carregar SRT ===
subs = pysubs2.load(insrt, encoding="utf-8")

# === Estilo Cinematográfico ===
style = pysubs2.SSAStyle(
    fontname="Montserrat",              # Arial Black como fallback
    fontsize=60 if int(height) >= 1080 else 45,  # ajusta automaticamente
    primarycolor=pysubs2.Color(255, 255, 255, 0),  # branco
    outlinecolor=pysubs2.Color(0, 0, 0, 0),        # contorno preto
    backcolor=pysubs2.Color(0, 0, 0, 0),           # sem fundo
    bold=True,
    italic=False,
    underline=False,
    borderstyle=1,
    outline=4 if int(height) >= 1080 else 3,
    shadow=1,
    alignment=2,      # centro inferior
    marginl=20,
    marginr=20,
    marginv=70 if int(height) >= 1080 else 50      # sobe um pouco em 1080p
)
subs.styles["Cinematic"] = style

# === Funções auxiliares ===
def strip_tags(text: str) -> str:
    """Remove tags HTML/SSA e limpa espaços extras."""
    return re.sub(r"<.*?>|\{\\.*?\}", "", text).strip()

# === Aplicar formatação no texto ===
for ev in subs.events:
    ev.style = "Cinematic"
    clean_text = strip_tags(ev.text)
    # quebra frases muito longas em 2 linhas se necessário
    if len(clean_text) > 45:
        words = clean_text.split()
        mid = len(words) // 2
        clean_text = " ".join(words[:mid]) + "\\N" + " ".join(words[mid:])
    ev.text = "{\\fad(200,200)}" + clean_text.upper()

# === Resolução ===
if isinstance(subs.info, dict):
    subs.info["PlayResX"] = int(width)
    subs.info["PlayResY"] = int(height)
else:
    subs.info.playresx = int(width)
    subs.info.playresy = int(height)

# === Salvar ===
subs.save(outass)
print(f"✅ Arquivo ASS cinematográfico gerado com sucesso:\n   {outass}")
