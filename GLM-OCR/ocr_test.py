import fitz  # PyMuPDF
from openai import OpenAI
import base64
import os

# erstellt von claude.ai

# --- Einstellungen ---
PDF_PATH = PDF_PATH = "C:/Users/Anwender/Downloads/test_set.pdf"          # Pfad zu deinem PDF anpassen
OUTPUT_IMG_DIR = "seiten"       # Ordner für die extrahierten Bilder
OUTPUT_TXT_DIR = "ergebnisse"   # Ordner für die OCR-Ergebnisse
DPI = 200
PROMPT = "Text Recognition:"

os.makedirs(OUTPUT_IMG_DIR, exist_ok=True)
os.makedirs(OUTPUT_TXT_DIR, exist_ok=True)

# --- Schritt 1: Alle Seiten als PNG extrahieren ---
print("Extrahiere Seiten aus PDF...")
doc = fitz.open(PDF_PATH)
image_paths = []
for i, page in enumerate(doc):
    pix = page.get_pixmap(dpi=DPI)
    img_path = os.path.join(OUTPUT_IMG_DIR, f"seite_{i+1:03d}.png")
    pix.save(img_path)
    image_paths.append(img_path)
print(f"{len(image_paths)} Seiten extrahiert.")

# --- Schritt 2: Jede Seite durch OCR schicken ---
client = OpenAI(base_url="http://localhost:8080/v1", api_key="none")

for i, img_path in enumerate(image_paths):
    print(f"Verarbeite Seite {i+1}/{len(image_paths)}: {img_path}")
    with open(img_path, "rb") as f:
        b64_image = base64.b64encode(f.read()).decode("utf-8")

    response = client.chat.completions.create(
        model="glm-ocr",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": PROMPT},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64_image}"}}
                ]
            }
        ]
    )

    result_text = response.choices[0].message.content
    out_path = os.path.join(OUTPUT_TXT_DIR, f"seite_{i+1:03d}.txt")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(result_text)

print("Fertig! Ergebnisse liegen im Ordner:", OUTPUT_TXT_DIR)