"""Orchestrator probe: can Muse Spark (contributor) read SAM tick-label crops? One call, all crops as images."""
import base64
import io
import json
import os
import pathlib
import re
import sys

from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from autosolar.ledger import Ledger  # noqa: E402
from autosolar.meta_client import MetaClient  # noqa: E402

for line in pathlib.Path(os.environ["AUTOSOLAR_ENV_FILE"]).read_text(encoding="utf-8").splitlines():
    if line.startswith("MODEL_API_KEY="):
        os.environ["MODEL_API_KEY"] = line.split("=", 1)[1].strip()
fig = Image.open(ROOT / "runs/sam_fig/hiron_fig7.png").convert("RGB")
t = json.load(open(ROOT / "runs/sam_fig/raw_fig7_number.json", encoding="utf-8"))["output"][0]["content"][0]["text"]
boxes = [tuple(int(v) for v in b) for b in re.findall(r"box;x1=(\d+);y1=(\d+);x2=(\d+);y2=(\d+);", t)]
content = [{"type": "input_text", "text": (
    f"Here are {len(boxes)} small crops from a chart, numbered 1 to {len(boxes)} in order. Each crop should hold one "
    "axis tick label. Read the text in each crop exactly as printed. Reply with JSON only: a list of objects "
    "{\"crop\": n, \"text\": \"...\"}; use null for text when a crop holds no single readable label.")}]
for i, (x1, y1, x2, y2) in enumerate(boxes, 1):
    buf = io.BytesIO()
    fig.crop((x1 - 3, y1 - 3, x2 + 4, y2 + 4)).save(buf, format="PNG")
    content.append({"type": "input_text", "text": f"Crop {i}:"})
    content.append({"type": "input_image", "image_url": "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()})
c = MetaClient(Ledger(ROOT / "ledger" / "api_usage.jsonl"), timeout_s=180)
r = c.respond("chart-probe", "S4-tick-read", [{"type": "message", "role": "user", "content": content}],
              estimate_usd=0.01, reasoning_effort="low")
out = {"boxes": boxes, "answer": r.text, "usage": r.raw.get("usage"), "cost_usd": r.cost_usd, "model": r.raw.get("model")}
(ROOT / "runs/sam_fig/tick_read_probe.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
print(r.text[:1500]); print("cost", r.cost_usd, "usage", r.raw.get("usage"))
