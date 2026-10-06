#!/usr/bin/env python3
"""Fixed 2D UMAP layout per leaflet from the cached embeddings, for the "point cloud" view
(plan Abschnitt 11, zurückgestellt). No API calls, no topic run needed: only the embedding
model and the seed decide the coordinates.

    python pipelines/04_topic/topic_map.py [--model baai/bge-m3]

Writes data/topics/topic_map.json: one record per leaflet (stem, start_page, end_page, x, y),
identified the same way export_topics.py identifies leaflets.
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import leaflet_topics as lt  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_PATH = REPO_ROOT / "data" / "topics" / "topic_map.json"


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--model", default="baai/bge-m3")
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()

    leaflets = lt.load_leaflets()
    cache = lt.load_cache(lt.CACHE_DIR / f"{args.model.replace('/', '__')}.npz")
    keys = [lt.text_key(lf["text"]) for lf in leaflets]
    missing = sum(k not in cache for k in keys)
    if missing:
        sys.exit(f"{missing} von {len(leaflets)} Flugblättern fehlen im Embeddings-Cache "
                 f"({args.model}); zuerst leaflet_topics.py --embed-only laufen lassen.")
    vectors = np.stack([cache[k] for k in keys])

    from umap import UMAP  # noqa: E402
    xy = UMAP(n_neighbors=15, n_components=2, min_dist=0.1, metric="cosine",
             random_state=args.seed).fit_transform(vectors)

    out = [{"stem": lf["stem"], "start_page": lf["start_page"], "end_page": lf["end_page"],
           "x": round(float(x), 3), "y": round(float(y), 3)}
          for lf, (x, y) in zip(leaflets, xy)]
    assert len(out) == len(leaflets)
    assert len({(r["stem"], r["start_page"], r["end_page"]) for r in out}) == len(out)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"-> {OUT_PATH.relative_to(REPO_ROOT)}: {len(out)} Flugblätter")


if __name__ == "__main__":
    main()
