import pytest

from finance_rag.chunking import make_chunks
from finance_rag.conversion import parse_pages
from finance_rag.models import Page


def test_marker_physical_page_numbers_and_blank_pages():
    md = "\n\n{0}" + "-" * 48 + "\n\n# Risk\n-1.234,56 TRY\n\n{1}" + "-" * 48 + "\n\n"
    pages = parse_pages(md, {"page_stats": [{"page_id": 0}, {"page_id": 1}]})
    assert [p.number for p in pages] == [1, 2]
    assert "-1.234,56 TRY" in pages[0].markdown
    assert pages[1].markdown == ""


@pytest.mark.parametrize(
    "markdown", ["plain text", "{2}" + "-" * 48 + "\ntext", "prefix\n{0}" + "-" * 48 + "\ntext"]
)
def test_refuses_unreliable_citations(markdown):
    with pytest.raises(ValueError):
        parse_pages(markdown, {})


def test_metadata_mismatch():
    with pytest.raises(ValueError, match="disagree"):
        parse_pages("{0}" + "-" * 48 + "\ntext", {"page_stats": [{"page_id": 1}]})


def test_tables_headers_equations_and_full_coverage():
    table = "| Year | Amount |\n| --- | --- |\n" + "\n".join(
        f"| {year} | -1.234,56 TRY |" for year in range(1990, 2026)
    )
    equation = "$$\nES = E[L | L > VaR]\n$$"
    pages = [
        Page(number=1, markdown="# Risk\n\n" + table + "\n\n" + equation),
        Page(number=2, markdown="Interpretation and assumptions."),
    ]
    chunks = make_chunks("doc", pages, len, 180)
    tables = [c for c in chunks if c.kind == "table"]
    assert len(tables) > 1
    assert all(c.text.startswith("| Year | Amount |\n| --- | --- |") for c in tables)
    for year in range(1990, 2026):
        assert sum(f"| {year} |" in c.text for c in tables) == 1
    assert any(c.text == equation for c in chunks)
    assert all(len(c.embedding_text) <= 180 for c in chunks)
    assert chunks[-1].page == 2 and chunks[-1].section == "Risk"


def test_long_prose_not_silently_truncated():
    text = " ".join(f"token{i}" for i in range(300))
    chunks = make_chunks("doc", [Page(number=1, markdown=text)], len, 100)
    assert " ".join(c.text for c in chunks) == text
    assert all(len(c.embedding_text) <= 100 for c in chunks)


def test_long_heading_and_oversized_row_remain_retrievable():
    md = "# " + "heading " * 100 + "\n\n| A | B |\n| --- | --- |\n| " + "x" * 400 + " | 5 |"
    chunks = make_chunks("doc", [Page(number=1, markdown=md)], len, 100)
    assert all(len(c.embedding_text) <= 100 for c in chunks)
    assert any(c.kind == "table" and c.fragmented for c in chunks)
