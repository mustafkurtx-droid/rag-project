"""Run a real-model MCP acceptance set on the private Brooks book excerpt."""

import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path

from fastmcp import Client
from fastmcp.client.transports import StdioTransport

# Expected original physical PDF pages, labelled from the user's source before retrieval.
CASES = [
    ("OLS neden yatay mesafeler yerine dikey mesafeleri küçültür?", 151),
    ("What is ordinary least squares used for when fitting a line?", 151),
    ("Regresyon doğrusunu göz kararı çizmenin sakıncası nedir?", 151),
    ("Gauss Markov teoreminde BLUE ne anlama gelir?", 163),
    ("OLS tahmincisinin en iyi doğrusal yansız olması ne demektir?", 163),
    ("Consistency and convergence of least squares estimators", 163),
    ("Which estimator has minimum variance among linear unbiased estimators?", 163),
    ("Goldfeld Quandt testi örneklemi nasıl böler?", 258),
    ("Değişen varyansı sadece grafikle tespit etmek neden yanıltıcı olabilir?", 258),
    ("Detection of heteroscedasticity using residual variances", 258),
    ("Heteroskedastic errors with variance changing over time", 258),
    ("ADF testinde gecikmeli fark terimleri neden eklenir?", 450),
    ("Birim kök testinde çok fazla gecikme kullanmanın güce etkisi nedir?", 450),
    ("How can information criteria select augmented Dickey Fuller lag length?", 450),
    ("Monthly and quarterly lag length rules for the ADF test", 450),
    ("GARCH modelinde koşullu varyans kendi geçmiş değerlerine nasıl bağlıdır?", 512),
    ("Who developed the GARCH model independently?", 512),
    ("GARCH(1,1) variance equation and previous volatility information", 512),
    ("Student t distribution critical values degrees of freedom table", 800),
    ("Normal dağılım kritik değerleri tablosu", 800),
]


async def verify(root: Path) -> dict:
    project = Path(__file__).resolve().parents[1]
    source_map = json.loads((root / "source-map.json").read_text(encoding="utf-8"))
    mapping = source_map["excerpt_to_original_pdf"]
    transport = StdioTransport(
        command=sys.executable,
        args=["-m", "finance_rag.server"],
        env={
            **os.environ,
            "FINRAG_ENV_FILE": str(project / ".env"),
            "FINRAG_DATA_DIR": str(root / "store"),
            "FINRAG_ALLOWED_PDF_DIR": str(root / "inbox"),
            "PYTHONUTF8": "1",
        },
    )
    async with Client(transport, timeout=300) as client:
        queued = (
            await client.call_tool(
                "pdf_add",
                {
                    "pdf_path": str(root / "inbox" / "brooks-acceptance.pdf"),
                    "metadata": {
                        "title": "Chris Brooks - Econometrics for Finance - test excerpt",
                        "domain": "econometrics",
                        "language": "en",
                        "tags": ["acceptance-test", "excerpt", "OLS", "ADF", "GARCH"],
                    },
                },
            )
        ).data
        deadline = time.monotonic() + 2400
        while True:
            job = (await client.call_tool("pdf_job_status", {"job_id": queued["job_id"]})).data
            if job["status"] == "succeeded":
                break
            if job["status"] in {"failed", "interrupted"}:
                raise RuntimeError(job)
            if time.monotonic() >= deadline:
                raise TimeoutError("Book acceptance timed out; inspect marker.log")
            await asyncio.sleep(5)
        document_id = job["result"]["document_id"]
        pages = {}
        for number in range(1, 7):
            page = (
                await client.call_tool("pdf_get_page", {"document_id": document_id, "page": number})
            ).data
            assert page["next_offset"] is None
            pages[number] = page["markdown"]
        assert "12.7062" in pages[6] and "1.9600" in pages[6], "Table values changed"
        assert "$$" in pages[5], "GARCH equation did not survive as display math"
        expected_garch = r"\sigma_t^2=\alpha_0+\alpha_1u_{t-1}^2+\beta\sigma_{t-1}^2\tag{9.22}"
        assert expected_garch in re.sub(r"\s+", "", pages[5]), "GARCH equation 9.22 changed"
        searches = []
        for mode in ("semantic", "hybrid"):
            for query, original_page in CASES:
                result = (
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
                retrieved_pages = [mapping[str(row["page"])] for row in result["results"]]
                assert all(row["citation"] for row in result["results"])
                searches.append(
                    {
                        "query": query,
                        "mode": mode,
                        "expected_original_page": original_page,
                        "retrieved_original_pages": retrieved_pages,
                        "hit_at_3": original_page in retrieved_pages,
                        "hit_at_1": bool(retrieved_pages) and retrieved_pages[0] == original_page,
                    }
                )
        lexical = (
            await client.call_tool(
                "pdf_search_keyword", {"query": "Goldfeld", "document_filter": document_id}
            )
        ).data
        assert lexical["results"][0]["page"] == 3
        metrics = {}
        for mode in ("semantic", "hybrid"):
            rows = [row for row in searches if row["mode"] == mode]
            metrics[mode] = {
                "queries": len(rows),
                "recall_at_3": sum(row["hit_at_3"] for row in rows) / len(rows),
                "top_1_page_accuracy": sum(row["hit_at_1"] for row in rows) / len(rows),
            }
        passed = all(value["recall_at_3"] >= 0.9 for value in metrics.values())
        health = (await client.call_tool("pdf_health", {})).data
    return {
        "status": "passed" if passed else "quality_threshold_not_met",
        "document": job["result"],
        "source_map": source_map,
        "checks": {
            "table_values_preserved": True,
            "display_math_present": True,
            "garch_equation_9_22_matches_source": True,
        },
        "metrics": metrics,
        "queries": searches,
        "health": health,
        "scope": "Six selected pages; citations use excerpt page numbers. "
        "Original PDF mapping is explicit. Small acceptance set, not a whole-book benchmark. "
        "Formula transcription requires visual review; math presence alone is not correctness.",
        "known_limitations": [
            "Some inline formula images on the GARCH page are omitted from surrounding prose; "
            "check the PDF for formula-dependent claims.",
            "The 891-page book has not been indexed in full.",
        ],
    }


def main():
    root = Path(__file__).resolve().parents[1] / "data" / "book-acceptance"
    report = asyncio.run(verify(root))
    target = root / "acceptance-report.json"
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": report["status"], "metrics": report["metrics"]}, indent=2))
    if report["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
