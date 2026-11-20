from __future__ import annotations

import argparse
import math
import re
import string
import sys
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape
from dataclasses import dataclass
from pathlib import Path

from fontTools.pens.transformPen import TransformPen
from fontTools.pens.recordingPen import RecordingPen
from fontTools.svgLib.path import parse_path

from build_fonts import IDENTITY, compose, parse_transform

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SVG_NS = "http://www.w3.org/2000/svg"
DRAWING_COORD_OFFSET = 155
GRID_STEP = 40
GRID_Y_OFFSET = 1
GRID_BASELINE = 5
GRID_VIEWBOX_X = -0.5
GRID_VIEWBOX_Y = 0.8
GRID_VIEWBOX_WIDTH = 3.0
GRID_VIEWBOX_HEIGHT = 6.4
GRID_CENTER_X = 1.0
PATH_TOKEN = re.compile(r"[A-Za-z]|[-+]?(?:\d*\.\d+|\d+\.?\d*)(?:[eE][-+]?\d+)?")

ET.register_namespace("", SVG_NS)
ET.register_namespace("xlink", "http://www.w3.org/1999/xlink")


@dataclass(frozen=True)
class Row:
    folder: str
    characters: str
    min_y: float
    max_y: float


@dataclass(frozen=True)
class Glyph:
    cell_id: str
    x: float
    y: float
    width: float
    height: float


ROWS = (
    Row("digits", "1234567890", 100, 400),
    Row("uppercase", string.ascii_uppercase, 400, 700),
    Row("lowercase_m", string.ascii_lowercase, 700, 1050),
    Row("lowercase_p", string.ascii_lowercase, 1050, 1400),
)
ASCII_SYMBOLS = string.punctuation
EXTRA_SYMBOLS = "£¥©®–—‘’“”…€™"
SYMBOL_ROWS = (
    (ASCII_SYMBOLS[:26], 1350, 1650),
    (ASCII_SYMBOLS[26:] + EXTRA_SYMBOLS, 1650, 2000),
)
GLYPH_PATH_OVERRIDES = {
    ("digits", "3"): "M0 1 L1 1 A1 1 0 0 1 1 3 L0 3 L1 3 A1 1 0 0 1 1 5 L0 5",
    ("digits", "6"): "M1 3 A1 1 0 1 1 0 4 L0 2 M0 3 L1 3 M0 2 A1 1 0 1 1 2 2",
    ("uppercase", "B"): "M0 5 L0 1 L1 1 A1 1 0 0 1 1 3 L0 3 L1 3 A1 1 0 0 1 1 5 L0 5",
    ("lowercase_1", "e"): "M1 5 A1 1 0 1 1 2 4 M0 4 L2 4 M1 5 L2 5",
    ("lowercase_2", "e"): "M0 4 L1 4 M1 5 A1 1 0 0 1 1 3 M1 4 L1 3",
    ("uppercase", "K"): "M0 5 L0 1 M2 4 L2 5 M2 2 L2 1 M1 3 A1 1 0 0 1 2 4 M0 3 L1 3 M2 2 A1 1 0 0 1 1 3",
    ("uppercase", "M"): "M1 5 L1 1 A1 1 0 0 1 2 2 L2 5 L2 2 A1 1 0 0 1 3 1 L3 5",
    ("uppercase", "P"): "M0 5 L0 1 L1 1 A1 1 0 0 1 1 3 L0 3",
    ("uppercase", "R"): "M0 5 L0 1 L1 1 A1 1 0 0 1 1 3 L0 3 L1 3 A1 1 0 0 1 2 4 L2 5",
    ("uppercase", "S"): "M1 3 A1 1 0 1 1 2 2 M1 3 A1 1 0 1 1 0 4",
    ("lowercase_1", "n"): "M0 3 L0 5 M0 4 A1 1 0 1 1 2 4 M2 5 L2 4",
    ("symbols", "$"): "M1 3 A1 1 0 1 1 2 2 M1 3 A1 1 0 1 1 0 4 M1 5 L1 1",
    ("symbols", "?"): "M0 2 A1 1 0 1 1 1 3 M1 4 L1 3 M1.25 5 L1 5",
    ("symbols", "£"): "M3 1 L2 1 M3 5 L1 5 M1 3 A1 1 0 0 1 1 5 M2 3 A1 1 0 0 1 2 1 M3 3 L1 3",
    ("symbols", "&"): "M2 4 A1 1 0 1 1 1 3 M2 5 A1 1 0 0 1 1 4 M1 1 L1 4 M1 1 L2 1 M2 2 A1 1 0 0 1 1 3 M2 1 L2 2",
    ("symbols", "™"): "M1 1 L0 1 M0.5 1 L0.5 2 M1 1 A1 1 0 0 1 2 2 M1 1 L1 2 M2 1 L2 2 M1 2 A1 1 0 0 1 2 1",
    ("symbols", "¥"): "M1 5 L1 2 M2 4 L0 4 M2 3 L0 3 M2 1 A1 1 0 1 1 0 1",
    ("symbols", "©"): "M0 2 A1 1 0 0 1 2 2 L2 4 A1 1 0 1 1 0 4 L0 2 M1.5 4 A1 1 0 0 1 1.5 2",
    ("symbols", "®"): "M0.5 2 A1 1 0 0 1 2.5 2 L2.5 4 A1 1 0 1 1 0.5 4 L0.5 2 M2 2 L1 2 L1 4 M2 2 A1 1 0 0 1 1 3 L2 4",
}


@dataclass(frozen=True)
class SymbolObject:
    cell_id: str
    x: float
    y: float
    width: float
    height: float
    is_edge: bool


def read_glyphs(content: str) -> list[Glyph]:
    mxfile = ET.fromstring(content)
    glyphs = []
    for cell in mxfile.findall(".//mxCell"):
        if cell.get("parent") != "1" or cell.get("vertex") != "1":
            continue

        geometry = cell.find("mxGeometry")
        if geometry is None:
            continue
        x = geometry.get("x")
        y = geometry.get("y")
        if x is None or y is None:
            continue
        if not any(row.min_y <= float(y) < row.max_y for row in ROWS):
            continue
        glyphs.append(
            Glyph(
                cell_id=cell.get("id", ""),
                x=float(x),
                y=float(y),
                width=float(geometry.get("width", "0")),
                height=float(geometry.get("height", "0")),
            )
        )
    return glyphs


def read_symbol_objects(content: str) -> list[SymbolObject]:
    mxfile = ET.fromstring(content)
    objects = []
    for cell in mxfile.findall(".//mxCell"):
        if cell.get("parent") != "1" or cell.get("id") is None:
            continue
        geometry = cell.find("mxGeometry")
        if geometry is None:
            continue

        if cell.get("vertex") == "1":
            x = geometry.get("x")
            y = geometry.get("y")
            if x is None or y is None:
                continue
            width = float(geometry.get("width", "0"))
            height = float(geometry.get("height", "0"))
            objects.append(SymbolObject(cell.get("id"), float(x), float(y), width, height, False))
        elif cell.get("edge") == "1":
            points = [
                (float(point.get("x")), float(point.get("y")))
                for point in geometry.findall(".//mxPoint")
                if point.get("x") is not None and point.get("y") is not None
            ]
            if len(points) < 2:
                continue
            x_values = [point[0] for point in points]
            y_values = [point[1] for point in points]
            objects.append(
                SymbolObject(
                    cell.get("id"),
                    min(x_values),
                    min(y_values),
                    max(x_values) - min(x_values),
                    max(y_values) - min(y_values),
                    True,
                )
            )
    return objects


def assign_rows(glyphs: list[Glyph], parser: argparse.ArgumentParser) -> list[tuple[Row, str, Glyph]]:
    assignments = []
    used_ids = set()
    for row in ROWS:
        row_glyphs = sorted(
            (glyph for glyph in glyphs if row.min_y <= glyph.y < row.max_y),
            key=lambda glyph: glyph.x,
        )
        if len(row_glyphs) != len(row.characters):
            parser.error(f"{row.folder}: expected {len(row.characters)} glyphs, found {len(row_glyphs)}")
        for character, glyph in zip(row.characters, row_glyphs):
            if not glyph.cell_id or glyph.cell_id in used_ids:
                parser.error(f"missing or duplicate draw.io cell ID in {row.folder}")
            used_ids.add(glyph.cell_id)
            assignments.append((row, character, glyph))
    if len(used_ids) != len(glyphs):
        parser.error("some top-level glyphs do not fall into a recognized character row")
    return assignments


def find_cell_groups(root: ET.Element) -> tuple[ET.Element, dict[str, ET.Element]]:
    groups = {
        element.get("data-cell-id"): element
        for element in root.iter(f"{{{SVG_NS}}}g")
        if element.get("data-cell-id")
    }
    layer = groups.get("1")
    if layer is None:
        raise ValueError("SVG does not contain draw.io layer 1")
    return layer, groups


def glyph_filename(character: str) -> str:
    if ord(character) >= 32 and character not in '<>:"/\\|?* ':
        stem = character
    else:
        stem = "_"
    return f"{stem}_{ord(character):04X}.svg"


def simple_number(text: str) -> str:
    value = float(text)
    value = round(value * 4) / 4
    return f"{value:.3f}".rstrip("0").rstrip(".")


def precise_number(value: float) -> str:
    return f"{round(value, 3):.3f}".rstrip("0").rstrip(".")


def recording_path_data(recording: RecordingPen) -> str:
    commands = []
    current = (0.0, 0.0)
    for operation, points in recording.value:
        if operation == "moveTo":
            current = points[0]
            commands.append(f"M{precise_number(current[0])} {precise_number(current[1])}")
        elif operation == "lineTo":
            start = current
            end = points[0]
            current = end
            commands.append(f"L{precise_number(end[0])} {precise_number(end[1])}")
        elif operation == "curveTo":
            p0, p1, p2, p3 = current, points[0], points[1], points[2]
            start_tangent = (p1[0] - p0[0], p1[1] - p0[1])
            end_tangent = (p3[0] - p2[0], p3[1] - p2[1])
            n1 = (start_tangent[1], -start_tangent[0])
            n2 = (end_tangent[1], -end_tangent[0])
            determinant = n1[0] * n2[1] - n1[1] * n2[0]
            if abs(determinant) < 1e-9:
                raise ValueError(f"cannot convert non-circular cubic segment to SVG arc: {points}")
            delta = (p3[0] - p0[0], p3[1] - p0[1])
            factor = (delta[0] * n2[1] - delta[1] * n2[0]) / determinant
            center = (p0[0] + factor * n1[0], p0[1] + factor * n1[1])
            radius0 = math.dist(center, p0)
            radius1 = math.dist(center, p3)
            if abs(radius0 - radius1) > 0.03:
                raise ValueError(f"cubic segment is not circular (radii {radius0:g}, {radius1:g})")
            radius = (radius0 + radius1) / 2
            sweep = int((p0[0] - center[0]) * start_tangent[1] - (p0[1] - center[1]) * start_tangent[0] > 0)
            angle0 = math.atan2(p0[1] - center[1], p0[0] - center[0])
            angle1 = math.atan2(p3[1] - center[1], p3[0] - center[0])
            angle = (angle1 - angle0) % (2 * math.pi) if sweep else (angle0 - angle1) % (2 * math.pi)
            large_arc = int(angle > math.pi + 1e-8)
            commands.append(
                f"A{precise_number(radius)} {precise_number(radius)} 0 {large_arc} {sweep} "
                f"{precise_number(p3[0])} {precise_number(p3[1])}"
            )
            current = p3
        elif operation == "closePath":
            commands.append("Z")
        elif operation == "endPath":
            continue
        else:
            raise ValueError(f"unsupported path operation for SVG output: {operation}")
    return " ".join(commands)


def baseline_alignment_offset(model_y: float, source_baseline: float) -> float:
    svg_origin_y = model_y - DRAWING_COORD_OFFSET
    source_grid_baseline = GRID_Y_OFFSET + (source_baseline - svg_origin_y) / GRID_STEP
    return GRID_BASELINE - source_grid_baseline


def readable_path_data(data: str) -> str:
    tokens = PATH_TOKEN.findall(data)
    lines = []
    index = 0
    argument_counts = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "Q": 4, "A": 7, "Z": 0}
    while index < len(tokens):
        command = tokens[index]
        index += 1
        count = argument_counts.get(command.upper())
        if count is None:
            raise ValueError(f"unsupported SVG path command: {command}")
        values = []
        while index < len(tokens) and not tokens[index].isalpha():
            values.append(tokens[index])
            index += 1
        if count == 0:
            lines.append(command)
            continue
        if len(values) % count:
            raise ValueError(f"invalid SVG path data: {data}")
        for offset in range(0, len(values), count):
            active_command = "L" if command.upper() == "M" and offset else command
            lines.append(f"{active_command}{' '.join(values[offset:offset + count])}")
    return "\n      ".join(lines)


def merge_connected_subpaths(data: str) -> str:
    tokens = PATH_TOKEN.findall(data)
    output = []
    index = 0
    current = None
    subpath_start = None
    counts = {"M": 2, "L": 2, "A": 7, "Z": 0}
    while index < len(tokens):
        command = tokens[index]
        index += 1
        kind = command.upper()
        count = counts.get(kind)
        if count is None:
            raise ValueError(f"unsupported command while merging paths: {command}")
        if count == 0:
            output.append(command)
            current = subpath_start
            continue
        values = []
        while index < len(tokens) and not tokens[index].isalpha():
            values.append(tokens[index])
            index += 1
        if len(values) % count:
            raise ValueError(f"invalid path data while merging subpaths: {data}")
        for start in range(0, len(values), count):
            segment = values[start:start + count]
            if kind == "M":
                point = (float(segment[0]), float(segment[1]))
                if current != point:
                    output.extend((command, *segment))
                    subpath_start = point
                current = point
            elif kind == "L":
                output.extend((command, *segment))
                current = (float(segment[0]), float(segment[1]))
            else:
                output.extend((command, *segment))
                current = (float(segment[5]), float(segment[6]))
    return " ".join(output)


def arc_circle(start: tuple[float, float], values: list[str]):
    arc_data = " ".join((f"M{start[0]} {start[1]}", "A", *values))
    recording = RecordingPen()
    parse_path(arc_data, recording)
    curves = [points for operation, points in recording.value if operation == "curveTo"]
    if not curves:
        return None
    p0, p1, p2, p3 = start, curves[0][0], curves[-1][1], curves[-1][2]
    tangent0 = (p1[0] - p0[0], p1[1] - p0[1])
    tangent1 = (p3[0] - p2[0], p3[1] - p2[1])
    normal0 = (tangent0[1], -tangent0[0])
    normal1 = (tangent1[1], -tangent1[0])
    determinant = normal0[0] * normal1[1] - normal0[1] * normal1[0]
    if abs(determinant) < 1e-9:
        return None
    delta = (p3[0] - p0[0], p3[1] - p0[1])
    factor = (delta[0] * normal1[1] - delta[1] * normal1[0]) / determinant
    center = (p0[0] + factor * normal0[0], p0[1] + factor * normal0[1])
    radius = (math.dist(center, p0) + math.dist(center, p3)) / 2
    a0 = math.atan2(p0[1] - center[1], p0[0] - center[0])
    a1 = math.atan2(p3[1] - center[1], p3[0] - center[0])
    sweep = int(values[4])
    angle = (a1 - a0) % (2 * math.pi) if sweep else (a0 - a1) % (2 * math.pi)
    return center, radius, angle


def merge_adjacent_arcs(data: str) -> str:
    tokens = PATH_TOKEN.findall(data)
    segments = []
    index = 0
    counts = {"M": 2, "L": 2, "A": 7, "Z": 0}
    while index < len(tokens):
        command = tokens[index]
        index += 1
        count = counts.get(command.upper())
        if count is None:
            raise ValueError(f"unsupported command while merging arcs: {command}")
        if count == 0:
            segments.append((command, []))
            continue
        values = []
        while index < len(tokens) and not tokens[index].isalpha():
            values.append(tokens[index])
            index += 1
        if len(values) % count:
            raise ValueError(f"invalid path data while merging arcs: {data}")
        segments.extend((command, values[i:i + count]) for i in range(0, len(values), count))

    output = []
    current = None
    index = 0
    while index < len(segments):
        command, values = segments[index]
        kind = command.upper()
        if kind == "M":
            current = (float(values[0]), float(values[1]))
            output.extend((command, *values))
            index += 1
        elif kind == "L":
            current = (float(values[0]), float(values[1]))
            output.extend((command, *values))
            index += 1
        elif kind == "A":
            run = [(current, values, arc_circle(current, values))]
            end = (float(values[5]), float(values[6]))
            cursor = index + 1
            while cursor < len(segments) and segments[cursor][0].upper() == "A":
                next_values = segments[cursor][1]
                next_arc = arc_circle(end, next_values)
                previous_arc = run[-1][2]
                if (
                    previous_arc is None or next_arc is None
                    or int(next_values[4]) != int(values[4])
                    or math.dist(previous_arc[0], next_arc[0]) > 0.03
                    or abs(previous_arc[1] - next_arc[1]) > 0.03
                ):
                    break
                run.append((end, next_values, next_arc))
                end = (float(next_values[5]), float(next_values[6]))
                cursor += 1
            if len(run) > 1:
                # SVG cannot draw a full circle with one A; leave full-circle runs intact.
                total_angle = sum(item[2][2] for item in run)
                if total_angle >= 2 * math.pi - 0.03:
                    for item in run:
                        output.extend((command, *item[1]))
                    current = end
                    index = cursor
                    continue
                chunks = [run]
                for chunk in chunks:
                    first_values, last_values = chunk[0][1], chunk[-1][1]
                    chunk_angle = sum(item[2][2] for item in chunk)
                    large_arc = int(chunk_angle >= math.pi - 1e-6)
                    merged = [first_values[0], first_values[1], first_values[2], str(large_arc), first_values[4], last_values[5], last_values[6]]
                    output.extend((command, *merged))
                current = end
                index = cursor
            else:
                output.extend((command, *values))
                current = end
                index += 1
        else:
            output.append(command)
            index += 1
    return " ".join(output)


def path_x_bounds(data: str) -> tuple[float, float]:
    recording = RecordingPen()
    parse_path(data, recording)
    xs = []
    current = None
    for operation, points in recording.value:
        if operation in ("moveTo", "lineTo"):
            current = points[0]
            xs.append(current[0])
        elif operation == "curveTo":
            p0, p1, p2, p3 = current, points[0], points[1], points[2]
            for step in range(1, 33):
                t = step / 32
                u = 1 - t
                x = u**3 * p0[0] + 3 * u**2 * t * p1[0] + 3 * u * t**2 * p2[0] + t**3 * p3[0]
                xs.append(x)
            current = p3
    if not xs:
        return 0.0, 0.0
    return min(xs), max(xs)


def translate_path_x(data: str, offset: float, coordinate_step: float = 1.0) -> str:
    tokens = PATH_TOKEN.findall(data)
    output = []
    index = 0
    counts = {"M": 2, "L": 2, "A": 7, "Z": 0}
    current = None
    point_output_indices = None
    previous_command = None
    while index < len(tokens):
        command = tokens[index]
        index += 1
        count = counts.get(command.upper())
        if count is None:
            raise ValueError(f"unsupported command while snapping glyph coordinates: {command}")
        output.append(command)
        if count == 0:
            continue
        values = []
        while index < len(tokens) and not tokens[index].isalpha():
            values.append(tokens[index])
            index += 1
        if len(values) % count:
            raise ValueError(f"invalid SVG path data while centering glyph: {data}")
        for start in range(0, len(values), count):
            segment = values[start:start + count]
            if command.upper() in ("M", "L"):
                raw = (float(segment[0]) + offset, float(segment[1]))
                def snap(value: float, step: float = coordinate_step) -> float:
                    return math.floor(value / step + 0.5) * step

                if command.upper() == "M":
                    point = (snap(raw[0]), snap(raw[1]))
                    output.extend((str(point[0]), str(point[1])))
                    current = raw
                    point_output_indices = (len(output) - 2, len(output) - 1)
                else:
                    point = (snap(raw[0]), snap(raw[1]))
                    if current is not None and previous_command == "M" and 0 < math.dist(current, raw) < 0.5:
                        start_point = (snap(current[0], 0.25), snap(current[1], 0.25))
                        end_point = (snap(raw[0], 0.25), snap(raw[1], 0.25))
                        if start_point == end_point:
                            middle = (snap((current[0] + raw[0]) / 2, 0.25), snap((current[1] + raw[1]) / 2, 0.25))
                            if abs(raw[0] - current[0]) >= abs(raw[1] - current[1]):
                                sign = 1 if raw[0] > current[0] else -1
                                start_point = (middle[0] + sign * 0.125, middle[1])
                                end_point = (middle[0] - sign * 0.125, middle[1])
                            else:
                                sign = 1 if raw[1] > current[1] else -1
                                start_point = (middle[0], middle[1] + sign * 0.125)
                                end_point = (middle[0], middle[1] - sign * 0.125)
                        if point_output_indices:
                            output[point_output_indices[0]] = simple_number(start_point[0])
                            output[point_output_indices[1]] = simple_number(start_point[1])
                        point = end_point
                    output.extend((str(point[0]), str(point[1])))
                    current = raw
                    point_output_indices = (len(output) - 2, len(output) - 1)
                previous_command = command.upper()
            else:
                segment = [simple_number(float(v)) for v in segment]
                segment[5] = str(math.floor((float(values[start + 5]) + offset) / coordinate_step + 0.5) * coordinate_step)
                segment[6] = str(math.floor(float(values[start + 6]) / coordinate_step + 0.5) * coordinate_step)
                output.extend(segment)
                current = (float(values[start + 5]) + offset, float(values[start + 6]))
                point_output_indices = (len(output) - 2, len(output) - 1)
                previous_command = command.upper()
    return " ".join(output)


def append_normalized_paths(
    element: ET.Element,
    parent_transform: tuple[float, float, float, float, float, float],
    target_paths: list[ET.Element],
    origin: tuple[float, float],
    y_offset: float,
) -> None:
    local_transform = compose(parent_transform, parse_transform(element.get("transform")))
    if element.tag == f"{{{SVG_NS}}}path" and element.get("d") and element.get("stroke") != "none":
        recording = RecordingPen()
        normalize = (
            1 / GRID_STEP, 0, 0, 1 / GRID_STEP,
            -origin[0] / GRID_STEP, GRID_Y_OFFSET + y_offset - origin[1] / GRID_STEP,
        )
        parse_path(element.get("d", ""), TransformPen(recording, compose(normalize, local_transform)))
        d = recording_path_data(recording)
        target_paths.append(ET.Element(f"{{{SVG_NS}}}path", {
            "d": d,
            "fill": "none",
            "stroke": element.get("stroke", "#000000"),
            "stroke-width": f"{float(element.get('stroke-width', '1')) / GRID_STEP:g}",
            "stroke-linecap": element.get("stroke-linecap", "round"),
            "stroke-linejoin": element.get("stroke-linejoin", "round"),
        }))
    for child in element:
        append_normalized_paths(child, local_transform, target_paths, origin, y_offset)


def normalized_glyph_svg(
    source_root: ET.Element,
    cell_ids: set[str],
    model_x: float,
    model_y: float,
    y_offset: float,
    family: str,
    character: str,
) -> ET.Element:
    layer, _ = find_cell_groups(source_root)
    origin = (model_x - DRAWING_COORD_OFFSET, model_y - DRAWING_COORD_OFFSET)
    paths: list[ET.Element] = []
    for child in layer:
        if child.get("data-cell-id") in cell_ids:
            append_normalized_paths(child, IDENTITY, paths, origin, y_offset)
    width = GRID_VIEWBOX_WIDTH * GRID_STEP
    height = GRID_VIEWBOX_HEIGHT * GRID_STEP
    glyph_root = ET.Element(f"{{{SVG_NS}}}svg", {
        "width": f"{width:g}px",
        "height": f"{height:g}px",
        "viewBox": f"{GRID_VIEWBOX_X:g} {GRID_VIEWBOX_Y:g} {GRID_VIEWBOX_WIDTH:g} {GRID_VIEWBOX_HEIGHT:g}",
    })
    override = GLYPH_PATH_OVERRIDES.get((family, character))
    combined_path = override or merge_connected_subpaths(" ".join(path.get("d", "") for path in paths))
    path_min_x, path_max_x = path_x_bounds(combined_path)
    x_offset = GRID_CENTER_X - (path_min_x + path_max_x) / 2
    x_offset = math.floor(x_offset * 4 + 0.5) / 4
    if override is None:
        coordinate_step = 0.25 if family == "symbols" else 1.0
        for path in paths:
            path.set("d", translate_path_x(path.get("d", ""), 0, coordinate_step))
        combined_path = merge_connected_subpaths(" ".join(path.get("d", "") for path in paths))
    combined_path = merge_adjacent_arcs(combined_path)
    combined_d = readable_path_data(combined_path)
    first = paths[0] if paths else ET.Element("path")
    path_attrs = {
        "d": f"\n      {combined_d}\n    ",
        "fill": first.get("fill", "none"),
        "stroke": first.get("stroke", "#000000"),
        "stroke-width": first.get("stroke-width", "0.25"),
        "stroke-linecap": first.get("stroke-linecap", "round"),
        "stroke-linejoin": first.get("stroke-linejoin", "round"),
    }
    if abs(x_offset) > 1e-9:
        path_attrs["transform"] = f"translate({x_offset:.3f} 0)"
    ET.SubElement(glyph_root, f"{{{SVG_NS}}}path", path_attrs)
    return glyph_root


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Split grouped glyphs from the draw.io SVG into individual SVG files."
    )
    parser.add_argument("--source", type=Path, help="draw.io SVG path; defaults to the only SVG in src/")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "src" / "charsvg")
    parser.add_argument("--dry-run", action="store_true", help="Check the grouped glyph layout without writing files.")
    parser.add_argument("--overwrite", action="store_true", help="Replace glyph SVGs that already exist.")
    args = parser.parse_args()

    source_path = args.source
    if source_path is None:
        source_candidates = sorted((PROJECT_ROOT / "src").glob("*.svg"))
        if len(source_candidates) != 1:
            parser.error(f"expected exactly one SVG in {PROJECT_ROOT / 'src'}, found {len(source_candidates)}")
        source_path = source_candidates[0]

    try:
        source_root = ET.parse(source_path).getroot()
        content = source_root.get("content")
        if not content:
            parser.error("source SVG does not contain embedded draw.io content")
        glyphs = read_glyphs(content)
        assignments = assign_rows(glyphs, parser)
        symbol_objects = read_symbol_objects(content)
        layer, svg_cells = find_cell_groups(source_root)
    except (OSError, ET.ParseError, ValueError) as error:
        parser.error(f"cannot read grouped SVG source: {error}")

    layer_ids = {child.get("data-cell-id") for child in layer if child.get("data-cell-id")}
    missing_svg = [glyph.cell_id for glyph in glyphs if glyph.cell_id not in layer_ids or glyph.cell_id not in svg_cells]
    if missing_svg:
        parser.error(f"glyph cells are missing from the SVG drawing layer: {missing_svg[:3]}")

    symbol_assignments = []
    for row_symbols, min_y, max_y in SYMBOL_ROWS:
        row_objects = sorted(
            (obj for obj in symbol_objects if min_y <= obj.y < max_y),
            key=lambda obj: obj.x,
        )
        if min_y == SYMBOL_ROWS[0][1]:
            touching_pairs = [
                (edge, group)
                for edge in row_objects
                if edge.is_edge
                for group in row_objects
                if not group.is_edge
                and abs(group.x - edge.x) <= 0.1
                and abs(group.width - edge.width) <= 0.1
                and abs(group.y + group.height - edge.y) <= 1
            ]
            if len(touching_pairs) != 1:
                parser.error(f"expected one standalone stroke attached to a symbol group, found {len(touching_pairs)}")
            attached_edge, attached_group = touching_pairs[0]
            attached_group_id = attached_group.cell_id
            attached_edge_id = attached_edge.cell_id
            row_objects.remove(attached_edge)
            row_objects[row_objects.index(attached_group)] = SymbolObject(
                attached_group.cell_id,
                attached_group.x,
                attached_group.y,
                attached_group.width,
                max(attached_group.height, attached_edge.y + attached_edge.height - attached_group.y),
                False,
            )

        if len(row_objects) != len(row_symbols):
            parser.error(
                f"symbols at y={min_y}: expected {len(row_symbols)} glyphs, found {len(row_objects)}"
            )
        for character, obj in zip(row_symbols, row_objects):
            ids = {obj.cell_id}
            if min_y == SYMBOL_ROWS[0][1] and obj.cell_id == attached_group_id:
                ids.add(attached_edge_id)
            symbol_assignments.append((character, obj, ids, min_y))

    symbol_missing_svg = [
        cell_id
        for _, _, selected_ids, _ in symbol_assignments
        for cell_id in selected_ids
        if cell_id not in svg_cells
    ]
    if symbol_missing_svg:
        parser.error(f"symbol cells are missing from the SVG drawing layer: {symbol_missing_svg[:3]}")

    all_targets = [
        args.output_dir / row.folder / glyph_filename(character)
        for row, character, _ in assignments
    ] + [
        args.output_dir / "symbols" / glyph_filename(character)
        for character, _, _, _ in symbol_assignments
    ]

    if args.dry_run:
        print(f"Validated {len(assignments)} alphanumeric and {len(symbol_assignments)} symbol glyphs from {source_path.name}.")
        for row in ROWS:
            count = sum(assignment[0] == row for assignment in assignments)
            print(f"  {row.folder}: {count} glyphs")
        for symbols, min_y, _ in SYMBOL_ROWS:
            print(f"  symbols y={min_y}: {len(symbols)} glyphs")
        return 0

    existing = [path for path in all_targets if path.exists()]
    if existing and not args.overwrite:
        parser.error(f"output already exists; choose another --output-dir or pass --overwrite: {existing[0]}")

    output_tasks = [
        (
            glyph.cell_id,
            row.folder,
            character,
            {glyph.cell_id},
            glyph.x,
            glyph.y,
            baseline_alignment_offset(
                glyph.y,
                {"digits": 162, "uppercase": 482, "lowercase_m": 802, "lowercase_p": 1122}[row.folder],
            ),
            target,
        )
        for (row, character, glyph), target in zip(
            assignments,
            [args.output_dir / row.folder / glyph_filename(character) for row, character, _ in assignments],
        )
    ]
    output_tasks.extend(
        (
            obj.cell_id,
            "symbols",
            character,
            ids,
            obj.x,
            obj.y,
            baseline_alignment_offset(
                obj.y,
                1442 if min_y == SYMBOL_ROWS[0][1] else 1762,
            ),
            args.output_dir / "symbols" / glyph_filename(character),
        )
        for character, obj, ids, min_y in symbol_assignments
    )

    for cell_id, family, character, selected_ids, x, y, y_offset, target in output_tasks:
        glyph_root = normalized_glyph_svg(source_root, selected_ids, x, y, y_offset, family, character)
        target.parent.mkdir(parents=True, exist_ok=True)
        path = glyph_root[0]
        root_attrs = " ".join(f'{key}="{escape(value, {chr(34): "&quot;"})}"' for key, value in glyph_root.attrib.items())
        path_attrs = " ".join(
            f'{key}="{escape(value, {chr(34): "&quot;"})}"'
            for key, value in path.attrib.items() if key != "d"
        )
        svg_text = (
            f'<svg xmlns="{SVG_NS}" {root_attrs}>\n'
            f'  <path d="{path.get("d", "")}" {path_attrs} />\n'
            "</svg>\n"
        )
        target.write_text(svg_text, encoding="utf-8", newline="\n")

    print(f"Wrote {len(output_tasks)} glyph SVGs to {args.output_dir}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
