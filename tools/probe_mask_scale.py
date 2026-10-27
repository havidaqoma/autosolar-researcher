"""Orchestrator probe: check how a SAM mask raster maps onto its box when the box is wider than the raster.

  uv run python tools/probe_mask_scale.py <raw_response.json> <image.png> <left> <top> <right> <bottom> [fixture_out.txt]

Compares the decoded mask with the drawn rectangle (truth, half-open) two ways: raster placed at native size at
the box corner, and raster stretched (nearest neighbour) to the box. Prints the intersection over union of each.
"""
import json
import pathlib
import sys

import meta_sam_parser as m
import numpy as np
from PIL import Image

raw, img = sys.argv[1], sys.argv[2]
tl, tt, tr, tb = (int(v) for v in sys.argv[3:7])
w, h = Image.open(img).size
text = json.loads(pathlib.Path(raw).read_text(encoding="utf-8"))["output"][0]["content"][0]["text"]
print("ascii", text.isascii(), "chars", len(text))
p = m.image_segmentation_format().create_parser()
p.push(text, emit=False)
res = p.finish(m.CompletedOutcome()).result
truth = np.zeros((h, w), bool)
truth[tt:tb, tl:tr] = True


def iou(a, b):
    return float(np.logical_and(a, b).sum() / np.logical_or(a, b).sum())


for rec in res.records:
    if not isinstance(rec, m.SegmentationMaskRecord):
        continue
    b = rec.bounds
    rw, rh = rec.mask.width, rec.mask.height
    ras = np.frombuffer(bytes(m.decode_mask_to_raster(rec.mask)), np.uint8).reshape(rh, rw) != 0
    bw, bh = int(b.right - b.left), int(b.bottom - b.top)
    ri = ((np.arange(bh) + 0.5) * rh / bh).astype(int)
    ci = ((np.arange(bw) + 0.5) * rw / bw).astype(int)
    full = np.zeros((h, w), bool)
    full[int(b.top):int(b.bottom), int(b.left):int(b.right)] = ras[np.ix_(ri, ci)]
    nat = np.zeros((h, w), bool)
    nat[int(b.top):int(b.top) + rh, int(b.left):int(b.left) + rw] = ras
    print("id", rec.object_id, "bounds", (b.left, b.top, b.right, b.bottom), "raster wh", (rw, rh),
          "conf", rec.confidence, "IoU native %.4f stretched %.4f" % (iou(nat, truth), iou(full, truth)))
if len(sys.argv) > 7:
    pathlib.Path(sys.argv[7]).write_text(text, encoding="ascii", newline="\n")
    print("fixture written")
