"""Score paper check runs on the Hiron 2021 paper against the hand audit (in-sample; rule fixed before the v2 runs).

  uv run python tools/score_paper_hiron.py runs/paper_checks/<run_id>/paper_check.json [...]

The hand audit in the private prep repo found 14 of 15 checks it could not reconcile. 13 of them fall under the
frozen checks P1 to P15 (C13, fuel share of cost, has no frozen check). A hand audit item counts as found when its
frozen check is flagged AND the flag's evidence names the quantity the item is about (rules below). Every other
flag is an extra flag that a person must confirm by hand from the paper's own numbers before it counts as true.
This is in-sample: the checks and the prompt were written after reading this paper.
"""
import json
import sys

ITEMS = (
    ("C1", "energy figures agree in value and unit", (("P15", "load"), ("P1", "load_kwh"))),
    ("C3", "hourly balance closes", (("P2", ""),)),
    ("C4", "PV energy is physically possible", (("P3", ""),)),
    ("C5", "battery gives out no more than it took in", (("P4", ""),)),
    ("C6", "PV output within its AC rating", (("P5", "pv"),)),
    ("C7", "diesel plant size stated consistently", (("P6", "diesel_kw"),)),
    ("C8", "battery size stated consistently", (("P6", "battery_size"),)),
    ("C9", "PV land area consistent", (("P1", "pv_area_m2"),)),
    ("C10", "wind speed stated consistently", (("P1", "wind_m_s"),)),
    ("C11", "pre-PV generation cost stated consistently", (("P1", "base_coe"),)),
    ("C12", "LCOE stated consistently with units", (("P1", "lcoe_usd_per_kwh"),)),
    ("C15", "cost items add up and recompute the LCOE", (("P9", ""), ("P10", ""))),
    ("C16", "inputs to reproduce the LCOE are stated", (("P11", ""),)),
)


def score(path):
    d = json.loads(open(path, encoding="ascii").read())
    res = {r["check_id"]: r for r in d["results"]}
    found, used = [], set()
    for cid, _what, rules in ITEMS:
        hit = False
        for pid, key in rules:
            r = res[pid]
            if r["status"] == "flag" and key in r["detail"]:
                hit = True
                used.add(pid)
        if hit:
            found.append(cid)
    extra = [pid for pid, r in res.items() if r["status"] == "flag" and pid not in used]
    return {"run_id": d["run_id"], "found": found, "found_n": len(found), "covered_n": len(ITEMS),
            "extra_flags": extra, "flags": d["summary"]["flagged_ids"], "kept": len(d["verified"]["statements"]),
            "dropped": len(d["verified"]["dropped"]), "rejected": len(d["verified"]["rejected"]),
            "schedule": d["verified"]["schedule"] is not None, "cost_usd": d["cost_usd"], "wall_s": d["wall_s"]}


if __name__ == "__main__":
    for p in sys.argv[1:]:
        print(json.dumps(score(p)))
