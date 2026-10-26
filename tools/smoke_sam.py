"""Day 1 smoke test of SAM 3.1 through autosolar.meta_client (orchestrator tooling, not pipeline code).

Usage: python tools/smoke_sam.py <village.png> <island.png> [--out docs/smoke/sam_smoke.json]

Sends 12 concept prompts (6 per image) to sam-3.1, non streaming, with confidence on. Logs every call in
ledger/api_usage.jsonl through the Ledger (USD 0.0025 per image). Saves counts, boxes and confidences, not masks.
Raw response text goes to runs/smoke_sam/ (not committed).
"""
import argparse
import base64
import hashlib
import json
import os
import pathlib
import re
import statistics
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from autosolar.ledger import Ledger  # noqa: E402
from autosolar.meta_client import MetaClient  # noqa: E402

PROMPTS = {
    "village": ["building", "roof", "house", "open field", "water", "solar panel"],
    "island": ["building", "open field", "water", "forest", "beach", "road"],
}
BOX = re.compile(r"<\|box;x1=(\d+);y1=(\d+);x2=(\d+);y2=(\d+);w=(\d+);h=(\d+)(?:;c=([0-9.]+))?\|>")
MASK = re.compile(r"<\|mask;[^|]*\|>")


def load_key():
    if os.environ.get("MODEL_API_KEY"):
        return
    env_file = pathlib.Path(os.environ.get("AUTOSOLAR_ENV_FILE", ROOT / ".env"))
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if line.startswith("MODEL_API_KEY="):
            os.environ["MODEL_API_KEY"] = line.split("=", 1)[1].strip()
            return
    sys.exit("MODEL_API_KEY not found")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("village")
    ap.add_argument("island")
    ap.add_argument("--out", default=str(ROOT / "docs" / "smoke" / "sam_smoke.json"))
    a = ap.parse_args()
    load_key()
    ledger = Ledger(ROOT / "ledger" / "api_usage.jsonl")
    client = MetaClient(ledger, timeout_s=180.0)
    raw_dir = ROOT / "runs" / "smoke_sam"
    raw_dir.mkdir(parents=True, exist_ok=True)
    out = {"model": "sam-3.1", "started_unix": round(time.time()), "images": {}, "calls": []}
    for name, path in (("village", a.village), ("island", a.island)):
        data = pathlib.Path(path).read_bytes()
        out["images"][name] = {"file": pathlib.Path(path).name, "sha256": hashlib.sha256(data).hexdigest(),
                               "bytes": len(data)}
        url = "data:image/png;base64," + base64.b64encode(data).decode("ascii")
        for prompt in PROMPTS[name]:
            msg = [{"type": "message", "role": "user", "content": [
                {"type": "input_text", "text": prompt}, {"type": "input_image", "image_url": url}]}]
            t0 = time.time()
            row = {"image": name, "prompt": prompt}
            try:
                r = client.respond("smoke-sam-day1", "S4-smoke", msg, estimate_usd=0.0025, model="sam-3.1",
                                   images=1, metadata={"include_confidence": "true"})
            except Exception as e:  # record and continue: the smoke test reports every failure
                row.update({"ok": False, "error": str(e)[:400], "wall_s": round(time.time() - t0, 2)})
                out["calls"].append(row)
                print(name, prompt, "ERROR", str(e)[:200], flush=True)
                continue
            boxes = BOX.findall(r.text)
            (raw_dir / f"{name}_{prompt.replace(' ', '_')}.txt").write_text(r.text, encoding="utf-8")
            conf = [float(b[6]) for b in boxes if b[6]]
            areas = [(int(b[2]) - int(b[0]) + 1) * (int(b[3]) - int(b[1]) + 1) for b in boxes]
            row.update({
                "ok": True, "wall_s": round(time.time() - t0, 2), "cost_usd": r.cost_usd,
                "n_objects": len(boxes), "n_masks": len(MASK.findall(r.text)),
                "image_wh": [int(boxes[0][4]), int(boxes[0][5])] if boxes else None,
                "conf_min": min(conf) if conf else None, "conf_median": statistics.median(conf) if conf else None,
                "box_area_px_sum": sum(areas), "box_area_px_max": max(areas) if areas else 0,
                "mask_markers": sorted(set(re.findall(r"data=\d+,\d+,(.)", r.text))),
                "response_chars": len(r.text), "response_id": r.response_id,
            })
            out["calls"].append(row)
            print(name, prompt, row["n_objects"], "objects", row["wall_s"], "s", flush=True)
    out["total_cost_usd_computed"] = round(sum(c.get("cost_usd", 0) for c in out["calls"]), 6)
    out["ok_calls"] = sum(c["ok"] for c in out["calls"])
    p = pathlib.Path(a.out)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print("saved", p, "ok", out["ok_calls"], "of", len(out["calls"]), "USD", out["total_cost_usd_computed"])


if __name__ == "__main__":
    main()
