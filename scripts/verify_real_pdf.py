"""Manual acceptance check with real Marker/E5 over MCP; may download model weights.

Expects the synthetic two-page finance-risk-acceptance.pdf in a separate inbox.
Never points at the desktop's production library by default.
"""

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

from fastmcp import Client
from fastmcp.client.transports import StdioTransport


async def verify(root: Path, timeout: int) -> dict:
    project = Path(__file__).resolve().parents[1]
    pdf = root / "inbox" / "finance-risk-acceptance.pdf"
    if not pdf.is_file():
        raise FileNotFoundError(pdf)
    env = {
        **os.environ,
        "FINRAG_ENV_FILE": str(project / ".env"),
        "FINRAG_DATA_DIR": str(root / "store"),
        "FINRAG_ALLOWED_PDF_DIR": str(root / "inbox"),
        "PYTHONUTF8": "1",
    }
    transport = StdioTransport(command=sys.executable, args=["-m", "finance_rag.server"], env=env)
    async with Client(transport, timeout=300) as client:
        added = (
            await client.call_tool(
                "pdf_add",
                {
                    "pdf_path": str(pdf),
                    "metadata": {
                        "title": "Synthetic finance risk acceptance fixture",
                        "domain": "risk",
                        "language": "en",
                        "tags": ["synthetic", "acceptance-test"],
                    },
                },
            )
        ).data
        deadline = time.monotonic() + timeout
        while True:
            job = (await client.call_tool("pdf_job_status", {"job_id": added["job_id"]})).data
            if job["status"] == "succeeded":
                break
            if job["status"] in {"failed", "interrupted"}:
                raise RuntimeError(job)
            if time.monotonic() > deadline:
                raise TimeoutError("Acceptance timeout; inspect the persistent job and marker.log.")
            await asyncio.sleep(2)
        document_id = job["result"]["document_id"]
        pages = {}
        for number in (1, 2):
            page = (
                await client.call_tool("pdf_get_page", {"document_id": document_id, "page": number})
            ).data
            assert page["next_offset"] is None, "Fixture page unexpectedly truncated"
            pages[number] = page["markdown"]
        assert "-1250.50" in pages[1] and "-1875.75" in pages[1], pages[1]
        assert "CREDITSCAN42" in pages[2], "Scanned page OCR token missing"
        assert "900.00" in pages[2] and "100000.00" in pages[2], pages[2]
        queries = [
            ("keyword", "CREDITSCAN42", 2),
            ("semantic", "Borçlunun temerrüdü ve beklenen kredi zararı", 2),
            ("hybrid", "kredi riski PD LGD EAD", 2),
            ("hybrid", "Expected Shortfall portfolio stress losses", 1),
        ]
        searches = []
        for mode, query, expected_page in queries:
            found = (
                await client.call_tool(
                    "pdf_search",
                    {
                        "query": query,
                        "mode": mode,
                        "top_k": 3,
                        "filters": {"document_id": document_id},
                    },
                )
            ).data
            assert found["count"] > 0, found
            assert found["results"][0]["page"] == expected_page, found
            assert all(item["citation"] for item in found["results"]), found
            searches.append(found)
        health = (await client.call_tool("pdf_health", {})).data
    return {
        "status": "passed",
        "document": job["result"],
        "checks": {
            "page_count": 2,
            "negative_decimal_values_preserved": True,
            "raster_page_ocr_token_found": True,
            "ocr_numeric_values_preserved": True,
            "turkish_semantic_query_retrieved_english_page": True,
            "citations_and_expected_top_pages": True,
        },
        "searches": searches,
        "health": health,
        "notice": "Synthetic fixture only; does not establish general OCR or finance accuracy.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("data/acceptance"))
    parser.add_argument("--timeout", type=int, default=2400)
    args = parser.parse_args()
    root = args.root.resolve()
    report = asyncio.run(verify(root, args.timeout))
    output = root / "acceptance-report.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": report["status"], "report": str(output)}, indent=2))


if __name__ == "__main__":
    main()
