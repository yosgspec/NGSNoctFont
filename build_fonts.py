from __future__ import annotations

import argparse
import math
import re
import string
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.recordingPen import RecordingPen
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.svgLib.path import parse_path
from shapely.geometry import LineString, MultiPolygon, Point, Polygon
from shapely.geometry.polygon import orient
from shapely.ops import unary_union


SVG_NS = "http://www.w3.org/2000/svg"
UNITS_PER_EM = 1000
SVG_SCALE = 5
ADVANCE_WIDTH = 500
CAP_HEIGHT = 800
X_HEIGHT = 410
ASCENDER = 850
DESCENDER = -450
BASELINES = {
    "digits": 162,
    "uppercase": 482,
    "lowercase_1": 802,
    "lowercase_2": 1122,
}
ROWS = {
    "digits": "1234567890",
    "uppercase": "ABCDEFGHIJKLMNOPQRSTUVWXYZ",
    "lowercase_1": "abcdefghijklmnopqrstuvwxyz",
    "lowercase_2": "abcdefghijklmnopqrstuvwxyz",
}

Matrix = tuple[float, float, float, float, float, float]
IDENTITY: Matrix = (1, 0, 0, 1, 0, 0)
TRANSFORM_RE = re.compile(r"([A-Za-z]+)\s*\(([^)]*)\)")
NUMBER_RE = re.compile(r"[-+]?(?:\d*\.\d+|\d+\.?\d*)(?:[eE][-+]?\d+)?")


@dataclass(frozen=True)
class Stroke:
    points: tuple[tuple[float, float], ...]
    closed: bool
    width: float


def compose(parent: Matrix, child: Matrix) -> Matrix:
    a, b, c, d, e, f = parent
    g, h, i, j, k, l = child
    return (
        a * g + c * h,
        b * g + d * h,
        a * i + c * j,
        b * i + d * j,
        a * k + c * l + e,
        b * k + d * l + f,
    )


def parse_transform(value: str | None) -> Matrix:
    result = IDENTITY
    if not value:
        return result
    for name, argument_text in TRANSFORM_RE.findall(value):
        values = [float(number) for number in NUMBER_RE.findall(argument_text)]
        name = name.lower()
        if name == "translate" and values:
            local = (1, 0, 0, 1, values[0], values[1] if len(values) > 1 else 0)
        elif name == "scale" and values:
            local = (values[0], 0, 0, values[1] if len(values) > 1 else values[0], 0, 0)
        elif name == "rotate" and values:
            angle = math.radians(values[0])
            cosine, sine = math.cos(angle), math.sin(angle)
            rotation = (cosine, sine, -sine, cosine, 0, 0)
            if len(values) >= 3:
                cx, cy = values[1:3]
                local = compose(compose((1, 0, 0, 1, cx, cy), rotation), (1, 0, 0, 1, -cx, -cy))
            else:
                local = rotation
        elif name == "matrix" and len(values) == 6:
            local = tuple(values)  # type: ignore[assignment]
        elif name == "skewx" and values:
            local = (1, 0, math.tan(math.radians(values[0])), 1, 0, 0)
        elif name == "skewy" and values:
            local = (1, math.tan(math.radians(values[0])), 0, 1, 0, 0)
        else:
            raise ValueError(f"unsupported SVG transform: {name}({argument_text})")
        result = compose(result, local)
    return result


def apply_matrix(matrix: Matrix, point: tuple[float, float]) -> tuple[float, float]:
    a, b, c, d, e, f = matrix
    x, y = point
    return a * x + c * y + e, b * x + d * y + f


def distance(first: tuple[float, float], second: tuple[float, float]) -> float:
    return math.hypot(second[0] - first[0], second[1] - first[1])


def flatten_cubic(
    start: tuple[float, float],
    control1: tuple[float, float],
    control2: tuple[float, float],
    end: tuple[float, float],
) -> list[tuple[float, float]]:
    estimate = distance(start, control1) + distance(control1, control2) + distance(control2, end)
    steps = max(3, min(256, math.ceil(estimate / 1.25)))
    result = []
    for index in range(1, steps + 1):
        t = index / steps
        inverse = 1 - t
        result.append(
            (
                inverse**3 * start[0]
                + 3 * inverse**2 * t * control1[0]
                + 3 * inverse * t**2 * control2[0]
                + t**3 * end[0],
                inverse**3 * start[1]
                + 3 * inverse**2 * t * control1[1]
                + 3 * inverse * t**2 * control2[1]
                + t**3 * end[1],
            )
        )
    return result


def flatten_quadratic(
    start: tuple[float, float], control: tuple[float, float], end: tuple[float, float]
) -> list[tuple[float, float]]:
    estimate = distance(start, control) + distance(control, end)
    steps = max(2, min(256, math.ceil(estimate / 1.25)))
    result = []
    for index in range(1, steps + 1):
        t = index / steps
        inverse = 1 - t
        result.append(
            (
                inverse**2 * start[0] + 2 * inverse * t * control[0] + t**2 * end[0],
                inverse**2 * start[1] + 2 * inverse * t * control[1] + t**2 * end[1],
            )
        )
    return result


def flatten_path(operations: list[tuple[str, tuple]]) -> list[tuple[list[tuple[float, float]], bool]]:
    subpaths = []
    points: list[tuple[float, float]] = []
    start: tuple[float, float] | None = None
    current: tuple[float, float] | None = None

    def finish(closed: bool) -> None:
        nonlocal points, start, current
        if len(points) > 1:
            subpaths.append((points, closed))
        points = []
        start = None
        current = None

    for operation, operands in operations:
        if operation == "moveTo":
            if points:
                finish(False)
            start = current = (float(operands[0][0]), float(operands[0][1]))
            points = [current]
        elif operation == "lineTo" and current is not None:
            current = (float(operands[0][0]), float(operands[0][1]))
            points.append(current)
        elif operation == "curveTo" and current is not None:
            for index in range(0, len(operands), 3):
                control1, control2, end = operands[index : index + 3]
                control1 = (float(control1[0]), float(control1[1]))
                control2 = (float(control2[0]), float(control2[1]))
                end = (float(end[0]), float(end[1]))
                points.extend(flatten_cubic(current, control1, control2, end))
                current = end
        elif operation == "qCurveTo" and current is not None:
            curve_points = list(operands)
            implied_end = curve_points[-1] is None
            if implied_end:
                controls = curve_points[:-1]
                endpoint = start
            else:
                controls = curve_points[:-1]
                final = curve_points[-1]
                endpoint = (float(final[0]), float(final[1]))
            for index, control in enumerate(controls):
                control_point = (float(control[0]), float(control[1]))
                if index + 1 < len(controls):
                    next_control = controls[index + 1]
                    end_point = (
                        (control_point[0] + float(next_control[0])) / 2,
                        (control_point[1] + float(next_control[1])) / 2,
                    )
                else:
                    end_point = endpoint
                if end_point is not None:
                    points.extend(flatten_quadratic(current, control_point, end_point))
                    current = end_point
        elif operation == "closePath":
            if points and start is not None:
                if distance(points[-1], start) > 1e-6:
                    points.append(start)
                finish(True)
        elif operation == "endPath":
            finish(False)
    if points:
        finish(False)
    return subpaths


def collect_strokes(element: ET.Element, parent_transform: Matrix = IDENTITY) -> list[Stroke]:
    local_transform = compose(parent_transform, parse_transform(element.get("transform")))
    strokes = []
    if element.tag == f"{{{SVG_NS}}}path" and element.get("d") and element.get("stroke") != "none":
        recording = RecordingPen()
        parse_path(element.get("d", ""), TransformPen(recording, local_transform))
        width = float(element.get("stroke-width", "1"))
        for points, closed in flatten_path(recording.value):
            strokes.append(Stroke(tuple(points), closed, width))
    for child in element:
        strokes.extend(collect_strokes(child, local_transform))
    return strokes


def make_geometry(svg_path: Path, baseline: float):
    root = ET.parse(svg_path).getroot()
    layer = next(
        (element for element in root.iter(f"{{{SVG_NS}}}g") if element.get("data-cell-id") == "1"),
        None,
    )
    if layer is None:
        raise ValueError(f"missing draw.io layer in {svg_path}")
    glyph_groups = [
        child
        for child in layer
        if child.get("data-cell-id") not in (None, "0", "1")
    ]
    if len(glyph_groups) != 1:
        raise ValueError(f"expected one glyph group in {svg_path}, found {len(glyph_groups)}")

    strokes = collect_strokes(glyph_groups[0])
    if not strokes:
        raise ValueError(f"no stroked paths in {svg_path}")

    shapes = []
    for stroke in strokes:
        points = [
            (x * SVG_SCALE, (baseline - y) * SVG_SCALE)
            for x, y in stroke.points
        ]
        if len(points) == 1:
            centerline = Point(points[0])
        else:
            centerline = LineString(points)
        shapes.append(
            centerline.buffer(
                stroke.width * SVG_SCALE / 2,
                cap_style="round",
                join_style="round",
                quad_segs=8,
            )
        )

    merged = unary_union(shapes)
    min_x = merged.bounds[0]
    return merged, min_x


def polygons_from(geometry) -> Iterable[Polygon]:
    if isinstance(geometry, Polygon):
        yield geometry
    elif isinstance(geometry, MultiPolygon) or hasattr(geometry, "geoms"):
        for part in geometry.geoms:
            yield from polygons_from(part)


def glyph_from_geometry(geometry):
    pen = TTGlyphPen(None)
    min_x, _, max_x, _ = geometry.bounds
    x_offset = (ADVANCE_WIDTH - (max_x - min_x)) / 2 - min_x
    for polygon in polygons_from(geometry):
        polygon = orient(polygon, sign=-1.0)
        rings = [polygon.exterior, *polygon.interiors]
        for ring in rings:
            coordinates = [
                (round(x + x_offset), round(y))
                for x, y in list(ring.coords)[:-1]
            ]
            cleaned = []
            for point in coordinates:
                if not cleaned or point != cleaned[-1]:
                    cleaned.append(point)
            if len(cleaned) < 3:
                continue
            pen.moveTo(cleaned[0])
            for point in cleaned[1:]:
                pen.lineTo(point)
            pen.closePath()
    return pen.glyph()


def empty_glyph():
    return TTGlyphPen(None).glyph()


def notdef_glyph():
    pen = TTGlyphPen(None)
    pen.moveTo((75, 0))
    pen.lineTo((75, 700))
    pen.lineTo((425, 700))
    pen.lineTo((425, 0))
    pen.closePath()
    return pen.glyph()


def build_font(variant: str, glyph_dir: Path, output_dir: Path) -> tuple[Path, Path]:
    lowercase_dir = glyph_dir / ("lowercase_1" if variant == "lc1" else "lowercase_2")
    source_dirs = {
        "digits": glyph_dir / "digits",
        "uppercase": glyph_dir / "uppercase",
        "lowercase": lowercase_dir,
    }
    characters = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    baseline_by_character = {
        **{character: BASELINES["digits"] for character in "0123456789"},
        **{character: BASELINES["uppercase"] for character in string.ascii_uppercase},
        **{character: BASELINES[f"lowercase_{variant[-1]}"] for character in string.ascii_lowercase},
    }
    source_by_character = {
        **{character: source_dirs["digits"] / f"{character}.svg" for character in "0123456789"},
        **{character: source_dirs["uppercase"] / f"{character}.svg" for character in string.ascii_uppercase},
        **{character: source_dirs["lowercase"] / f"{character}.svg" for character in string.ascii_lowercase},
    }

    glyph_order = [".notdef", "space"]
    glyph_names = {character: f"uni{ord(character):04X}" for character in characters}
    glyph_order.extend(glyph_names[character] for character in characters)
    glyphs = {".notdef": notdef_glyph(), "space": empty_glyph()}
    metrics = {".notdef": (ADVANCE_WIDTH, 0), "space": (ADVANCE_WIDTH, 0)}

    for character, glyph_name in glyph_names.items():
        source = source_by_character[character]
        if not source.exists():
            raise FileNotFoundError(f"missing glyph SVG: {source}")
        geometry, _ = make_geometry(source, baseline_by_character[character])
        glyphs[glyph_name] = glyph_from_geometry(geometry)
        metrics[glyph_name] = (ADVANCE_WIDTH, 0)

    family_name = f"NGSCS Font {variant.upper()} Mono"
    postscript_name = f"NGSCSFont-{variant.upper()}-Mono"
    builder = FontBuilder(UNITS_PER_EM, isTTF=True)
    builder.setupGlyphOrder(glyph_order)
    builder.setupCharacterMap({32: "space", **{ord(char): glyph_names[char] for char in characters}})
    builder.setupGlyf(glyphs)
    builder.setupHorizontalMetrics(metrics)
    builder.setupHorizontalHeader(ascent=ASCENDER, descent=DESCENDER)
    builder.setupNameTable(
        {
            "familyName": family_name,
            "styleName": "Regular",
            "uniqueFontIdentifier": f"{postscript_name}-1.0",
            "fullName": family_name,
            "psName": postscript_name,
            "version": "Version 1.0",
        }
    )
    builder.setupOS2(
        sTypoAscender=ASCENDER,
        sTypoDescender=DESCENDER,
        sTypoLineGap=100,
        usWinAscent=900,
        usWinDescent=450,
        sxHeight=X_HEIGHT,
        sCapHeight=CAP_HEIGHT,
        usWeightClass=400,
        usWidthClass=5,
    )
    builder.setupPost(isFixedPitch=1)
    builder.setupMaxp()

    output_dir.mkdir(parents=True, exist_ok=True)
    ttf_path = output_dir / f"{postscript_name}.ttf"
    woff2_path = output_dir / f"{postscript_name}.woff2"
    font = builder.font
    font.save(ttf_path)
    font.flavor = "woff2"
    font.save(woff2_path)
    return ttf_path, woff2_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Build LC1 and LC2 TTF/WOFF2 fonts from grouped glyph SVGs.")
    parser.add_argument("--glyph-dir", type=Path, default=Path(__file__).with_name("split_glyphs"))
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).with_name("fonts"))
    parser.add_argument("--variant", choices=("lc1", "lc2", "both"), default="both")
    args = parser.parse_args()

    variants = ("lc1", "lc2") if args.variant == "both" else (args.variant,)
    try:
        for variant in variants:
            for path in build_font(variant, args.glyph_dir, args.output_dir):
                print(f"Generated {path}")
    except (ET.ParseError, OSError, ValueError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    sys.exit(main())