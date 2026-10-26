"""Orchestrator probe: one sam-3.1 call, dump the raw JSON response (masks truncated)."""
import base64
import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from autosolar.ledger import Ledger  # noqa: E402
from autosolar.meta_client import MetaClient  # noqa: E402

img, prompt, out = sys.argv[1], sys.argv[2], sys.argv[3]
stream = len(sys.argv) > 4 and sys.argv[4] == "conf"
for line in pathlib.Path(os.environ["AUTOSOLAR_ENV_FILE"]).read_text(encoding="utf-8").splitlines():
    if line.startswith("MODEL_API_KEY="):
        os.environ["MODEL_API_KEY"] = line.split("=", 1)[1].strip()
c = MetaClient(Ledger(ROOT / "ledger" / "api_usage.jsonl"), timeout_s=180)
url = "data:image/png;base64," + base64.b64encode(pathlib.Path(img).read_bytes()).decode()
msg = [{"type": "message", "role": "user", "content": [{"type": "input_text", "text": prompt},
                                                        {"type": "input_image", "image_url": url}]}]
r = c.respond("smoke-sam-day1", "S4-smoke-raw", msg, estimate_usd=0.0025, model="sam-3.1", images=1,
              metadata={"include_confidence": "true"} if stream else None)
s = json.dumps(r.raw)
pathlib.Path(out).write_text(s, encoding="utf-8")
print(len(s), "text chars", len(r.text))
print(s[:1800])
