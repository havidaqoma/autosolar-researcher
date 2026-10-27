"""Judge probe for S3: the real T10a support prompt on the 4 saved probe sources, judged by local Muse Glimmer.

Orchestrator tooling. Free (local model). Starts the server like tools/source.py and saves
runs/search_probe/judge_probe_t10e.json (T10e prompt). The discount rate row is a planted trap: the source states a nominal WACC,
the target is a real discount rate, so a careful judge says no.
"""
import json
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from autosolar.cite_check import Claim, fetch_source, find_quote, support_verdict, title_in_source  # noqa: E402
from autosolar.sourcing import glimmer_judge  # noqa: E402  (falls back below while T10b is not built)
from source import server_up, start_server  # noqa: E402

P = ROOT / "runs" / "search_probe"
TARGETS = json.loads((ROOT / "config" / "sourcing_targets.json").read_text(encoding="utf-8"))["targets"]
DESC = {t["input"]: t["description"] for t in TARGETS}


class Saved:
    def __init__(self, body, url):
        self.status_code, self.content, self.url, self.headers = 200, body, url, {}


def main():
    probe = json.loads((P / "probe.json").read_text(encoding="utf-8"))
    proc = None if server_up() else start_server(P / "judge_server.log")
    rows = []
    try:
        for n, row in enumerate(probe["rows"]):
            a = row["answer"]
            body = next(P.glob("src_%d.*" % n)).read_bytes()
            claim = Claim(row["input"], DESC[row["input"]], a["value"], a["unit"], a["url"], a.get("doi"),
                          a["quote"], a.get("title") or "", a.get("currency_year"))
            src = fetch_source(claim.url, lambda url, **kw: Saved(body, url))
            m = find_quote(claim.quote, src.pages)
            prompts = []

            def judge(prompt):
                prompts.append(prompt)
                return glimmer_judge(prompt)

            t = time.perf_counter()
            shown = title_in_source(claim.title, src.pages)
            v = support_verdict(judge, claim, m.context, source_title=claim.title if shown else None,
                                source_url=src.final_url)
            sec = round(time.perf_counter() - t, 1)
            rows.append({"input": row["input"], "description": claim.description, "quote_kind": m.kind,
                         "context_chars": len(m.context), "title_shown": shown, "prompt_chars": len(prompts[0]) if prompts else 0,
                         "supports": v.supports, "reason": v.reason, "seconds": sec})
            print(row["input"], v.supports, sec, "s |", v.reason[:200], flush=True)
    finally:
        if proc is not None:
            proc.terminate()
            proc.wait(timeout=60)
    out = {"what": "local Muse Glimmer support verdicts on the 4 S3 probe claims (T10e prompt: title when the source text contains it, plus URL)", "label": "measured",
           "rows": rows}
    (P / "judge_probe_t10e.json").write_text(json.dumps(out, indent=1, ensure_ascii=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
