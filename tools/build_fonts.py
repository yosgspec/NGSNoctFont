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
from fontTools.ttLib import TTCollection, TTFont
from shapely.geometry import LineString, MultiPolygon, Point, Polygon, box
from shapely.geometry.polygon import orient
from shapely.ops import unary_union


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SVG_NS = "http://www.w3.org/2000/svg"
UNITS_PER_EM = 1000
SVG_SCALE = 200
MONO_ADVANCE_WIDTH = 500
PROP_SIDE_BEARING = 40
CAP_HEIGHT = 800
X_HEIGHT = 410
ASCENDER = 850
DESCENDER = -450
BASELINES = {
    "digits": 5,
    "uppercase": 5,
    "lowercase_m": 5,
    "lowercase_p": 5,
}
ROWS = {
    "digits": "1234567890",
    "uppercase": "ABCDEFGHIJKLMNOPQRSTUVWXYZ",
    "lowercase_m": "abcdefghijklmnopqrstuvwxyz",
    "lowercase_p": "abcdefghijklmnopqrstuvwxyz",
}
ASCII_SYMBOLS = string.punctuation
EXTRA_SYMBOLS = "£¥©®–—‘’“”…€™"
SYMBOLS = ASCII_SYMBOLS + EXTRA_SYMBOLS
SYMBOL_BASELINES = {
    **{character: 5 for character in SYMBOLS},
}

Matrix = tuple[float, float, float, float, float, float]
IDENTITY: Matrix = (1, 0, 0, 1, 0, 0)
TRANSFORM_RE = re.compile(r"([A-Za-z]+)\s*\(([^)]*)\)")
NUMBER_RE = re.compile(r"[-+]?(?:\d*\.\d+|\d+\.?\d*)(?:[eE][-+]?\d+)?")


def glyph_filename(character: str) -> str:
    if ord(character) >= 32 and character not in '<>:"/\\|?* ':
        stem = character
    else:
        stem = "_"
    return f"{stem}_{ord(character):04X}.svg"


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


def make_geometry(svg_path: Path, baseline: float, stroke_scale: float = 1.0):
    root = ET.parse(svg_path).getroot()
    strokes = collect_strokes(root)
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
                stroke.width * stroke_scale * SVG_SCALE / 2,
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


def glyph_from_geometry(
    geometry,
    advance_width: float,
    left_bearing: float,
    is_monospaced: bool,
):
    pen = TTGlyphPen(None)
    min_x, _, max_x, _ = geometry.bounds
    x_offset = (
        advance_width / 2 - (min_x + max_x) / 2
        if is_monospaced
        else left_bearing - min_x
    )
    outline_min_x = math.inf
    for polygon in polygons_from(geometry):
        polygon = orient(polygon, sign=-1.0)
        rings = [polygon.exterior, *polygon.interiors]
        for ring in rings:
            coordinates = [
                (round(x + x_offset), round(y))
                for x, y in list(ring.coords)[:-1]
            ]
            if coordinates:
                outline_min_x = min(outline_min_x, *(point[0] for point in coordinates))
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
    return pen.glyph(), int(outline_min_x)


def empty_glyph():
    return TTGlyphPen(None).glyph()


def notdef_glyph(advance_width: float):
    pen = TTGlyphPen(None)
    left = max(50, round(advance_width * 0.15))
    right = advance_width - left
    pen.moveTo((left, 0))
    pen.lineTo((left, 700))
    pen.lineTo((right, 700))
    pen.lineTo((right, 0))
    pen.closePath()
    return pen.glyph()


def build_font(
    variant: str,
    glyph_dir: Path,
    output_dir: Path,
    compact: bool = False,
    bold: bool = False,
) -> tuple[Path, Path]:
    is_monospaced = variant in ("lc1", "m")
    mono_advance = MONO_ADVANCE_WIDTH
    default_advance = mono_advance if is_monospaced else 260
    lowercase_family = "lowercase_m" if is_monospaced else "lowercase_p"
    lowercase_dir = glyph_dir / lowercase_family
    source_dirs = {
        "digits": glyph_dir / "digits",
        "uppercase": glyph_dir / "uppercase",
        "lowercase": lowercase_dir,
    }
    alphanumeric = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    characters = alphanumeric + SYMBOLS
    baseline_by_character = {
        **{character: BASELINES["digits"] for character in "0123456789"},
        **{character: BASELINES["uppercase"] for character in string.ascii_uppercase},
        **{character: BASELINES[lowercase_family] for character in string.ascii_lowercase},
        **SYMBOL_BASELINES,
    }
    source_by_character = {
        **{character: source_dirs["digits"] / glyph_filename(character) for character in "0123456789"},
        **{character: source_dirs["uppercase"] / glyph_filename(character) for character in string.ascii_uppercase},
        **{character: source_dirs["lowercase"] / glyph_filename(character) for character in string.ascii_lowercase},
        **{character: glyph_dir / "symbols" / glyph_filename(character) for character in SYMBOLS},
    }
    if compact:
        short_lowercase_dir = glyph_dir / ("lowercase_mf" if is_monospaced else "lowercase_pf")
        for character in "gpq":
            source_by_character[character] = short_lowercase_dir / glyph_filename(character)

    glyph_order = [".notdef", "space"]
    glyph_names = {character: f"uni{ord(character):04X}" for character in characters}
    glyph_order.extend(glyph_names[character] for character in characters)
    notdef_left_bearing = max(50, round(default_advance * 0.15))
    glyphs = {".notdef": notdef_glyph(default_advance), "space": empty_glyph()}
    space_advance = mono_advance if is_monospaced else 260
    metrics = {
        ".notdef": (default_advance, notdef_left_bearing),
        "space": (space_advance, 0),
    }

    for character, glyph_name in glyph_names.items():
        source = source_by_character[character]
        if not source.exists():
            raise FileNotFoundError(f"missing glyph SVG: {source}")
        geometry, _ = make_geometry(source, baseline_by_character[character], 1.4 if bold else 1.0)
        if compact and character == "|":
            geometry = geometry.intersection(box(-1_000_000, 0, 1_000_000, 1_000_000))
        glyph_width = geometry.bounds[2] - geometry.bounds[0]
        advance_width = (
            mono_advance
            if is_monospaced
            else math.ceil(glyph_width + PROP_SIDE_BEARING * 2)
        )
        glyphs[glyph_name], left_bearing = glyph_from_geometry(
            geometry,
            advance_width,
            PROP_SIDE_BEARING,
            is_monospaced,
        )
        metrics[glyph_name] = (advance_width, left_bearing)

    family_name, postscript_name = (
        ("NGS Noct M", "NGSNoctM")
        if is_monospaced
        else ("NGS Noct P", "NGSNoctP")
    )
    if compact:
        family_name = "NGS Noct MF" if is_monospaced else "NGS Noct PF"
        postscript_name = "NGSNoctMF" if is_monospaced else "NGSNoctPF"
    if bold:
        postscript_name += "-Bold"
    style_name = "Bold" if bold else "Regular"
    full_name = f"{family_name} {style_name}" if bold else family_name
    builder = FontBuilder(UNITS_PER_EM, isTTF=True)
    builder.setupGlyphOrder(glyph_order)
    builder.setupCharacterMap({32: "space", **{ord(char): glyph_names[char] for char in characters}})
    builder.setupGlyf(glyphs)
    builder.setupHorizontalMetrics(metrics)
    descender = DESCENDER + 2 * SVG_SCALE if compact else DESCENDER
    builder.setupHorizontalHeader(ascent=ASCENDER, descent=descender)
    builder.setupNameTable(
        {
            "familyName": family_name,
            "styleName": style_name,
            "uniqueFontIdentifier": f"{postscript_name}-1.0",
            "fullName": full_name,
            "psName": postscript_name,
            "version": "Version 1.0",
        }
    )
    builder.setupOS2(
        sTypoAscender=ASCENDER,
        sTypoDescender=descender,
        sTypoLineGap=100,
        usWinAscent=900,
        usWinDescent=abs(descender),
        sxHeight=X_HEIGHT,
        sCapHeight=CAP_HEIGHT,
        usWeightClass=700 if bold else 400,
        usWidthClass=5,
    )
    builder.setupPost(isFixedPitch=1 if is_monospaced else 0)
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
    parser = argparse.ArgumentParser(description="Build NGS Noct M/P/MF/PF TTF, WOFF2, and TTC fonts from glyph SVGs.")
    parser.add_argument("--glyph-dir", type=Path, default=PROJECT_ROOT / "src" / "charsvg")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "fonts")
    parser.add_argument("--variant", choices=("lc1", "lc2", "both"), default="both")
    args = parser.parse_args()

    variants = ("lc1", "lc2") if args.variant == "both" else (args.variant,)
    try:
        ttf_paths = []
        for variant in variants:
            for compact in (False, True):
                for bold in (False, True):
                    for path in build_font(variant, args.glyph_dir, args.output_dir, compact, bold):
                        print(f"Generated {path}")
                        if path.suffix == ".ttf":
                            ttf_paths.append(path)
        if args.variant == "both":
            collection = TTCollection()
            collection.fonts = [TTFont(path) for path in ttf_paths]
            collection_path = args.output_dir / "NGSNoct.ttc"
            collection.save(collection_path)
            collection.close()
            print(f"Generated {collection_path}")
    except (ET.ParseError, OSError, ValueError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    sys.exit(main())
