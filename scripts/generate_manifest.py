#!/usr/bin/env python3
"""Generate manifest tool metadata from mcp_server.py decorators."""

from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MCP_SERVER_PATH = ROOT / "mcp_server.py"
MANIFEST_PATH = ROOT / "manifest.json"


def _is_mcp_tool_decorator(decorator: ast.AST) -> bool:
    if not isinstance(decorator, ast.Call):
        return False
    func = decorator.func
    if not isinstance(func, ast.Attribute):
        return False
    if func.attr != "tool":
        return False
    value = func.value
    return isinstance(value, ast.Name) and value.id == "mcp"


def _extract_tool_defs() -> list[dict[str, str]]:
    tree = ast.parse(MCP_SERVER_PATH.read_text(encoding="utf-8"), filename=str(MCP_SERVER_PATH))
    tools: list[dict[str, str]] = []

    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not any(_is_mcp_tool_decorator(dec) for dec in node.decorator_list):
            continue

        name = node.name
        raw_docstring = ast.get_docstring(node) or ""
        first_line = next((line.strip() for line in raw_docstring.splitlines() if line.strip()), "")
        description = first_line or f"MCP tool: {name}"
        tools.append({"name": name, "description": description})

    return tools


def main() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    tools = _extract_tool_defs()
    manifest["tools"] = tools
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Updated {MANIFEST_PATH} with {len(tools)} tool entries")


if __name__ == "__main__":
    main()
