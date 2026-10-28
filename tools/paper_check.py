"""Stage S7 paper check: Muse Spark reads a PDF study, scripts check its numbers (P1 to P15).

  AUTOSOLAR_ENV_FILE=path/to/.env uv run python tools/paper_check.py <paper.pdf> --study runs/studies/<hash> \
      [--label hiron2021] [--repeat 1]

Orchestrator glue around autosolar.paper_check (T12a). One paid call per repeat: Muse Spark (contributor) gets the
whole PDF as an input_file and returns the numbers as JSON (prompt below). The scripts then keep only numbers whose
quote is found in the PDF text layer, and run the frozen checks. The site irradiation range for P3 and P8 comes from
the study run's weather table: the minimum and maximum of NASA POWER, PVGIS-ERA5 and GSA (as the frozen check says).
Output: runs/paper_checks/<run_id>/paper_check.json and paper_check.md. The PDF itself is never copied.
The model key is read from the environment or the env file and never printed.
"""
import argparse
import base64
import dataclasses
import hashlib
import json
import pathlib
import sys
import time
import uuid

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from ask import env_value  # noqa: E402
from autosolar.cite_check import pdf_pages  # noqa: E402
from autosolar.ledger import Ledger  # noqa: E402
from autosolar.meta_client import MetaClient  # noqa: E402
from autosolar.paper_check import (CHECK_IDS, QUANTITIES, parse_extraction, run_checks, summary,  # noqa: E402
                                   verify_extraction)

INDEPENDENT_CASES = ("NASA POWER", "PVGIS-ERA5 TMY", "GSA scaled")
CHECK_TITLES = {
    "P1": "One quantity, one value", "P2": "Hourly energy balance", "P3": "PV yield is physically possible",
    "P4": "Battery gives out no more than it took in", "P5": "Power within rating", "P6": "Sizes stated consistently",
    "P7": "PV area fits the module count", "P8": "Stated sunshine matches independent sources",
    "P9": "Cost items add up", "P10": "Cost of energy recomputes", "P11": "Economics can be reproduced",
    "P12": "Fuel per kWh is plausible", "P13": "Renewable share recomputes", "P14": "CO2 per litre is plausible",
    "P15": "Daily and annual totals agree",
}
QUANTITY_HELP = {
    "pv_ac_kw": "PV plant AC rating (inverter side), any power unit",
    "pv_dc_kwp": "PV array DC size (kWp, MWp)",
    "diesel_kw": "rated power of the diesel plant or of each diesel unit (use count for 'N x size')",
    "converter_kw": "converter or inverter rating of the battery system",
    "battery_kw": "battery power rating",
    "peak_load_kw": "peak electricity demand",
    "battery_size": "battery capacity in any unit as printed (kWh, MWh, Ah, MAh)",
    "pv_module_wp": "rated power of one PV module (Wp)",
    "pv_module_count": "number of PV modules",
    "pv_module_area_m2": "area of one PV module",
    "pv_area_m2": "total land or roof area used by the whole PV plant (never a per-module or spacing figure)",
    "load_kwh_day": "electricity demand per day",
    "pv_kwh_day": "PV energy per day",
    "diesel_kwh_day": "diesel energy per day",
    "load_kwh_yr": "electricity demand per year",
    "pv_kwh_yr": "PV energy per year",
    "diesel_kwh_yr": "diesel energy per year",
    "energy_served_kwh_yr": "total electricity served per year",
    "ghi_kwh_m2_yr": "solar irradiation at the site (per day or per year, unit as printed)",
    "wind_m_s": "wind speed (put the height in condition)",
    "lcoe_usd_per_kwh": "levelised cost of energy or cost of energy of the proposed system (put the scenario in condition)",
    "base_coe_usd_per_kwh": "cost of energy of the system before the project",
    "npc_usd": "net present cost",
    "capex_usd": "total initial capital cost",
    "annual_cost_usd": "total annual cost",
    "cost_item_usd": "one line of a cost breakdown; condition = npc_usd, capex_usd or annual_cost_usd (the total it belongs to)",
    "om_cost_usd": "operation and maintenance cost, any form",
    "pv_capex_usd_per_kw": "PV capital cost per kW or kWp",
    "diesel_capex_usd_per_kw": "diesel generator capital cost per kW",
    "battery_capex_usd_per_kwh": "battery capital cost per kWh",
    "fuel_price_usd_per_l": "diesel fuel price per litre",
    "discount_rate_frac": "discount or interest rate used in the economics",
    "renewable_fraction_frac": "renewable share of the energy served",
    "battery_rte_frac": "battery round trip efficiency",
    "project_life_yr": "project lifetime",
    "fuel_l_yr": "diesel fuel used per year",
    "co2_kg_yr": "CO2 emitted per year",
}
PROMPT = (
    "You read a PDF of a design or feasibility study of a power system with PV, batteries or diesel generators. "
    "Copy out the numbers listed below exactly as the PDF prints them. Return only JSON, no prose, with exactly two "
    "keys: \"statements\" and \"schedule\".\n\n"
    "statements: one entry for EVERY place where a listed quantity is stated: abstract, text, tables, figure "
    "captions and conclusion. If the paper states the same quantity in four places, give four entries, also when the "
    "values differ. Never fix, convert, add up, multiply or round a number. Each entry is "
    "{\"quantity\": a name from the list, \"value\": the number as printed, written as a JSON number and never as a "
    "string (dot for decimals, no thousands separators), \"count\": a JSON integer, the number of identical units "
    "when the paper writes for example 2 x 2.7 MW (then value 2.7 and count 2), else null, \"unit\": only the unit "
    "of that number as printed (for example MW), without any other text, \"condition\": \"\" or a few words when the "
    "value belongs to a scenario, height, year or case that makes it a different value, \"page\": the page in the PDF "
    "file counted from 1, \"place\": one of abstract, text, table, caption, conclusion, \"quote\": the words around "
    "the number copied character for character from the PDF, at least 8 words where the text allows, and it must "
    "contain the number; for a number in a table, the row or column label and the number}.\n\n"
    "Quantity names:\n" + "\n".join("- " + k + ": " + v for k, v in QUANTITY_HELP.items()) + "\n\n"
    "schedule: if the paper prints a table of power flows for one day at a fixed time step (for example hourly), "
    "give {\"page\": page in the PDF file, \"label\": the table name, \"period_h\": hours per row, \"rows\": [one "
    "object per printed row: {\"time\", \"load_kw\", \"pv_to_load_kw\", \"pv_total_kw\", \"pv_to_battery_kw\", "
    "\"battery_discharge_kw\", \"diesel_kw\", \"curtailed_kw\"}]}. All numbers in rows are JSON numbers, never "
    "strings. Map each printed column to the field it means: pv_to_load_kw is PV power that goes straight to the "
    "load, pv_total_kw is all PV output, pv_to_battery_kw is power that charges the battery. A PV column that equals "
    "the load in the hours when the battery charges is pv_to_load_kw, not pv_total_kw. Use null for a field the "
    "table does not have. Copy every row. If the paper has no such table, schedule is null."
)


def site_range(study_dir):
    rep = json.loads((pathlib.Path(study_dir) / "report.json").read_text(encoding="ascii"))
    vals = {w["case"]: float(w["ghi_kwh_m2_yr"]) for w in rep["weather_table"] if w["case"] in INDEPENDENT_CASES}
    if len(vals) < 2:
        sys.exit("study weather table lacks the independent sources")
    return (min(vals.values()), max(vals.values())), vals, rep["run_hash"]


def site_range_at(lat_deg, lon_deg):
    """Same three sources fetched for any point (measured, cached under runs/weather_cache)."""
    from autosolar.weather import (YEAR_FROM, YEAR_TO, annual_totals_nasa_monthly, cached_fetchers,
                                   default_fetchers, ghi_from_pvlib, gsa_annual_ghi_kwh_m2)
    f = cached_fetchers(default_fetchers(), ROOT / "runs" / "weather_cache")
    nasa = annual_totals_nasa_monthly(f.nasa_monthly(lat_deg, lon_deg, YEAR_FROM, YEAR_TO))
    vals = {"NASA POWER": sum(nasa.values()) / len(nasa),
            "PVGIS-ERA5 TMY": float(ghi_from_pvlib(f.pvgis_tmy(lat_deg, lon_deg)).sum() / 1000.0),
            "GSA scaled": float(gsa_annual_ghi_kwh_m2(f.gsa(lat_deg, lon_deg)))}
    return (min(vals.values()), max(vals.values())), vals, "site %.4f,%.4f" % (lat_deg, lon_deg)


def render(out):
    lines = ["# Paper check: " + out["label"], "",
             "PDF sha256 " + out["pdf_sha256"][:16] + ", " + str(out["pages"]) + " pages. Run " + out["run_id"] + ".",
             "Numbers were read by " + out["model"] + " and kept only when their quote is in the PDF text layer.",
             "",
             "Kept " + str(len(out["verified"]["statements"])) + " statements, dropped "
             + str(len(out["verified"]["dropped"])) + ", rejected " + str(len(out["verified"]["rejected"]))
             + "; schedule " + ("kept" if out["verified"]["schedule"] is not None else "not kept") + ".", "",
             "| Check | Result | Pages | Evidence |", "|---|---|---|---|"]
    for r in out["results"]:
        lines.append("| " + r["check_id"] + " " + CHECK_TITLES[r["check_id"]] + " | " + r["status"] + " | "
                     + ", ".join(str(p) for p in r["pages"]) + " | " + r["detail"].replace("|", "/") + " |")
    s = out["summary"]
    lines += ["", "Flags " + str(s["flags"]) + ", passes " + str(s["passes"]) + ", not checkable "
              + str(s["not_checkable"]) + ". A flag means our checks could not reconcile the numbers as printed; "
              "it is not a finding about the authors."]
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--study", default=None, help="study run folder; its weather table gives the site range")
    ap.add_argument("--site", default=None, help="LAT,LON of the paper site when no study run exists there")
    ap.add_argument("--label", default=None)
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--effort", default=None, help="reasoning effort passed to the model (default: none sent)")
    args = ap.parse_args()
    import os
    os.environ["MODEL_API_KEY"] = env_value("MODEL_API_KEY")
    pdf = pathlib.Path(args.pdf)
    data = pdf.read_bytes()
    pages = pdf_pages(data)
    if args.study is not None:
        rng, sources, study_hash = site_range(args.study)
    elif args.site is not None:
        lat, lon = (float(x) for x in args.site.split(","))
        rng, sources, study_hash = site_range_at(lat, lon)
    else:
        sys.exit("give --study or --site")
    client = MetaClient(Ledger(ROOT / "ledger" / "api_usage.jsonl"), timeout_s=600.0)
    inp = [{"role": "user", "content": [
        {"type": "input_file", "filename": pdf.name,
         "file_data": "data:application/pdf;base64," + base64.b64encode(data).decode("ascii")},
        {"type": "input_text", "text": PROMPT}]}]
    for _ in range(args.repeat):
        run_id = "paper-" + time.strftime("%Y%m%dT%H%M%S", time.gmtime()) + "-" + uuid.uuid4().hex[:6]
        t0 = time.time()
        res = client.respond(run_id, "S7_paper_extract", inp, estimate_usd=0.30, reasoning_effort=args.effort)
        wall = round(time.time() - t0, 1)
        try:
            parsed = parse_extraction(res.text)
        except ValueError as exc:
            parsed = {"statements": [], "schedule": None, "rejected": [{"index": "all", "reason": str(exc)}]}
        verified = verify_extraction(parsed, pages)
        results = run_checks(verified, site_ghi_kwh_m2_yr=rng)
        out = {"schema": "autosolar.paper_check/1", "run_id": run_id, "label": args.label or pdf.stem,
               "pdf_name": pdf.name, "pdf_sha256": hashlib.sha256(data).hexdigest(), "pages": len(pages),
               "model": res.model, "usage": res.usage, "cost_usd": res.cost_usd, "wall_s": wall,
               "study": study_hash, "site_ghi_kwh_m2_yr": list(rng), "site_sources": sources,
               "prompt_sha256": hashlib.sha256(PROMPT.encode("utf-8")).hexdigest(), "raw_text": res.text,
               "verified": verified, "results": [dataclasses.asdict(r) for r in results],
               "summary": summary(results)}
        run_dir = ROOT / "runs" / "paper_checks" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "paper_check.json").write_text(json.dumps(out, indent=2, ensure_ascii=True), encoding="ascii")
        (run_dir / "paper_check.md").write_text(render(out), encoding="ascii")
        print(run_id, "wall", wall, "s USD", res.cost_usd, "kept", len(verified["statements"]), "dropped",
              len(verified["dropped"]), "schedule", verified["schedule"] is not None, "flags",
              out["summary"]["flagged_ids"])
    assert set(CHECK_TITLES) == set(CHECK_IDS) and set(QUANTITY_HELP) == set(QUANTITIES)


if __name__ == "__main__":
    main()
