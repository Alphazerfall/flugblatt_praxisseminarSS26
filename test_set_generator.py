import os
import random
import fitz  # PyMuPDF

PDF_FOLDER = r"C:\path\to\your\pdf_folder" # Pfad zum Ordner, der alle PDF-Dateien enthält

AMOUNT_OF_PAGES = 20  # Anzahl der Seiten, die aus jedem Jahr extrahiert werden sollen

# Liste der PDFs nach Jahr (evtl. anpassen, je nachdem, wie die PDFs benannt sind)
# Zum entfernen von PDFs, die nicht existieren, einfach die entsprechenden Einträge löschen/auskommentieren.
PDFS_BY_YEAR = {
    1968: ["1968.pdf"],
    1969: ["1969.pdf"],
    1970: ["1970.pdf"],
    1971: ["1971.pdf"],
    1972: ["1972_1.pdf", "1972_2.pdf", "1972_3.pdf", "1972_4.pdf"],
    1973: ["1973_1.pdf", "1973_2.pdf", "1973_3.pdf", "1973_4.pdf", "1973_5.pdf"],
}

def extract_20_random_pages(year):
    docs = [fitz.open(os.path.join(PDF_FOLDER, pdf)) for pdf in PDFS_BY_YEAR[year]]
    pages = [(doc, i) for doc in docs for i in range(len(doc))]
    selected = random.sample(pages, min(AMOUNT_OF_PAGES, len(pages)))
    return selected

    
def main():

    out = fitz.open()   

    for year in range(1968, 1974):
        selected = extract_20_random_pages(year)

        for doc, page_num in selected:
            out.insert_pdf(doc, from_page=page_num, to_page=page_num)
    
    out.save(f"test_set.pdf")
    out.close()



if __name__ == "__main__":
    main()
