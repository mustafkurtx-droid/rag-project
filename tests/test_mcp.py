import sys

from fastmcp import Client
from fastmcp.client.transports import StdioTransport

from finance_rag.models import DocumentMetadata
from finance_rag.server import create_server


async def test_real_mcp_schema_tools_and_retrieval(rag, pdf):
    added = rag.add(str(pdf), DocumentMetadata(domain="risk"))
    server = create_server(rag.settings, service=rag)
    async with Client(server) as client:
        names = {tool.name for tool in await client.list_tools()}
        assert {
            "pdf_add",
            "pdf_search",
            "pdf_search_similarity",
            "pdf_search_keyword",
            "pdf_list",
            "pdf_remove",
            "pdf_get_page",
            "pdf_job_status",
            "pdf_health",
        } <= names
        result = await client.call_tool("pdf_search", {"query": "VaR", "mode": "keyword"})
        assert result.data["count"] > 0
        page = await client.call_tool(
            "pdf_get_page", {"document_id": added["document_id"], "page": 2}
        )
        assert "TRY" in page.data["markdown"]
        queued = await client.call_tool(
            "pdf_add", {"pdf_path": str(pdf), "metadata": {"domain": "risk"}}
        )
        assert queued.data["job_id"]
        rules = await client.read_resource("finance://research-rules")
        assert "untrusted" in rules[0].text


async def test_stdio_startup_without_model_downloads(tmp_path):
    transport = StdioTransport(
        command=sys.executable,
        args=["-m", "finance_rag.server"],
        env={
            "FINRAG_DATA_DIR": str(tmp_path / "store"),
            "FINRAG_ALLOWED_PDF_DIR": str(tmp_path / "inbox"),
            "PYTHONUTF8": "1",
        },
    )
    async with Client(transport) as client:
        result = await client.call_tool("pdf_list", {})
        assert result.data["count"] == 0
        result = await client.call_tool("pdf_search", {"query": "VaR"})
        assert result.data["results"] == []
