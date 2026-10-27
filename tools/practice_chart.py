"""Exploratory practice calls for the chart reader (not part of any pre-registered test). Orchestrator tooling.

  uv run python tools/practice_chart.py <image.png> <tag> "<prompt 1>" ["<prompt 2>" ...]

Sends one SAM 3.1 call per prompt through the production adapter, saves every mask to
runs/chart_practice/<tag>__<prompt>.npz and appends a summary line to docs/smoke/chart_practice.jsonl.
"""
import json
import os
import pathlib
import sys
import time

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from autosolar.chart_reader import sam_segment_fn  # noqa: E402
from autosolar.ledger import Ledger  # noqa: E402
from autosolar.meta_client import MetaClient  # noqa: E402


def main(image, tag, prompts):
    env_file = pathlib.Path(os.environ.get("AUTOSOLAR_ENV_FILE", ROOT / ".env"))
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if line.startswith("MODEL_API_KEY="):
            os.environ["MODEL_API_KEY"] = line.split("=", 1)[1].strip()
    client = MetaClient(Ledger(ROOT / "ledger" / "api_usage.jsonl"), timeout_s=180.0)
    seg = sam_segment_fn(client, "chart-practice", stage="practice-sam")
    png = pathlib.Path(image).read_bytes()
    out_dir = ROOT / "runs" / "chart_practice"
    out_dir.mkdir(parents=True, exist_ok=True)
    for prompt in prompts:
        objs = seg(png, prompt)
        slug = prompt.replace(" ", "_")
        np.savez_compressed(out_dir / f"{tag}__{slug}.npz", *[o.mask for o in objs])
        row = {"unix": round(time.time()), "image": str(image).replace("\\", "/"), "tag": tag, "prompt": prompt,
               "n_objects": len(objs),
               "objects": [{"id": o.object_id, "box_px": o.box_px, "px": int(o.mask.sum()),
                            "confidence": o.confidence} for o in objs]}
        with open(ROOT / "docs" / "smoke" / "chart_practice.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
        print(prompt, "->", len(objs), [(o.box_px, int(o.mask.sum())) for o in objs], flush=True)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3:])
