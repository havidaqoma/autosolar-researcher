"""SAM 3.1 test 2 (rules: docs/smoke/SAM_TEST2_RULES.md). Orchestrator tooling, not pipeline code.

  uv run --with rasterio --with pillow python tools/smoke_sam2.py prepare <osm_overpass.json>
  uv run python tools/smoke_sam2.py run

prepare: saves OSM building centroids, reads the two Sentinel-2 TCI COGs, picks the tile by code, writes tiles to
runs/sam_test2/ and their metadata to docs/smoke/sam_test2_tiles.json.
run: 12 SAM calls through MetaClient, measures, verdict, docs/smoke/sam_test2.json.
"""
import base64
import json
import os
import pathlib
import re
import sys
import time

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SMOKE = ROOT / "docs" / "smoke"
RUNS = ROOT / "runs" / "sam_test2"
SCENES = {"2026": "S2C_49MDP_20260909_0_L2A", "2025": "S2C_49MDP_20250709_0_L2A"}
COG = ("https://sentinel-cogs.s3.us-west-2.amazonaws.com/sentinel-s2-l2a-cogs/49/M/DP/{y}/{m}/{sid}/TCI.tif")
VILLAGE = (110.415, -5.89, 110.445, -5.86)
CALLS = [("A", "building"), ("A", "roof"), ("A", "house"), ("A", "village"),
         ("B", "building"), ("B", "roof"), ("B", "house"), ("B", "village"),
         ("C", "building"), ("C", "village"), ("C", "forest"), ("C", "beach")]
BOX = re.compile(r"<\|box;x1=(\d+);y1=(\d+);x2=(\d+);y2=(\d+);w=(\d+);h=(\d+)(?:;c=([0-9.]+))?\|>")


def cog_url(sid):
    y, m = sid[10:14], str(int(sid[14:16]))
    return COG.format(y=y, m=m, sid=sid)


def stretch(a):
    out = np.empty_like(a, dtype=np.uint8)
    for b in range(3):
        lo, hi = np.percentile(a[..., b], [2, 98])
        out[..., b] = np.clip((a[..., b].astype(float) - lo) / max(hi - lo, 1) * 255, 0, 255).astype(np.uint8)
    return out


def prepare(osm_path):
    import rasterio
    from PIL import Image
    from rasterio.warp import transform, transform_bounds
    from rasterio.windows import Window, from_bounds

    osm = json.loads(pathlib.Path(osm_path).read_text(encoding="utf-8"))
    cents = [{"id": e["id"], "lat": e["center"]["lat"], "lon": e["center"]["lon"]} for e in osm["elements"]]
    (SMOKE / "osm_buildings_karimunjawa.json").write_text(json.dumps({
        "attribution": "OpenStreetMap contributors, ODbL 1.0", "source": "Overpass API, way[building], bbox "
        "-5.91,110.38,-5.77,110.48", "osm_base": osm.get("osm3s", {}).get("timestamp_osm_base"),
        "n": len(cents), "centroids": cents}, indent=0), encoding="utf-8")
    RUNS.mkdir(parents=True, exist_ok=True)
    arrs, meta = {}, {}
    for key, sid in SCENES.items():
        with rasterio.open(cog_url(sid)) as src:
            b = transform_bounds("EPSG:4326", src.crs, *VILLAGE)
            w = from_bounds(*b, transform=src.transform).round_offsets().round_lengths()
            big = Window(w.col_off - 64, w.row_off - 64, w.width + 128, w.height + 128)
            arrs[key] = np.transpose(src.read([1, 2, 3], window=big), (1, 2, 0))
            meta[key] = {"crs": str(src.crs), "transform": list(src.window_transform(big))[:6],
                         "inner": [64, 64, int(w.width), int(w.height)]}
    crs, tr = meta["2026"]["crs"], meta["2026"]["transform"]
    assert meta["2025"]["transform"] == tr, "the two scenes must share one pixel grid"
    xs, ys = transform("EPSG:4326", crs, [c["lon"] for c in cents], [c["lat"] for c in cents])
    cols = (np.array(xs) - tr[2]) / tr[0]
    rows = (np.array(ys) - tr[5]) / tr[4]
    c0, r0, iw, ih = meta["2026"]["inner"]
    best = None
    for r in range(r0, r0 + ih - 128 + 1, 8):
        for c in range(c0, c0 + iw - 128 + 1, 8):
            ok = True
            for key in SCENES:
                t = arrs[key][r:r + 128, c:c + 128]
                if (t.sum(axis=2) == 0).any() or (t.min(axis=2) > 200).mean() >= 0.02:
                    ok = False
            if not ok:
                continue
            n = int(((cols >= c) & (cols < c + 128) & (rows >= r) & (rows < r + 128)).sum())
            if best is None or n > best[0]:
                best = (n, r, c)
    assert best, "no clean window"
    n, r, c = best
    tiles = {"A": ("2026", r, c, 128, 8), "B": ("2025", r, c, 128, 8), "C": ("2025", r - 64, c - 64, 256, 4)}
    out = {"rules": "docs/smoke/SAM_TEST2_RULES.md", "crs": crs, "grid_transform": tr, "tiles": {}}
    for name, (key, rr, cc, size, f) in tiles.items():
        a = arrs[key][rr:rr + size, cc:cc + size]
        assert a.shape[:2] == (size, size) and not (a.sum(axis=2) == 0).any(), f"tile {name} incomplete"
        im = Image.fromarray(stretch(a)).resize((size * f, size * f), Image.LANCZOS)
        p = RUNS / f"tile_{name}.png"
        im.save(p)
        inside = (cols >= cc) & (cols < cc + size) & (rows >= rr) & (rows < rr + size)
        px = [[round((cols[i] - cc) * f, 1), round((rows[i] - rr) * f, 1)] for i in np.flatnonzero(inside)]
        out["tiles"][name] = {"scene": SCENES[key], "native_px": size, "upscale": f, "row_col": [int(rr), int(cc)],
                              "very_bright_share": round(float((a.min(axis=2) > 200).mean()), 4),
                              "osm_buildings": len(px), "osm_px": px, "png": p.name}
    (SMOKE / "sam_test2_tiles.json").write_text(json.dumps(out, indent=0), encoding="utf-8")
    print({k: (v["scene"][4:18], v["osm_buildings"], v["very_bright_share"]) for k, v in out["tiles"].items()})


def measure(text, osm_px, size_px):
    boxes = [tuple(int(v) for v in b[:4]) for b in BOX.findall(text)]
    conf = [float(b[6]) for b in BOX.findall(text) if b[6]]
    area = size_px * size_px
    shares = [(x2 - x1 + 1) * (y2 - y1 + 1) / area for x1, y1, x2, y2 in boxes]

    def inside(p, b):
        return b[0] <= p[0] <= b[2] and b[1] <= p[1] <= b[3]

    prec = (sum(any(inside(p, b) for p in osm_px) for b in boxes) / len(boxes)) if boxes else 0.0
    rec = (sum(any(inside(p, b) for b in boxes) for p in osm_px) / len(osm_px)) if osm_px else 0.0
    best_box_hold = max((sum(inside(p, b) for p in osm_px) / max(len(osm_px), 1)
                         for b, s in zip(boxes, shares) if s <= 0.5), default=0.0)
    return {"n_objects": len(boxes), "max_box_share": round(max(shares), 4) if shares else 0.0,
            "precision": round(prec, 4), "recall": round(rec, 4),
            "best_box_le50_osm_share": round(best_box_hold, 4),
            "conf_median": round(float(np.median(conf)), 4) if conf else None, "boxes": boxes[:200]}


def run():
    from autosolar.ledger import Ledger
    from autosolar.meta_client import MetaClient

    if not os.environ.get("MODEL_API_KEY"):
        env_file = pathlib.Path(os.environ.get("AUTOSOLAR_ENV_FILE", ROOT / ".env"))
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("MODEL_API_KEY="):
                os.environ["MODEL_API_KEY"] = line.split("=", 1)[1].strip()
    tiles = json.loads((SMOKE / "sam_test2_tiles.json").read_text(encoding="utf-8"))["tiles"]
    client = MetaClient(Ledger(ROOT / "ledger" / "api_usage.jsonl"), timeout_s=180.0)
    urls = {k: "data:image/png;base64," + base64.b64encode((RUNS / v["png"]).read_bytes()).decode("ascii")
            for k, v in tiles.items()}
    res = {"rules": "docs/smoke/SAM_TEST2_RULES.md", "started_unix": round(time.time()), "calls": []}
    for tile, prompt in CALLS:
        t = tiles[tile]
        size_px = t["native_px"] * t["upscale"]
        msg = [{"type": "message", "role": "user", "content": [
            {"type": "input_text", "text": prompt}, {"type": "input_image", "image_url": urls[tile]}]}]
        t0 = time.time()
        row = {"tile": tile, "prompt": prompt}
        try:
            r = client.respond("sam-test2", "S4-test2", msg, estimate_usd=0.0025, model="sam-3.1", images=1,
                               metadata={"include_confidence": "true"})
            (RUNS / f"raw_{tile}_{prompt}.txt").write_text(r.text, encoding="utf-8")
            row.update({"ok": True, "cost_usd": r.cost_usd, "response_id": r.response_id,
                        **measure(r.text, t["osm_px"], size_px)})
        except Exception as e:  # counted as a fail by the rules, never retried
            row.update({"ok": False, "error": str(e)[:400]})
        row["wall_s"] = round(time.time() - t0, 2)
        res["calls"].append(row)
        print(tile, prompt, {k: row.get(k) for k in ("ok", "n_objects", "max_box_share", "precision", "recall",
                                                       "best_box_le50_osm_share")}, flush=True)

    def get(tile, prompt):
        return next(c for c in res["calls"] if c["tile"] == tile and c["prompt"] == prompt)

    def roof_ok(c):
        return (c["ok"] and c["n_objects"] >= 3 and c["max_box_share"] <= 0.25 and c["precision"] >= 0.5
                and c["recall"] >= 0.2)

    roof = {w: roof_ok(get("A", w)) and roof_ok(get("B", w)) for w in ("building", "roof", "house")}
    settle_tiles = [t for t in "ABC" if any(c["ok"] and c["best_box_le50_osm_share"] >= 0.5 for c in
                                            (get(t, "village"), get(t, "building")))]
    res["roof_role_by_wording"] = roof
    res["roof_role_pass"] = any(roof.values())
    res["settlement_role_tiles"] = settle_tiles
    res["settlement_role_pass"] = len(settle_tiles) >= 2
    res["verdict"] = ("keep card B" if res["roof_role_pass"] else
                      "coarse settlement role" if res["settlement_role_pass"] else "SAM leaves the satellite role")
    res["total_cost_usd_computed"] = round(sum(c.get("cost_usd", 0) for c in res["calls"]), 6)
    (SMOKE / "sam_test2.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    print("VERDICT:", res["verdict"], "| roof", roof, "| settlement tiles", settle_tiles, "| USD",
          res["total_cost_usd_computed"])


if __name__ == "__main__":
    if sys.argv[1] == "prepare":
        prepare(sys.argv[2])
    else:
        run()
