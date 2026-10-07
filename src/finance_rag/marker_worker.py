"""Standalone worker: all third-party stdout stays outside the MCP transport."""

import argparse
import json
from importlib.metadata import version
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf")
    parser.add_argument("output")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--force-ocr", action="store_true")
    args = parser.parse_args()

    # Check before any model creation: Marker 2 may spawn external inference servers.
    installed = version("marker-pdf")
    if installed != "1.10.1":
        raise RuntimeError(
            f"Expected server-free marker-pdf==1.10.1, found {installed}. "
            "Set FINRAG_MARKER_PYTHON to the dedicated Marker environment."
        )
    from marker.converters.pdf import PdfConverter
    from marker.models import create_model_dict
    from marker.output import save_output

    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    models = create_model_dict(device=args.device)
    try:
        converter = PdfConverter(
            artifact_dict=models,
            config={
                "paginate_output": True,
                "page_separator": "-" * 48,
                "use_llm": False,
                "force_ocr": args.force_ocr,
                "html_tables_in_markdown": False,
            },
        )
        rendered = converter(args.pdf)
        save_output(rendered, str(output), "document")
        (output / "conversion.json").write_text(
            json.dumps(
                {
                    "marker_version": installed,
                    "engine": "native-pytorch",
                    "device": args.device,
                    "force_ocr": args.force_ocr,
                    "use_llm": False,
                }
            ),
            encoding="utf-8",
        )
    finally:
        # Models live only in this worker process; there is no inference daemon.
        models.clear()


if __name__ == "__main__":
    main()
