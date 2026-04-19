"""Unit tests for visual_overlap_detector — pure geometry, no browser."""
import pytest

from book_ingestion_v2.services.visual_overlap_detector import (
    DEFAULT_IOU_THRESHOLD,
    ObjectBounds,
    detect_overlaps,
    format_collision_report,
    _iou,
)


# ─── Helpers ──────────────────────────────────────────────────────────────


def _rect(x: float, y: float, w: float, h: float) -> dict:
    return {"x": x, "y": y, "width": w, "height": h}


def _text(x: float, y: float, w: float, h: float, text: str = "label") -> ObjectBounds:
    return ObjectBounds(type="Text", text=text, bounds=_rect(x, y, w, h))


def _graphics(x: float, y: float, w: float, h: float, dense: bool = True) -> ObjectBounds:
    return ObjectBounds(type="Graphics", bounds=_rect(x, y, w, h), dense=dense)


# ─── IoU math ─────────────────────────────────────────────────────────────


class TestIoUMath:
    def test_disjoint_returns_zero(self):
        assert _iou(_rect(0, 0, 10, 10), _rect(100, 100, 10, 10)) == 0.0

    def test_identical_returns_one(self):
        assert _iou(_rect(0, 0, 10, 10), _rect(0, 0, 10, 10)) == 1.0

    def test_small_inside_large_returns_one(self):
        # 10x10 label fully inside a 100x100 rect — min-area denominator => 1.0
        assert _iou(_rect(20, 20, 10, 10), _rect(0, 0, 100, 100)) == 1.0

    def test_half_overlap(self):
        # Two 10x10 boxes overlapping by 5x10 area — intersection 50, min area 100 => 0.5
        assert _iou(_rect(0, 0, 10, 10), _rect(5, 0, 10, 10)) == pytest.approx(0.5)

    def test_touching_but_not_overlapping(self):
        # Right edge of A aligns with left edge of B — no intersection
        assert _iou(_rect(0, 0, 10, 10), _rect(10, 0, 10, 10)) == 0.0


# ─── detect_overlaps ─────────────────────────────────────────────────────


class TestDetectOverlaps:
    def test_no_overlap_when_bounds_disjoint(self):
        bounds = [_text(0, 0, 20, 10, "A"), _text(100, 100, 20, 10, "B")]
        assert detect_overlaps(bounds) == []

    def test_text_on_text_overlap_detected(self):
        bounds = [
            _text(0, 0, 20, 10, "Lakhs"),
            _text(5, 0, 20, 10, "Thousands"),
        ]
        overlaps = detect_overlaps(bounds)
        assert len(overlaps) == 1
        assert overlaps[0].a_label == "Lakhs"
        assert overlaps[0].b_label == "Thousands"
        assert overlaps[0].iou > DEFAULT_IOU_THRESHOLD

    def test_text_on_dense_graphics_detected(self):
        bounds = [
            _text(10, 10, 30, 20, "inside"),
            _graphics(0, 0, 100, 100, dense=True),
        ]
        overlaps = detect_overlaps(bounds)
        assert len(overlaps) == 1
        assert overlaps[0].iou == 1.0

    def test_text_on_transparent_graphics_not_flagged(self):
        bounds = [
            _text(10, 10, 30, 20, "inside"),
            _graphics(0, 0, 100, 100, dense=False),
        ]
        # Transparent graphics never count as a collision candidate.
        assert detect_overlaps(bounds) == []

    def test_graphics_on_graphics_not_flagged_even_if_overlapping(self):
        bounds = [
            _graphics(0, 0, 50, 50, dense=True),
            _graphics(10, 10, 50, 50, dense=True),
        ]
        # Two Graphics with no Text involved — explicitly not flagged.
        assert detect_overlaps(bounds) == []

    def test_threshold_configurable(self):
        # 3% overlap: detected at threshold 0.02, ignored at default 0.05
        bounds = [_text(0, 0, 100, 10), _text(0, 0, 3, 10)]
        assert detect_overlaps(bounds, iou_threshold=0.02)
        # Default threshold (0.05) should also see this since IoU is 1.0 (small
        # box fully inside large) — swap to a case where IoU = 0.03
        bounds = [_text(0, 0, 100, 100), _text(97, 97, 3, 3)]
        # intersection 9, min area 9 => IoU 1.0 again. Use partial overlap:
        bounds = [_text(0, 0, 100, 100), _text(99, 99, 4, 4)]
        # IoU = intersection(1*1=1) / min(10000, 16) = 1/16 = 0.0625
        assert detect_overlaps(bounds, iou_threshold=0.02)
        assert detect_overlaps(bounds, iou_threshold=0.10) == []

    def test_ignores_hidden_objects_below_threshold(self):
        # Two texts that barely touch
        bounds = [_text(0, 0, 10, 10), _text(9, 0, 10, 10)]
        overlaps = detect_overlaps(bounds, iou_threshold=0.5)
        # IoU = 1/10 = 0.1, below 0.5 threshold
        assert overlaps == []


# ─── format_collision_report ─────────────────────────────────────────────


class TestFormatCollisionReport:
    def test_empty_returns_placeholder(self):
        assert format_collision_report([]) == "(no overlaps detected)"

    def test_includes_coords_and_iou(self):
        bounds = [
            _text(10, 20, 30, 15, "Lakhs"),
            _text(15, 20, 30, 15, "Thousands"),
        ]
        overlaps = detect_overlaps(bounds)
        report = format_collision_report(overlaps)
        assert "Lakhs" in report
        assert "Thousands" in report
        assert "IoU" in report
        # Coords should be present
        assert "(10,20" in report
