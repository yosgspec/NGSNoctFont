from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import sys
import zipfile
from pathlib import Path

from fontTools.ttLib import TTCollection, TTFont


PROJECT_ROOT = Path(__file__).resolve().parent.parent
EXTRA_CODEPOINTS = {
    0x00A3,
    0x00A5,
    0x00A9,
    0x00AE,
    0x2013,
    0x2014,
    0x2018,
    0x2019,
    0x201C,
    0x201D,
    0x2026,
    0x20AC,
    0x2122,
}
EXPECTED_CODEPOINTS = set(range(0x20, 0x7F)) | EXTRA_CODEPOINTS
FONTS = {
    "NGSNoctM": ("NGS Noct M", True, False, False),
    "NGSNoctM-Bold": ("NGS Noct M", True, True, False),
    "NGSNoctP": ("NGS Noct P", False, False, False),
    "NGSNoctP-Bold": ("NGS Noct P", False, True, False),
    "NGSNoctMF": ("NGS Noct MF", True, False, True),
    "NGSNoctMF-Bold": ("NGS Noct MF", True, True, True),
    "NGSNoctPF": ("NGS Noct PF", False, False, True),
    "NGSNoctPF-Bold": ("NGS Noct PF", False, True, True),
}
DOCUMENTS = (
    PROJECT_ROOT / "docs" / "FONT_CHARACTERS.txt",
    PROJECT_ROOT / "docs" / "FONT_BUILD.md",
)
TAG_RE = re.compile(r"v\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?\Z")


def validate_font(
    path: Path,
    family_name: str,
    is_monospaced: bool,
    is_bold: bool,
    is_compact: bool,
    is_woff2: bool,
) -> None:
    with TTFont(path) as font:
        cmap = font.getBestCmap()
        missing = EXPECTED_CODEPOINTS - set(cmap)
        if missing:
            missing_text = ", ".join(f"U+{codepoint:04X}" for codepoint in sorted(missing))
            raise ValueError(f"{path.name} is missing characters: {missing_text}")

        wrong_name = {
            record.toUnicode()
            for record in font["name"].names
            if record.nameID == 1 and record.platformID in (0, 3)
        }
        if wrong_name != {family_name}:
            raise ValueError(f"{path.name} has unexpected family name(s): {sorted(wrong_name)}")

        if font["head"].unitsPerEm != 1000:
            raise ValueError(f"{path.name} has an unexpected unitsPerEm value")
        if (font.flavor == "woff2") != is_woff2:
            raise ValueError(f"{path.name} has an unexpected font format")
        if font["OS/2"].usWeightClass != (700 if is_bold else 400):
            raise ValueError(f"{path.name} has an unexpected weight class")
        expected_descender = -50 if is_compact else -450
        if font["hhea"].descent != expected_descender:
            raise ValueError(f"{path.name} has unexpected vertical metrics")
        if font["hhea"].ascent - font["hhea"].descent != (900 if is_compact else 1300):
            raise ValueError(f"{path.name} does not have the expected two-unit Short height reduction")
        if font["post"].isFixedPitch != int(is_monospaced):
            raise ValueError(f"{path.name} has an unexpected fixed-pitch flag")

        advances = set()
        for codepoint in EXPECTED_CODEPOINTS:
            glyph_name = cmap[codepoint]
            glyph = font["glyf"][glyph_name]
            advance, left_bearing = font["hmtx"].metrics[glyph_name]
            advances.add(advance)
            if codepoint != 0x20 and glyph.numberOfContours == 0:
                raise ValueError(f"{path.name} has an empty glyph for U+{codepoint:04X}")
            if glyph.numberOfContours and left_bearing != glyph.xMin:
                raise ValueError(f"{path.name} has an invalid left side bearing for U+{codepoint:04X}")
            if is_monospaced and glyph.numberOfContours:
                if abs(glyph.xMin + glyph.xMax - advance) > 1:
                    raise ValueError(f"{path.name} has an off-center glyph for U+{codepoint:04X}")

        expected_mono_advance = 500
        if is_monospaced and advances != {expected_mono_advance}:
            raise ValueError(f"{path.name} is not consistently {expected_mono_advance} units wide")
        if not is_monospaced and len(advances) < 2:
            raise ValueError(f"{path.name} does not have proportional advances")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate and package NGS Noct release fonts.")
    parser.add_argument("--font-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--version", required=True, help="Release tag, for example v1.0.0")
    args = parser.parse_args()

    if not TAG_RE.fullmatch(args.version):
        parser.error("version must be a tag such as v1.0.0 or v1.0.0-rc.1")

    try:
        font_paths = []
        for basename, (family_name, is_monospaced, is_bold, is_compact) in FONTS.items():
            for extension in ("ttf", "woff2"):
                path = args.font_dir / f"{basename}.{extension}"
                if not path.is_file():
                    raise FileNotFoundError(f"missing release font: {path}")
                validate_font(path, family_name, is_monospaced, is_bold, is_compact, extension == "woff2")
                font_paths.append(path)

        for document in DOCUMENTS:
            if not document.is_file():
                raise FileNotFoundError(f"missing release document: {document}")

        args.output_dir.mkdir(parents=True, exist_ok=True)
        release_font_paths = []
        for path in font_paths:
            release_path = args.output_dir / path.name
            shutil.copyfile(path, release_path)
            release_font_paths.append(release_path)

        collection_source = args.font_dir / "NGSNoct.ttc"
        if not collection_source.is_file():
            raise FileNotFoundError(f"missing font collection: {collection_source}")
        collection = TTCollection(str(collection_source), lazy=True)
        if len(collection.fonts) != len(FONTS):
            raise ValueError(f"{collection_source.name} must contain {len(FONTS)} faces")
        collection.close()
        collection_path = args.output_dir / collection_source.name
        shutil.copyfile(collection_source, collection_path)
        release_font_paths.append(collection_path)

        archive_path = args.output_dir / f"NGS-Noct-{args.version}.zip"
        latest_archive_path = args.output_dir / "NGS-Noct.zip"
        archive_root = f"NGS-Noct-{args.version}"
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in release_font_paths:
                archive.write(path, f"{archive_root}/{path.name}")
            for document in DOCUMENTS:
                archive.write(document, f"{archive_root}/{document.name}")
        shutil.copyfile(archive_path, latest_archive_path)

        checksum_paths = [archive_path, latest_archive_path, *release_font_paths]
        checksum_path = args.output_dir / "SHA256SUMS.txt"
        checksum_path.write_text(
            "".join(f"{sha256(path)}  {path.name}\n" for path in checksum_paths),
            encoding="utf-8",
        )
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        parser.error(str(error))

    print(f"Validated {len(FONTS)} fonts with {len(EXPECTED_CODEPOINTS)} characters each.")
    print(f"Created {archive_path}")
    print(f"Created {checksum_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
