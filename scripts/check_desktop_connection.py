"""Check an exported desktop profile over real stdio, without downloading models."""

import argparse
import asyncio
import json
import time
import tomllib
from pathlib import Path
from tempfile import TemporaryDirectory

from fastmcp import Client
from fastmcp.client.transports import StdioTransport


async def check(profile: Path, isolated_data_dir: Path | None = None) -> dict:
    text = profile.read_text(encoding="utf-8-sig")
    if profile.suffix == ".toml":
        entry = tomllib.loads(text)["mcp_servers"]["finance-rag"]
    else:
        entry = json.loads(text)["mcpServers"]["finance-rag"]
    env = dict(entry.get("env", {}))
    if isolated_data_dir is not None:
        env["FINRAG_DATA_DIR"] = str(isolated_data_dir)
        env["FINRAG_ALLOWED_PDF_DIR"] = str(isolated_data_dir / "inbox")
    transport = StdioTransport(command=entry["command"], args=entry["args"], env=env)
    async with Client(transport, timeout=60) as client:
        tools = [tool.name for tool in await client.list_tools()]
        library = await client.call_tool("pdf_list", {})
        health = await client.call_tool("pdf_health", {})
    return {
        "status": "connected",
        "profile": str(profile.resolve()),
        "isolated_library": isolated_data_dir is not None,
        "tools": tools,
        "document_count": library.data["count"],
        "health": health.data,
        "notice": "Protocol connection verified; desktop app activation is not confirmed.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", type=Path)
    parser.add_argument(
        "--isolated",
        action="store_true",
        help="Check using a temporary library while a desktop server is running",
    )
    args = parser.parse_args()
    if args.isolated:
        temporary = TemporaryDirectory(prefix="finance-rag-check-")
        try:
            result = asyncio.run(check(args.profile, Path(temporary.name)))
        finally:
            # Windows can hold SQLite/Chroma handles briefly after process exit.
            for attempt in range(21):
                try:
                    temporary.cleanup()
                    break
                except PermissionError:
                    if attempt == 20:
                        raise
                    time.sleep(0.5)
    else:
        result = asyncio.run(check(args.profile))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
