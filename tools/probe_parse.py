"""Probe for stage S0 (parse). Orchestrator tooling, not pipeline code.

  uv run python tools/probe_parse.py

Sends 5 fixed questions to the contributor model through MetaClient (ledger/api_usage.jsonl) and saves the raw
text and the usage to runs/parse_probe/probe.json, so the T09 spec can be written from measured behaviour.
"""
import json
import os
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from autosolar.ledger import Ledger  # noqa: E402
from autosolar.meta_client import MetaClient  # noqa: E402

QUESTIONS = [
    "Is solar plus battery worth it for Karimunjawa? The island runs on diesel.",
    "Berapa ukuran PLTS dan baterai yang paling murah untuk Pulau Karimunjawa yang sekarang pakai PLTD?",
    "How much solar and storage should Sumba add to cut diesel use?",
    "What is the best pizza in Jakarta?",
    "Size a PV and battery system for Lord Howe Island in Australia.",
]

INSTRUCTIONS = (
    "You turn a user question into a JSON object. Return only the JSON object, no prose, no code fence.\n"
    "Keys:\n"
    '  "site_name": the place the question is about, as written by the user (string, or null if none),\n'
    '  "country": the country of that place in English (string, or null if unknown),\n'
    '  "question_type": "pv_battery_for_diesel_grid" if the user asks whether or how much solar PV and/or '
    'battery storage to add to a power system, else "other",\n'
    '  "language": the ISO 639-1 code of the question.\n'
    "Do not guess coordinates. Do not add other keys."
)


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
    load_key()
    ledger = Ledger(ROOT / "ledger" / "api_usage.jsonl")
    client = MetaClient(ledger, timeout_s=120.0)
    out = []
    for i, q in enumerate(QUESTIONS):
        t = time.perf_counter()
        r = client.respond("probe_T09_parse", "S0_probe", [
            {"role": "system", "content": INSTRUCTIONS},
            {"role": "user", "content": q},
        ], estimate_usd=0.01)
        out.append({"question": q, "text": r.text, "usage": r.usage, "cost_usd": r.cost_usd,
                    "model": r.model, "seconds": round(time.perf_counter() - t, 2)})
        print(i, round(time.perf_counter() - t, 1), "s", r.cost_usd, repr(r.text[:200]))
    dest = ROOT / "runs" / "parse_probe"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "probe.json").write_text(json.dumps({"instructions": INSTRUCTIONS, "rows": out}, indent=1),
                                     encoding="utf-8")


if __name__ == "__main__":
    main()
