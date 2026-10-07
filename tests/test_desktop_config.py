import importlib.util
import json
import tomllib
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "configure_desktop.py"
spec = importlib.util.spec_from_file_location("configure_desktop", SCRIPT)
desktop = importlib.util.module_from_spec(spec)
spec.loader.exec_module(desktop)

ENTRY = {
    "command": "C:/example/python.exe",
    "args": ["-m", "finance_rag.server"],
    "env": {"FINRAG_ENV_FILE": "C:/project/.env", "PYTHONUTF8": "1"},
}


def test_claude_merge_backup_and_idempotency(tmp_path):
    target = tmp_path / "claude.json"
    original = '{"mcpServers":{"other":{"command":"other"}},"preferences":{"theme":"dark"}}'
    target.write_text(original)
    result = desktop.install("claude", target, ENTRY)
    config = json.loads(target.read_text())
    assert config["preferences"]["theme"] == "dark"
    assert config["mcpServers"]["other"]["command"] == "other"
    assert Path(result["backup"]).read_text() == original
    assert desktop.install("claude", target, ENTRY)["status"] == "already_configured"


def test_chatgpt_preserves_existing_toml(tmp_path):
    target = tmp_path / "config.toml"
    original = '# keep comments\nmodel = "existing-model"\n[mcp_servers.other]\ncommand = "other"\n'
    target.write_text(original)
    desktop.install("chatgpt", target, ENTRY)
    assert target.read_text().startswith(original)
    config = tomllib.loads(target.read_text())
    assert config["model"] == "existing-model"
    assert config["mcp_servers"]["other"]["command"] == "other"
    assert config["mcp_servers"]["finance-rag"]["tool_timeout_sec"] == 300


@pytest.mark.parametrize("client,text", [("claude", "invalid json"), ("chatgpt", "[broken")])
def test_invalid_configs_are_not_overwritten(tmp_path, client, text):
    target = tmp_path / "config"
    target.write_text(text)
    with pytest.raises(ValueError):
        desktop.install(client, target, ENTRY)
    assert target.read_text() == text


def test_conflicting_server_is_not_overwritten(tmp_path):
    target = tmp_path / "config.json"
    target.write_text('{"mcpServers":{"finance-rag":{"command":"another-server"}}}')
    original = target.read_bytes()
    with pytest.raises(ValueError, match="different finance-rag"):
        desktop.install("claude", target, ENTRY)
    assert target.read_bytes() == original
