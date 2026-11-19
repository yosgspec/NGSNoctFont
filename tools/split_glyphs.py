from __future__ import annotations

import argparse
import copy
import string
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SVG_NS = "http://www.w3.org/2000/svg"
MODEL_TO_SVG_X_OFFSET = 118
MODEL_TO_SVG_Y_OFFSET = 158
MIN_GLYPH_SIZE = 40
CROP_MARGIN = 8

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
    Row("lowercase_1", string.ascii_lowercase, 700, 1050),
    Row("lowercase_2", string.ascii_lowercase, 1050, 1400),
)
ASCII_SYMBOLS = string.punctuation
EXTRA_SYMBOLS = "£¥©®–—‘’“”…€™"
SYMBOL_ROWS = (
    (ASCII_SYMBOLS[:26], 1350, 1650),
    (ASCII_SYMBOLS[26:] + EXTRA_SYMBOLS, 1650, 2000),
)


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


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Split grouped glyphs from the draw.io SVG into individual SVG files."
    )
    parser.add_argument("--source", type=Path, help="draw.io SVG path; defaults to the only SVG in src/")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "charsvg")
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
        args.output_dir / row.folder / f"{character}.svg"
        for row, character, _ in assignments
    ] + [
        args.output_dir / "symbols" / f"U+{ord(character):04X}.svg"
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
        (glyph.cell_id, {glyph.cell_id}, glyph.x, glyph.y, glyph.width, glyph.height, row.min_y - 100, target)
        for (row, character, glyph), target in zip(
            assignments,
            [args.output_dir / row.folder / f"{character}.svg" for row, character, _ in assignments],
        )
    ]
    output_tasks.extend(
        (
            obj.cell_id,
            ids,
            obj.x,
            obj.y,
            obj.width,
            obj.height,
            1600 if min_y == SYMBOL_ROWS[0][1] else 1920,
            args.output_dir / "symbols" / f"U+{ord(character):04X}.svg",
        )
        for character, obj, ids, min_y in symbol_assignments
    )

    for cell_id, selected_ids, x, y, width, height, baseline, target in output_tasks:
        glyph_root = copy.deepcopy(source_root)
        glyph_root.attrib.pop("content", None)
        output_layer, _ = find_cell_groups(glyph_root)
        for child in list(output_layer):
            child_id = child.get("data-cell-id")
            if child_id and child_id not in selected_ids:
                output_layer.remove(child)

        view_x = x - MODEL_TO_SVG_X_OFFSET
        view_y = y - MODEL_TO_SVG_Y_OFFSET
        view_width = max(width, MIN_GLYPH_SIZE)
        view_height = max(height, MIN_GLYPH_SIZE)
        view_x -= CROP_MARGIN
        view_y -= CROP_MARGIN
        view_width += CROP_MARGIN * 2
        view_height += CROP_MARGIN * 2
        glyph_root.set("viewBox", f"{view_x:g} {view_y:g} {view_width:g} {view_height:g}")
        glyph_root.set("width", f"{view_width:g}px")
        glyph_root.set("height", f"{view_height:g}px")

        target.parent.mkdir(parents=True, exist_ok=True)
        ET.ElementTree(glyph_root).write(target, encoding="utf-8", xml_declaration=True)

    print(f"Wrote {len(output_tasks)} glyph SVGs to {args.output_dir}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())