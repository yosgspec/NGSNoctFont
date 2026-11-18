from __future__ import annotations

import argparse
import copy
import string
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path


SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"
MODEL_TO_SVG_OFFSET = 119
CELL_WIDTH = 100
CELL_HEIGHT = 200
CROP_MARGIN = 5

ET.register_namespace("", SVG_NS)
ET.register_namespace("xlink", XLINK_NS)


@dataclass(frozen=True)
class Row:
    folder: str
    characters: str
    x: int
    y: int


@dataclass(frozen=True)
class Cell:
    cell_id: str
    bounds: tuple[float, float, float, float]


ROWS = (
    Row("digits", string.digits, 160, 120),
    Row("uppercase", string.ascii_uppercase, 160, 320),
    Row("lowercase_1", string.ascii_lowercase, 160, 600),
    Row("lowercase_2", string.ascii_lowercase, 120, 880),
)


def parse_cells(content: str) -> list[Cell]:
    mxfile = ET.fromstring(content)
    cells = []
    for cell in mxfile.findall(".//mxCell"):
        cell_id = cell.get("id")
        geometry = cell.find("mxGeometry")
        if not cell_id or geometry is None:
            continue

        points = []
        x = geometry.get("x")
        y = geometry.get("y")
        width = geometry.get("width")
        height = geometry.get("height")
        if x is not None and y is not None and width is not None and height is not None:
            left = float(x)
            top = float(y)
            points.extend(((left, top), (left + float(width), top + float(height))))

        for point in geometry.findall(".//mxPoint"):
            px = point.get("x")
            py = point.get("y")
            if px is not None and py is not None:
                points.append((float(px), float(py)))

        if not points:
            continue
        cells.append(
            Cell(
                cell_id,
                (
                    min(point[0] for point in points),
                    min(point[1] for point in points),
                    max(point[0] for point in points),
                    max(point[1] for point in points),
                ),
            )
        )
    return cells


def intersects(bounds: tuple[float, float, float, float], box: tuple[float, float, float, float]) -> bool:
    left, top, right, bottom = bounds
    box_left, box_top, box_right, box_bottom = box

    def overlaps_axis(start: float, end: float, box_start: float, box_end: float) -> bool:
        if start == end:
            return box_start <= start < box_end
        return start < box_end and end > box_start

    return overlaps_axis(left, right, box_left, box_right) and overlaps_axis(top, bottom, box_top, box_bottom)


def prune_unselected_cells(element: ET.Element, selected: set[str]) -> None:
    for child in list(element):
        cell_id = child.get("data-cell-id")
        if cell_id and cell_id not in {"0", "1"} and cell_id not in selected:
            element.remove(child)
        else:
            prune_unselected_cells(child, selected)


def main() -> int:
    parser = argparse.ArgumentParser(description="Split the draw.io SVG character sheet into individual SVG glyphs.")
    parser.add_argument("--source", type=Path, default=Path(__file__).with_name("ngscsfont.drawio.svg.xml"))
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).with_name("split_glyphs"))
    parser.add_argument("--dry-run", action="store_true", help="Check the crop layout without writing files.")
    parser.add_argument("--overwrite", action="store_true", help="Replace glyph SVGs that already exist.")
    args = parser.parse_args()

    try:
        source_root = ET.parse(args.source).getroot()
    except (OSError, ET.ParseError) as error:
        parser.error(f"cannot read SVG source: {error}")

    content = source_root.get("content")
    if not content:
        parser.error("source SVG does not contain embedded draw.io content")

    cells = parse_cells(content)
    svg_cells = {
        element.get("data-cell-id"): element
        for element in source_root.iter(f"{{{SVG_NS}}}g")
        if element.get("data-cell-id")
    }
    tasks = []
    for row in ROWS:
        for index, character in enumerate(row.characters):
            x = row.x + index * CELL_WIDTH
            box = (x, row.y, x + CELL_WIDTH, row.y + CELL_HEIGHT)
            selected = {
                cell.cell_id
                for cell in cells
                if cell.cell_id in svg_cells and intersects(cell.bounds, box)
            }
            if not selected:
                parser.error(f"no drawing cells found for {row.folder}/{character}")
            tasks.append((row, character, x, selected))

    if args.dry_run:
        print(f"Validated {len(tasks)} glyph crops from {args.source.name}.")
        for row in ROWS:
            row_tasks = [task for task in tasks if task[0] == row]
            print(f"  {row.folder}: {len(row_tasks)} glyphs")
        return 0

    targets = [args.output_dir / row.folder / f"{character}.svg" for row, character, _, _ in tasks]
    existing = [path for path in targets if path.exists()]
    if existing and not args.overwrite:
        parser.error(f"output already exists; choose another --output-dir: {existing[0]}")

    for (row, character, x, selected), target in zip(tasks, targets):
        glyph_root = copy.deepcopy(source_root)
        glyph_root.attrib.pop("content", None)
        glyph_root.attrib.pop("id", None)
        output_width = CELL_WIDTH + CROP_MARGIN * 2
        output_height = CELL_HEIGHT + CROP_MARGIN * 2
        glyph_root.set("width", f"{output_width}px")
        glyph_root.set("height", f"{output_height}px")
        glyph_root.set(
            "viewBox",
            f"{x - MODEL_TO_SVG_OFFSET - CROP_MARGIN} "
            f"{row.y - MODEL_TO_SVG_OFFSET - CROP_MARGIN} {output_width} {output_height}",
        )
        prune_unselected_cells(glyph_root, selected)
        target.parent.mkdir(parents=True, exist_ok=True)
        ET.ElementTree(glyph_root).write(target, encoding="utf-8", xml_declaration=True)

    print(f"Wrote {len(targets)} glyph SVGs to {args.output_dir}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())