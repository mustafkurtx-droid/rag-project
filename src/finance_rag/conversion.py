import json
import os
import re
import subprocess
import sys
from pathlib import Path

from .config import Settings
from .models import Page

PAGE_MARKER = re.compile(r"(?m)^\{(\d+)\}-{48}\s*$")


def parse_pages(markdown: str, metadata: dict) -> list[Page]:
    """Marker IDs are zero-based physical PDF pages, not printed page labels."""
    markers = list(PAGE_MARKER.finditer(markdown))
    if not markers or markdown[: markers[0].start()].strip():
        raise ValueError("Marker output has no reliable page markers; refusing invented citations.")
    pages = []
    for i, match in enumerate(markers):
        end = markers[i + 1].start() if i + 1 < len(markers) else len(markdown)
        # Do not normalize numbers, decimal separators, signs, currencies or formulae.
        text = markdown[match.end() : end].replace("\r\n", "\n").strip()
        pages.append(Page(number=int(match.group(1)) + 1, markdown=text))
    ids = [p.number - 1 for p in pages]
    if ids != list(range(len(ids))):
        raise ValueError(
            "Non-contiguous or duplicate Marker page IDs; full-PDF conversion required."
        )
    expected = [p["page_id"] for p in metadata.get("page_stats", [])]
    if expected and expected != ids:
        raise ValueError("Marker page metadata and Markdown page boundaries disagree.")
    return pages


class MarkerConverter:
    def __init__(self, settings: Settings):
        self.settings = settings

    def convert(self, pdf: Path, output: Path, force_ocr: bool = False) -> list[Page]:
        command = [
            self.settings.marker_python or sys.executable,
            str(Path(__file__).with_name("marker_worker.py")),
            str(pdf),
            str(output),
            "--device",
            self.settings.marker_device,
        ]
        if force_ocr:
            command.append("--force-ocr")
        environment = os.environ.copy()
        environment["PYTHONUTF8"] = "1"
        if self.settings.model_cache_dir is not None:
            root = self.settings.model_cache_dir.expanduser().resolve()
            environment["MODEL_CACHE_DIR"] = str(root / "marker")
            environment["TEMP"] = environment["TMP"] = str(root / "tmp")
        # Do not inherit the previous Marker 2 server configuration.
        for key in ("LLAMA_CPP_BINARY", "SURYA_INFERENCE_BACKEND", "SURYA_INFERENCE_URL"):
            environment.pop(key, None)
        log_path = output / "marker.log"
        try:
            with log_path.open("w", encoding="utf-8") as log:
                result = subprocess.run(
                    command,
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    timeout=self.settings.marker_timeout_seconds,
                    check=False,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"Marker timed out; inspect {log_path}") from exc
        if result.returncode:
            raise RuntimeError(
                f"Marker failed (exit {result.returncode}); inspect {log_path}. "
                "Check the dedicated marker-pdf==1.10.1 Python environment with doctor."
            )
        markdown = (output / "document.md").read_text(encoding="utf-8")
        metadata = json.loads((output / "document_meta.json").read_text(encoding="utf-8"))
        return parse_pages(markdown, metadata)
