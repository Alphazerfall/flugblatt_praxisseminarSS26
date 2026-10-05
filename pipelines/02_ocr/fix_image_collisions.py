"""Repairs Datalab picture files that a later batch overwrote.

Batched conversions restart the page ids in every batch, so pictures of different
batches could get the same file name, and only the last one was saved. Each
Picture block of the JSON still holds its own image data, so every picture with a
shared name gets a unique name and its file is written again from that data.
The JSON is backed up once as <stem>.json.bak.

    python fix_image_collisions.py "data/raw/Nr. 009 (1972)/0118_0009" [more folders]
"""
import base64
import hashlib
import json
import re
import shutil
import sys
from collections import Counter
from pathlib import Path

SRC = re.compile(r'src="([^"]+)"')


def pictures(doc):
    """(page number in the merged document, Picture block)"""
    for page_no, page in enumerate(doc.get("children") or [], start=1):
        for block in page.get("children") or []:
            if block.get("block_type") == "Picture":
                yield page_no, block


def unique_name(page_no, name):
    """Same pattern as Datalab's names ('<32 hex>_img.jpg'), which the app expects."""
    return hashlib.md5(f"{page_no}/{name}".encode()).hexdigest() + name[name.find("_"):]


def unique_batch_images(result, key, batch_no):
    """Prevents the collision in new conversions: names of a batch result made unique."""
    images = result.get("images") or {}
    names = {n: unique_name(f"batch{batch_no}", n) for n in images}
    content = json.dumps(result[key])
    for old, new in names.items():
        content = content.replace(old, new)
    return {**result, key: json.loads(content), "images": {names[n]: b for n, b in images.items()}}


def fix_doc(doc):
    """Renames pictures with shared names in place; returns {new name: image bytes}."""
    shared = Counter(n for _, b in pictures(doc) for n in SRC.findall(b.get("html", "")))
    files = {}
    for page_no, block in pictures(doc):
        for name in SRC.findall(block.get("html", "")):
            if shared[name] < 2 or name not in (block.get("images") or {}):
                continue
            new = unique_name(page_no, name)
            files[new] = base64.b64decode(block["images"][name])
            block["html"] = block["html"].replace(name, new)
            block["images"][new] = block["images"].pop(name)
    return files


def fix_folder(folder):
    folder = Path(folder)
    path = folder / f"{folder.name}.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    files = fix_doc(doc)
    if files:
        backup = path.with_name(path.name + ".bak")
        if not backup.exists():
            shutil.copy2(path, backup)
        for name, data in files.items():
            (folder / name).write_bytes(data)
        path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{folder}: {len(files)} pictures renamed")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    for arg in sys.argv[1:]:
        fix_folder(arg)
