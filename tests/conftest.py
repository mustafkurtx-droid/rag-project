import hashlib
import json
import math
import re

import pytest

from finance_rag.config import Settings
from finance_rag.models import Page
from finance_rag.service import FinanceRAG


class FakeEmbedder:
    """Deterministic test double; never selectable through production configuration."""

    def count(self, text):
        return len(text) // 4 + 4

    def encode(self, texts, *, query=False):
        vectors = []
        for text in texts:
            vector = [0.0] * 64
            for token in re.findall(r"\w+", text.lower()):
                index = int(hashlib.sha256(token.encode()).hexdigest()[:8], 16) % 64
                vector[index] += 1
            norm = math.sqrt(sum(x * x for x in vector)) or 1
            vectors.append([x / norm for x in vector])
        return vectors


class FakeConverter:
    def __init__(self):
        self.calls = 0
        self.fail = False

    def convert(self, pdf, output, force_ocr=False):
        self.calls += 1
        if self.fail:
            raise RuntimeError("Simulated OCR failure")
        pages = [
            Page(
                number=1,
                markdown="# Market risk\n\nValue at Risk (VaR) uses a loss quantile.\n\n"
                "$$\nVaR_{0.99}(L) = q_{0.99}(L)\n$$",
            ),
            Page(
                number=2,
                markdown="## Expected shortfall\n\nExpected shortfall considers tail losses."
                "\n\n| Measure | Value |\n| --- | --- |\n| VaR | -1.234,56 TRY |\n"
                "\nFootnote: hypothetical data, not market observations.",
            ),
        ]
        (output / "document.md").write_text(
            "\n\n".join(p.markdown for p in pages), encoding="utf-8"
        )
        (output / "document_meta.json").write_text(json.dumps({}), encoding="utf-8")
        return pages


@pytest.fixture
def settings(tmp_path):
    return Settings(_env_file=None, data_dir=tmp_path / "store", allowed_pdf_dir=tmp_path / "inbox")


@pytest.fixture
def rag(settings):
    service = FinanceRAG(settings, converter=FakeConverter(), embedder=FakeEmbedder())
    yield service
    service.close()


@pytest.fixture
def pdf(rag):
    path = rag.settings.allowed_pdf_dir / "risk.pdf"
    path.write_bytes(b"%PDF-1.7\nsynthetic input for adapter tests")
    return path
