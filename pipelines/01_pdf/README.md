# TIFF scans -> one PDF

Turn a folder of TIFF scans into a single PDF matching the Rep. 118 reference (RGB, JPEG q75, 400 DPI).

```bash
pip install pillow img2pdf
python tiff_to_pdf.py "path/to/Nr. 014 (1973)"
```

Output is `<folder-name>.pdf` inside the folder. Defaults match the reference; override with `-q` (quality), `-d` (DPI), `-o` (output path), `--keep-jpeg` (keep intermediate JPEGs).

Check it: `pdfinfo file.pdf` (pages, size), `pdfimages -list file.pdf` (per-page DPI/encoding).


# Merge by year