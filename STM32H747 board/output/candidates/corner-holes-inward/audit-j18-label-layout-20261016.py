"""Read-only static J18 label geometry review; emits its own report only."""
import hashlib
import importlib.util
import json
import math
import sys
from pathlib import Path

from shapely.geometry import Point, box

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "output/validation/native-multilayer-cn1_cutout_192_20261016-reopened.epru"
OUT = Path(__file__).resolve().parent / "j18-bottom-label-layout-review-20261016.json"
MM = .0254
GLYPHS = {"0": [0, 14, -12, 9], "1": [0, 5, -12, 9], "2": [0, 14, -12, 9],
          "3": [0, 14, -12, 9], "4": [0, 15, -12, 9], "5": [0, 14, -12, 9],
          "6": [0, 13, -12, 9], "7": [0, 14, -12, 9], "8": [0, 14, -12, 9],
          "9": [0, 13, -12, 9], "P": [0, 14, -12, 9], "D": [0, 14, -12, 9],
          "B": [0, 14, -12, 9], "C": [0, 15, -12, 9], "G": [0, 15, -12, 9],
          "N": [0, 14, -12, 9], "M": [0, 16, -12, 9], "S": [0, 14, -12, 9],
          "O": [0, 16, -12, 9], "K": [0, 14, -12, 9], "I": [0, 0, -12, 9],
          "V": [0, 16, -12, 9], "J": [0, 10, -12, 9], "+": [0, 18, -9, 9], "n": [0, 11, -5, 9]}
PINS = {1: (47.765, 3.935001, "SPI2_SCK", "PD3", "SCK"),
        2: (47.765, 6.475001, "SPI2_MOSI", "PB15", "MOSI"),
        3: (45.225, 3.935001, "GND", "", "GND"),
        4: (45.225, 6.475001, "SPI2_SOFT_CSn", "PC7", "CSn"),
        5: (42.685001, 3.935001, "GND", "", "GND"),
        6: (42.685, 6.475001, "GND", "", "GND"),
        7: (40.145, 3.935001, "GND", "", "GND"),
        8: (40.145, 6.475001, "GND", "", "GND"),
        9: (37.605, 3.935001, "+3V3", "", "+3V3"),
        10: (37.605, 6.475001, "+3V3", "", "+3V3")}


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def metrics(text, size, stroke=.12):
    height = size - stroke
    factor = height / 32
    position = stroke / 2
    maximum = 0
    min_y, max_y = math.inf, -math.inf
    for ch in text:
        if ch == " ":
            position += height * .7
            continue
        left, right, bottom, top = GLYPHS[ch]
        # Match the installed BFe default-stroke-font's 0.01 internal-unit
        # rounding, where one internal PCB unit is 10 mil / 0.254 mm.
        maximum = round((position + factor * right) / .254 * 100) / 100 * .254
        min_y, max_y = min(min_y, bottom * factor), max(max_y, top * factor)
        position = maximum + stroke + height * .15
    return {"text": text, "font_size_mm": size, "line_width_mm": stroke,
            "model_width_mm": maximum + stroke / 2,
            "actual_cap_ink_height_mm": max_y - min_y + stroke}


def main():
    planner = load_module("corner_planner_label_review", ROOT / "scripts/plan-corner-holes-inward-20261016.py")
    m = planner.helper()
    rows = [planner.record(m, line) for line in SOURCE.read_text(encoding="utf-8-sig").splitlines() if line]
    pads = planner.load_pads(m, rows)
    mask = []
    j18_pads = []
    for p in pads.values():
        geometry = m.pad_copper_geometry(p["pad_body"], p["component_body"], 2)
        if geometry.is_empty:
            continue
        # Baseline default 2.0079 mil solder-mask expansion = 0.05100066 mm.
        geometry = geometry.buffer(2.0079)
        mask.append((p["object_id"], p["reference"], geometry))
        if p["reference"] == "J18":
            j18_pads.append(p)
            expected = PINS[int(p["number"])]
            assert p["net_name"] == expected[2]
            point = m.pad_hole_geometry(p["pad_body"], p["component_body"]).centroid
            assert math.dist((point.x * MM, point.y * MM), expected[:2]) < .000005
    assert len(j18_pads) == 10
    for r in rows:
        if r.kind == "PAD" and not r.body.get("plated"):
            mask.append((r.record_id, "free NPTH", Point(r.body["centerX"], r.body["centerY"]).buffer(r.body["hole"]["width"] / 2)))
    scenarios = []
    for function_size in (.65, .9):
        labels = []
        for pin, (x, y, net, gpio, function) in PINS.items():
            odd = pin % 2
            header = str(pin) + (" " + gpio if gpio else "")
            for kind, text, yy, size in (("header", header, 1.15 if odd else 8.2, .65),
                                         ("function", function, 2.15 if odd else 9.2, function_size)):
                metric = metrics(text, size)
                width = metric["model_width_mm"]
                # Full nominal line-height boxes are deliberately more
                # conservative than the cap-glyph bounds for vertical checks.
                rectangle = box((x - width / 2) / MM, (yy - size / 2) / MM,
                                (x + width / 2) / MM, (yy + size / 2) / MM)
                nearest = min((rectangle.distance(g) * MM, oid, ref) for oid, ref, g in mask)
                edge = min(x - width / 2, 100 - x - width / 2, yy - size / 2, 154 - yy - size / 2)
                labels.append({"pin": pin, "kind": kind, "x_mm": x, "y_mm": yy, "layer": "Bottom Silkscreen",
                               "mirror": True, "alignment": "CENTER", **metric,
                               "minimum_mask_or_drill_clearance_mm": nearest[0],
                               "nearest_mask_object": nearest[1], "nearest_component": nearest[2],
                               "board_edge_clearance_mm": edge, "geometry": rectangle})
        title_metric = metrics("J18 SPI2", .9)
        tx, ty, ts = 42.685, 10.5, .9
        tw = title_metric["model_width_mm"]
        title_rect = box((tx - tw / 2) / MM, (ty - ts / 2) / MM,
                         (tx + tw / 2) / MM, (ty + ts / 2) / MM)
        nearest = min((title_rect.distance(g) * MM, oid, ref) for oid, ref, g in mask)
        labels.append({"pin": None, "kind": "title", "x_mm": tx, "y_mm": ty,
                       "layer": "Bottom Silkscreen", "mirror": True, "alignment": "CENTER",
                       **title_metric, "minimum_mask_or_drill_clearance_mm": nearest[0],
                       "nearest_mask_object": nearest[1], "nearest_component": nearest[2],
                       "board_edge_clearance_mm": min(tx - tw / 2, 100 - tx - tw / 2, ty - ts / 2, 154 - ty - ts / 2),
                       "geometry": title_rect})
        pairs = []
        for i, a in enumerate(labels):
            for b in labels[i + 1:]:
                pairs.append((a["geometry"].distance(b["geometry"]) * MM, a["text"], b["text"]))
        nearest_pair = min(pairs)
        minimum_mask = min(v["minimum_mask_or_drill_clearance_mm"] for v in labels)
        minimum_edge = min(v["board_edge_clearance_mm"] for v in labels)
        assert nearest_pair[0] > .15 and minimum_mask > .15 and minimum_edge > .15
        for label in labels:
            label.pop("geometry")
        scenarios.append({"function_font_size_mm": function_size, "status": "PASS_CONSERVATIVE_STATIC_GEOMETRY",
                          "minimum_label_pair_clearance_mm": nearest_pair[0], "nearest_text_pair": nearest_pair[1:],
                          "minimum_mask_or_drill_clearance_mm": minimum_mask,
                          "minimum_board_edge_clearance_mm": minimum_edge, "labels": labels})
    report = {"status": "PASS_STATIC_LAYOUT_WITH_LEGIBILITY_CAUTION",
              "source": str(SOURCE.relative_to(ROOT)), "source_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
              "native_calls": False, "project_modified": False,
              "font_data_source": "Installed EasyEDA pcb.js 3.2.193.682ed44e Qy.fontPath and Qd/BFe default-stroke-font metrics",
              "font_literal_sha256": "77fb93d6c3f1e02e158f64247348fd07aa23b5d15737627d9eb0e6825c11e37f",
              "font_metric_caveat": "A later loaded renderer may differ; verify actual final exported Gerber glyph bounds.",
              "front_view_columns_left_to_right": [[9, 10], [7, 8], [5, 6], [3, 4], [1, 2]],
              "back_view_columns_left_to_right_when_flipped_about_vertical_axis": [[1, 2], [3, 4], [5, 6], [7, 8], [9, 10]],
              "mask_expansion_mm": 2.0079 * MM,
              "readability": "0.65 mm default-font line height yields only 0.468 mm visible capital height. Keep short pin/GPIO header at 0.65 mm but enlarge main function row to 0.9 mm (visible cap height 0.632 mm). Do not combine all GPIO/function words into one long line at 2.54 mm pitch.",
              "scenarios": scenarios}
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"path": str(OUT), "sha256": hashlib.sha256(OUT.read_bytes()).hexdigest(),
                      "scenarios": [{k: v for k, v in s.items() if k != "labels"} for s in scenarios]}, indent=2))


if __name__ == "__main__":
    main()
