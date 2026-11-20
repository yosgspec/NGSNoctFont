from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path


TOKEN_RE = re.compile(r"[A-Za-z]|[-+]?(?:\d*\.\d+|\d+\.?\d*)(?:[eE][-+]?\d+)?")
SVG_NS = "http://www.w3.org/2000/svg"
PRESERVE_SOURCE_SHAPES = {
    "lowercase_p/w_0077.svg",
    "lowercase_p/m_006D.svg",
    "lowercase_p/x_0078.svg",
    "lowercase_p/z_007A.svg",
    "symbols/;_003B.svg",
    "symbols/!_0021.svg",
    "symbols/€_20AC.svg",
}


@dataclass(frozen=True)
class Edge:
    start: tuple[float, float]
    end: tuple[float, float]
    command: str
    values: tuple[str, ...]


@dataclass(frozen=True)
class Step:
    edge_id: int
    reverse: bool


def point_key(point: tuple[float, float]) -> tuple[int, int]:
    return round(point[0] * 1000000), round(point[1] * 1000000)


def parse_edges(data: str) -> list[Edge]:
    tokens = TOKEN_RE.findall(data)
    edges: list[Edge] = []
    index = 0
    command = None
    current = None
    subpath_start = None
    counts = {"M": 2, "L": 2, "A": 7, "Z": 0}
    while index < len(tokens):
        if tokens[index].isalpha():
            command = tokens[index]
            index += 1
        if command is None:
            raise ValueError(f"missing SVG command in {data}")
        kind = command.upper()
        if kind not in counts:
            raise ValueError(f"unsupported path command {command}")
        if kind == "Z":
            if current is not None and subpath_start is not None and point_key(current) != point_key(subpath_start):
                edges.append(Edge(current, subpath_start, "L", (str(subpath_start[0]), str(subpath_start[1]))))
            current = subpath_start
            command = None
            continue
        count = counts[kind]
        values = []
        while index < len(tokens) and not tokens[index].isalpha():
            values.append(tokens[index])
            index += 1
        if not values or len(values) % count:
            raise ValueError(f"invalid path data {data}")
        for offset in range(0, len(values), count):
            segment = tuple(values[offset:offset + count])
            if kind == "M":
                point = (float(segment[0]), float(segment[1]))
                current = subpath_start = point
                command = "L" if command.isupper() else "l"
                continue
            if current is None:
                raise ValueError(f"path segment before moveTo in {data}")
            if kind == "L":
                end = (float(segment[0]), float(segment[1]))
                edge_command = "L"
            else:
                end = (float(segment[5]), float(segment[6]))
                edge_command = "A"
            edges.append(Edge(current, end, edge_command, segment))
            current = end
    return edges


def reversed_edge(edge: Edge) -> tuple[str, tuple[str, ...]]:
    if edge.command == "L":
        return "L", (format_number(edge.start[0]), format_number(edge.start[1]))
    values = list(edge.values)
    values[4] = str(1 - int(values[4]))
    values[5] = format_number(edge.start[0])
    values[6] = format_number(edge.start[1])
    return "A", tuple(values)


def format_number(value: float | str) -> str:
    number = Decimal(str(value)).normalize()
    return format(number, "f") if number else "0"


def components(edges: list[Edge]) -> list[list[int]]:
    adjacency: dict[tuple[int, int], list[int]] = {}
    for edge_id, edge in enumerate(edges):
        a, b = point_key(edge.start), point_key(edge.end)
        adjacency.setdefault(a, []).append(edge_id)
        adjacency.setdefault(b, []).append(edge_id)
    remaining = set(range(len(edges)))
    result = []
    while remaining:
        first = min(remaining)
        stack = [point_key(edges[first].start)]
        found: set[int] = set()
        while stack:
            vertex = stack.pop()
            for edge_id in adjacency[vertex]:
                if edge_id in found:
                    continue
                found.add(edge_id)
                edge = edges[edge_id]
                stack.append(point_key(edge.end if point_key(edge.start) == vertex else edge.start))
        remaining -= found
        result.append(sorted(found))
    return result


def euler_trails(edges: list[Edge], edge_ids: list[int]) -> list[list[Step]]:
    adjacency: dict[tuple[int, int] | str, list[tuple[int, tuple[int, int] | str, bool]]] = {}
    start_by_id: dict[int, tuple[int, int]] = {}
    end_by_id: dict[int, tuple[int, int]] = {}
    local_edges: dict[int, Edge | None] = {}
    for edge_id in edge_ids:
        edge = edges[edge_id]
        a, b = point_key(edge.start), point_key(edge.end)
        start_by_id[edge_id], end_by_id[edge_id], local_edges[edge_id] = a, b, edge
        adjacency.setdefault(a, []).append((edge_id, b, False))
        adjacency.setdefault(b, []).append((edge_id, a, True))

    degree = {vertex: len(incidents) for vertex, incidents in adjacency.items()}
    odd_vertices = [vertex for vertex, value in degree.items() if value % 2]
    dummy_ids = set()
    if odd_vertices:
        dummy = "__dummy__"
        for offset, vertex in enumerate(odd_vertices):
            edge_id = len(edges) + offset
            dummy_ids.add(edge_id)
            start_by_id[edge_id], end_by_id[edge_id], local_edges[edge_id] = vertex, dummy, None
            adjacency.setdefault(vertex, []).append((edge_id, dummy, False))
            adjacency.setdefault(dummy, []).append((edge_id, vertex, True))
        start = dummy
    else:
        start = next(iter(adjacency))

    used: set[int] = set()
    vertices = [start]
    route_stack: list[Step] = []
    reverse_route: list[Step] = []
    while vertices:
        vertex = vertices[-1]
        while adjacency[vertex] and adjacency[vertex][-1][0] in used:
            adjacency[vertex].pop()
        if adjacency[vertex]:
            edge_id, other, reverse = adjacency[vertex].pop()
            if edge_id in used:
                continue
            used.add(edge_id)
            vertices.append(other)
            route_stack.append(Step(edge_id, reverse))
        else:
            vertices.pop()
            if route_stack:
                reverse_route.append(route_stack.pop())
    route = list(reversed(reverse_route))

    if not dummy_ids:
        return [route] if route else []
    first_dummy = next(i for i, step in enumerate(route) if step.edge_id in dummy_ids)
    route = route[first_dummy + 1:] + route[:first_dummy + 1]
    trails: list[list[Step]] = []
    current: list[Step] = []
    for step in route:
        if step.edge_id in dummy_ids:
            if current:
                trails.append(current)
                current = []
        else:
            current.append(step)
    if current:
        trails.append(current)
    return trails


def optimize_path(data: str) -> str:
    edges = parse_edges(data)
    trails = []
    for component in components(edges):
        trails.extend(euler_trails(edges, component))
    output = []
    for trail in trails:
        first_edge = edges[trail[0].edge_id]
        first_point = first_edge.end if trail[0].reverse else first_edge.start
        output.append(f"M{format_number(first_point[0])} {format_number(first_point[1])}")
        for step in trail:
            edge = edges[step.edge_id]
            if step.reverse:
                command, values = reversed_edge(edge)
            else:
                command, values = edge.command, edge.values
            output.append(f"{command}{' '.join(format_number(value) for value in values)}")
    return "\n      ".join(output)


def main() -> int:
    parser = argparse.ArgumentParser(description="Join endpoint-connected SVG glyph strokes to reduce moveTo commands.")
    parser.add_argument("--glyph-dir", type=Path, default=Path(__file__).resolve().parent.parent / "src" / "charsvg")
    args = parser.parse_args()
    glyph_files = sorted(args.glyph_dir.rglob("*.svg"))
    before_moves = after_moves = changed = 0
    for path in glyph_files:
        relative = path.relative_to(args.glyph_dir).as_posix()
        if relative in PRESERVE_SOURCE_SHAPES:
            continue
        text = path.read_text(encoding="utf-8")
        match = re.search(r'(<path\b[^>]*\bd=")([\s\S]*?)(")', text)
        if not match:
            continue
        old = match.group(2)
        new = "\n      " + optimize_path(old) + "\n    "
        before_moves += len(re.findall(r"\bM", old))
        after_moves += len(re.findall(r"\bM", new))
        if old != new:
            changed += 1
            text = text[:match.start(2)] + new + text[match.end(2):]
            path.write_text(text, encoding="utf-8")
    print(f"Glyphs: {len(glyph_files)}; changed: {changed}; M commands: {before_moves} -> {after_moves}; removed: {before_moves - after_moves}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
