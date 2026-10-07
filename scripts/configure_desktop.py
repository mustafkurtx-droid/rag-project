"""Generate or install one local desktop MCP entry without replacing other settings."""

import argparse
import json
import os
import tempfile
import tomllib
from datetime import UTC, datetime
from pathlib import Path

SERVER_NAME = "finance-rag"


def server_entry(project: Path, python_override: Path | None = None) -> dict:
    project = project.resolve()
    python = python_override or project / ".venv" / "Scripts" / "python.exe"
    python = python.resolve()
    if not python.is_file():
        raise ValueError(f"Project Python does not exist: {python}")
    return {
        "command": python.as_posix(),
        "args": ["-m", "finance_rag.server"],
        "env": {
            "FINRAG_ENV_FILE": (project / ".env").as_posix(),
            "FINRAG_DATA_DIR": (project / "data").as_posix(),
            "FINRAG_ALLOWED_PDF_DIR": (project / "data" / "inbox").as_posix(),
            "PYTHONUTF8": "1",
        },
    }


def toml_entry(entry: dict) -> str:
    lines = [
        f"[mcp_servers.{SERVER_NAME}]",
        f"command = {json.dumps(entry['command'])}",
        f"args = {json.dumps(entry['args'])}",
        "startup_timeout_sec = 90",
        "tool_timeout_sec = 300",
        "enabled = true",
        "",
        f"[mcp_servers.{SERVER_NAME}.env]",
    ]
    lines.extend(f"{key} = {json.dumps(value)}" for key, value in entry["env"].items())
    return "\n".join(lines) + "\n"


def install(client: str, target: Path, entry: dict) -> dict:
    original = target.read_bytes() if target.exists() else b""
    text = original.decode("utf-8-sig")
    if client == "claude":
        config = json.loads(text) if text.strip() else {}
        if not isinstance(config, dict) or not isinstance(config.get("mcpServers", {}), dict):
            raise ValueError("Claude config and mcpServers must be JSON objects.")
        servers = config.setdefault("mcpServers", {})
        expected = entry
    else:
        config = tomllib.loads(text)
        servers = config.get("mcp_servers", {})
        expected = tomllib.loads(toml_entry(entry))["mcp_servers"][SERVER_NAME]
    if SERVER_NAME in servers:
        if servers[SERVER_NAME] == expected:
            return {"status": "already_configured", "config": str(target)}
        raise ValueError(
            "A different finance-rag entry already exists; inspect it before replacing."
        )
    if client == "claude":
        servers[SERVER_NAME] = entry
        content = (json.dumps(config, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    else:
        content = original.rstrip() + b"\n\n" + toml_entry(entry).encode("utf-8")
        tomllib.loads(content.decode("utf-8-sig"))
    target.parent.mkdir(parents=True, exist_ok=True)
    backup = None
    if target.exists():
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        backup = target.with_name(f"{target.name}.{stamp}.bak")
        backup.write_bytes(original)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
        temporary.replace(target)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)
    return {
        "status": "configured",
        "config": str(target),
        "backup": str(backup) if backup else None,
        "next_step": "Restart the selected desktop client's MCP connection.",
    }


def default_target(client: str) -> Path:
    if client == "chatgpt":
        return Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))) / "config.toml"
    standard = Path(os.environ["APPDATA"]) / "Claude" / "claude_desktop_config.json"
    packages = Path(os.environ["LOCALAPPDATA"]) / "Packages"
    candidates = list(
        packages.glob("Claude_*/LocalCache/Roaming/Claude/claude_desktop_config.json")
    )
    existing = [path for path in [standard, *candidates] if path.is_file()]
    if len(existing) > 1:
        raise ValueError(
            "Multiple Claude configs found. Use --config with Developer > Edit Config path."
        )
    return existing[0] if existing else standard


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client", choices=["claude", "chatgpt"], required=True)
    parser.add_argument("--project", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--config", type=Path, help="Explicit client config path")
    parser.add_argument(
        "--python", type=Path, help="Python in a separately located clean environment"
    )
    parser.add_argument("--apply", action="store_true", help="Install; otherwise print config only")
    args = parser.parse_args()
    entry = server_entry(args.project, args.python)
    if args.apply:
        result = install(args.client, args.config or default_target(args.client), entry)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif args.client == "claude":
        print(json.dumps({"mcpServers": {SERVER_NAME: entry}}, indent=2, ensure_ascii=False))
    else:
        print(toml_entry(entry), end="")


if __name__ == "__main__":
    main()
