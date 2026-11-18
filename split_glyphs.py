from __future__ import annotations

import argparse
import copy
import string
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path


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
    parser.add_argument("--source", type=Path, default=Path(__file__).with_name("ngscsfont.drawio.svg"))
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).with_name("split_glyphs"))
    parser.add_argument("--dry-run", action="store_true", help="Check the grouped glyph layout without writing files.")
    parser.add_argument("--overwrite", action="store_true", help="Replace glyph SVGs that already exist.")
    args = parser.parse_args()

    try:
        source_root = ET.parse(args.source).getroot()
        content = source_root.get("content")
        if not content:
            parser.error("source SVG does not contain embedded draw.io content")
        glyphs = read_glyphs(content)
        assignments = assign_rows(glyphs, parser)
        layer, svg_cells = find_cell_groups(source_root)
    except (OSError, ET.ParseError, ValueError) as error:
        parser.error(f"cannot read grouped SVG source: {error}")

    layer_ids = {child.get("data-cell-id") for child in layer if child.get("data-cell-id")}
    missing_svg = [glyph.cell_id for glyph in glyphs if glyph.cell_id not in layer_ids or glyph.cell_id not in svg_cells]
    if missing_svg:
        parser.error(f"glyph cells are missing from the SVG drawing layer: {missing_svg[:3]}")

    if args.dry_run:
        print(f"Validated {len(assignments)} glyphs from {args.source.name}.")
        for row in ROWS:
            count = sum(assignment[0] == row for assignment in assignments)
            print(f"  {row.folder}: {count} glyphs")
        return 0

    targets = [args.output_dir / row.folder / f"{character}.svg" for row, character, _ in assignments]
    existing = [path for path in targets if path.exists()]
    if existing and not args.overwrite:
        parser.error(f"output already exists; choose another --output-dir or pass --overwrite: {existing[0]}")

    for (row, character, glyph), target in zip(assignments, targets):
        glyph_root = copy.deepcopy(source_root)
        glyph_root.attrib.pop("content", None)
        output_layer, _ = find_cell_groups(glyph_root)
        for child in list(output_layer):
            cell_id = child.get("data-cell-id")
            if cell_id and cell_id != glyph.cell_id:
                output_layer.remove(child)

        view_x = glyph.x - MODEL_TO_SVG_X_OFFSET
        view_y = glyph.y - MODEL_TO_SVG_Y_OFFSET
        view_width = max(glyph.width, MIN_GLYPH_SIZE)
        view_height = max(glyph.height, MIN_GLYPH_SIZE)
        view_x -= CROP_MARGIN
        view_y -= CROP_MARGIN
        view_width += CROP_MARGIN * 2
        view_height += CROP_MARGIN * 2
        glyph_root.set("viewBox", f"{view_x:g} {view_y:g} {view_width:g} {view_height:g}")
        glyph_root.set("width", f"{view_width:g}px")
        glyph_root.set("height", f"{view_height:g}px")

        target.parent.mkdir(parents=True, exist_ok=True)
        ET.ElementTree(glyph_root).write(target, encoding="utf-8", xml_declaration=True)

    print(f"Wrote {len(targets)} glyph SVGs to {args.output_dir}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())