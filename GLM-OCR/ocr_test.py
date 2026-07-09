import fitz  # PyMuPDF
from openai import OpenAI
import base64
import json
import os

# erstellt von claude.ai

# --- Einstellungen ---
PDF_PATH = "data/test_set/test_set.pdf"          # Pfad zu deinem PDF anpassen
DPI = 200
PROMPT = "Text Recognition:"

# Ausgabeschema wie data/<pdf_stem>/jsonDatalab/: data/<pdf_stem>/jsonGLM/
PDF_STEM = os.path.splitext(os.path.basename(PDF_PATH))[0]
OUTPUT_DIR = os.path.join(os.path.dirname(PDF_PATH), PDF_STEM, "jsonGLM")
OUTPUT_JSON_PATH = os.path.join(OUTPUT_DIR, f"{PDF_STEM}.json")

os.makedirs(OUTPUT_DIR, exist_ok=True)

# --- Schritt 1: Alle Seiten als PNG extrahieren ---
print("Extrahiere Seiten aus PDF...")
doc = fitz.open(PDF_PATH)
image_paths = []
for i, page in enumerate(doc):
    pix = page.get_pixmap(dpi=DPI)
    img_path = os.path.join(OUTPUT_DIR, f"seite_{i+1:03d}.png")
    pix.save(img_path)
    image_paths.append(img_path)
print(f"{len(image_paths)} Seiten extrahiert.")

# --- Schritt 2: Jede Seite durch OCR schicken ---
client = OpenAI(base_url="http://localhost:8080/v1", api_key="none")

results = []
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
    results.append({
        "page": i + 1,
        "image_path": img_path,
        "text": result_text,
    })

with open(OUTPUT_JSON_PATH, "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

print("Fertig! Ergebnisse gespeichert in:", OUTPUT_JSON_PATH)