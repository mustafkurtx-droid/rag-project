"""Create a private six-page acceptance excerpt from the supplied 891-page Brooks PDF."""

import argparse
import hashlib
import json
from pathlib import Path

from pypdf import PdfReader, PdfWriter

PAGES = (151, 163, 258, 450, 512, 800)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    args = parser.parse_args()
    source = args.source.expanduser().resolve(strict=True)
    reader = PdfReader(source)
    if len(reader.pages) != 891:
        raise ValueError("This acceptance profile expects the supplied 891-page edition.")
    root = Path(__file__).resolve().parents[1] / "data" / "book-acceptance"
    (root / "inbox").mkdir(parents=True, exist_ok=True)
    target = root / "inbox" / "brooks-acceptance.pdf"
    if target.exists():
        raise FileExistsError("Excerpt already exists; use it or choose a fresh test workspace.")
    writer = PdfWriter()
    for number in PAGES:
        writer.add_page(reader.pages[number - 1])
    writer.add_metadata(
        {"/Title": "Brooks Econometrics - acceptance excerpt", "/Author": "Chris Brooks"}
    )
    with target.open("wb") as stream:
        writer.write(stream)
    mapping = {
        "source": str(source),
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "source_total_pages": len(reader.pages),
        "excerpt_to_original_pdf": {str(i + 1): number for i, number in enumerate(PAGES)},
    }
    (root / "source-map.json").write_text(json.dumps(mapping, indent=2), encoding="utf-8")
    print(json.dumps({"excerpt": str(target), "original_pdf_pages": PAGES}, indent=2))


if __name__ == "__main__":
    main()
