"""Pure-Python IoU overlap detection over a bounds list.

No browser, no Playwright — just axis-aligned rectangle geometry. The
render harness produces the bounds list via Playwright + Pixi.js getBounds();
this module decides which pairs overlap enough to be flagged.

Design notes:
- IoU uses min(area_a, area_b) as the denominator, not union. A small label
  fully inside a large box therefore reports IoU=1.0. That's the semantic we
  want for "is the text inside the graphics rect?" — union would dilute the
  signal for small labels.
- We only flag pairs where at least one side is Text. Graphics-on-Graphics
  overlap is typically intentional layering (e.g., stacked bars) and is not
  the defect class this feature targets.
- Text-on-dense-Graphics is flagged; Text-on-transparent-Graphics is not
  (transparent graphics don't visually occlude).
"""
from typing import Optional

from pydantic import BaseModel


DEFAULT_IOU_THRESHOLD = 0.05


class ObjectBounds(BaseModel):
    """One item from the Pixi display tree walk."""
    type: str
    text: Optional[str] = None
    bounds: dict
    alpha: float = 1.0
    dense: bool = False


class OverlapPair(BaseModel):
    a_index: int
    b_index: int
    a_label: str
    b_label: str
    iou: float
    a_bounds: dict
    b_bounds: dict


def detect_overlaps(
    bounds: list[ObjectBounds],
    *,
    iou_threshold: float = DEFAULT_IOU_THRESHOLD,
) -> list[OverlapPair]:
    """Return text-on-text and text-on-dense-graphics pairs above the IoU threshold."""
    candidate_indices: list[int] = []
    for i, obj in enumerate(bounds):
        if obj.type == "Text":
            candidate_indices.append(i)
        elif obj.type == "Graphics" and obj.dense:
            candidate_indices.append(i)

    overlaps: list[OverlapPair] = []
    for idx_a in range(len(candidate_indices)):
        for idx_b in range(idx_a + 1, len(candidate_indices)):
            i, j = candidate_indices[idx_a], candidate_indices[idx_b]
            a, b = bounds[i], bounds[j]
            # At least one side must be Text — don't flag Graphics-on-Graphics.
            if a.type != "Text" and b.type != "Text":
                continue
            iou = _iou(a.bounds, b.bounds)
            if iou > iou_threshold:
                overlaps.append(
                    OverlapPair(
                        a_index=i,
                        b_index=j,
                        a_label=a.text or a.type,
                        b_label=b.text or b.type,
                        iou=round(iou, 3),
                        a_bounds=a.bounds,
                        b_bounds=b.bounds,
                    )
                )
    return overlaps


def _iou(a: dict, b: dict) -> float:
    """Intersection / min(area_a, area_b). Zero if the boxes don't touch."""
    ax1, ay1 = a["x"], a["y"]
    bx1, by1 = b["x"], b["y"]
    aw, ah = a["width"], a["height"]
    bw, bh = b["width"], b["height"]
    ax2, ay2 = ax1 + aw, ay1 + ah
    bx2, by2 = bx1 + bw, by1 + bh

    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0

    intersection = (ix2 - ix1) * (iy2 - iy1)
    area_a = aw * ah
    area_b = bw * bh
    smaller = min(area_a, area_b)
    return intersection / smaller if smaller > 0 else 0.0


def format_collision_report(overlaps: list[OverlapPair]) -> str:
    """Format overlaps as a natural-language prompt fragment for the refine round."""
    if not overlaps:
        return "(no overlaps detected)"
    lines = []
    for o in overlaps:
        a_desc = f"Text '{o.a_label}'" if o.a_label else f"object[{o.a_index}]"
        b_desc = f"Text '{o.b_label}'" if o.b_label else f"object[{o.b_index}]"
        lines.append(
            f"- {a_desc} at "
            f"({o.a_bounds['x']:.0f},{o.a_bounds['y']:.0f},"
            f"{o.a_bounds['width']:.0f}w,{o.a_bounds['height']:.0f}h) "
            f"overlaps {b_desc} at "
            f"({o.b_bounds['x']:.0f},{o.b_bounds['y']:.0f},"
            f"{o.b_bounds['width']:.0f}w,{o.b_bounds['height']:.0f}h) "
            f"— IoU {o.iou}"
        )
    return "\n".join(lines)
