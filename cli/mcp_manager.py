"""
mcp_manager.py — MCP server lifecycle and tool execution for Axon CLI.

Manages MCP server subprocesses via stdio transport, discovers tools,
and routes tool calls from the AI to the correct server.
"""

import asyncio
import json
import os
import re
import threading
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Any

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False


_CLI_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CONFIG_PATH = os.path.join(_CLI_DIR, "mcp_config.json")

# Regex for parsing <mcp_tool .../> from AI responses
MCP_TOOL_RE = re.compile(
    r'<mcp_tool\s+server="(?P<server>[^"]+)"\s+'
    r'tool="(?P<tool>[^"]+)"\s+'
    r"args='(?P<args>.*?)'\s*/>",
    re.DOTALL,
)

MCP_SYSTEM_PROMPT_HEADER = (
    "You have access to external tools via MCP (Model Context Protocol) servers.\n"
    "When you need to use a tool, output it using this exact XML format on its own line:\n"
    "\n"
    '<mcp_tool server="server_name" tool="tool_name" args=\'{"param": "value"}\' />\n'
    "\n"
    "Only use tools when necessary. Always explain what you are doing before each tool call.\n"
)


@dataclass
class MCPServerInfo:
    name: str
    command: str
    args: list[str]
    env: dict[str, str] = field(default_factory=dict)
    enabled: bool = True
    # Runtime state
    running: bool = False
    session: Any = None
    tools: list[tuple[str, str, dict]] = field(default_factory=list)  # (name, desc, schema)


class MCPManager:
    """Manages MCP server subprocesses, tool discovery, and tool calls."""

    def __init__(self, config_path: str = DEFAULT_CONFIG_PATH):
        self.config_path = config_path
        self.servers: dict[str, MCPServerInfo] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._stacks: dict[str, AsyncExitStack] = {}

    # ── Config ────────────────────────────────────────

    def load_config(self) -> None:
        if not os.path.isfile(self.config_path):
            return
        try:
            with open(self.config_path, encoding="utf-8") as f:
                data = json.load(f)
            for entry in data.get("servers", []):
                name = entry.get("name", "")
                if not name:
                    continue
                self.servers[name] = MCPServerInfo(
                    name=name,
                    command=entry.get("command", ""),
                    args=entry.get("args", []),
                    env=entry.get("env", {}),
                    enabled=entry.get("enabled", True),
                )
        except Exception:
            pass

    def save_config(self) -> None:
        out: dict[str, Any] = {"servers": []}
        for srv in self.servers.values():
            entry: dict[str, Any] = {
                "name": srv.name,
                "command": srv.command,
                "args": srv.args,
                "enabled": srv.enabled,
            }
            if srv.env:
                entry["env"] = srv.env
            out["servers"].append(entry)
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(out, f, indent=2)
        except Exception:
            pass

    # ── Event loop ────────────────────────────────────

    def _ensure_loop(self) -> None:
        if self._loop is None or not self._loop.is_running():
            self._loop = asyncio.new_event_loop()
            self._thread = threading.Thread(
                target=self._loop.run_forever, daemon=True,
            )
            self._thread.start()

    def _submit(self, coro, timeout: float = 30):
        self._ensure_loop()
        assert self._loop is not None
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=timeout)

    # ── Startup ───────────────────────────────────────

    def start(self) -> list[str]:
        """Load config, start event loop, connect enabled servers.

        Returns list of error messages (empty on full success).
        """
        if not MCP_AVAILABLE:
            return ["mcp package not installed — run: pip install mcp"]
        self.load_config()
        if not self.servers:
            return []
        self._ensure_loop()
        errors: list[str] = []
        for name, srv in self.servers.items():
            if srv.enabled:
                try:
                    self._submit(self._async_connect(name))
                except Exception as exc:
                    errors.append(f"{name}: {exc}")
        return errors

    # ── Connect / disconnect ──────────────────────────

    async def _async_connect(self, name: str) -> None:
        srv = self.servers[name]
        stack = AsyncExitStack()
        merged_env = {**os.environ, **srv.env}
        params = StdioServerParameters(
            command=srv.command, args=srv.args, env=merged_env,
        )
        read, write = await stack.enter_async_context(stdio_client(params))
        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        tools_result = await session.list_tools()
        srv.session = session
        srv.tools = [
            (t.name, t.description or "", t.inputSchema or {})
            for t in tools_result.tools
        ]
        srv.running = True
        self._stacks[name] = stack

    def connect_server(self, name: str) -> None:
        if not MCP_AVAILABLE:
            raise RuntimeError("mcp package not installed")
        self._submit(self._async_connect(name))
        srv = self.servers.get(name)
        if srv:
            srv.enabled = True
            self.save_config()

    def disconnect_server(self, name: str) -> None:
        self._submit(self._async_disconnect(name))
        srv = self.servers.get(name)
        if srv:
            srv.enabled = False
            self.save_config()

    async def _async_disconnect(self, name: str) -> None:
        stack = self._stacks.pop(name, None)
        if stack:
            await stack.aclose()
        srv = self.servers.get(name)
        if srv:
            srv.session = None
            srv.tools = []
            srv.running = False

    # ── Tool calls ────────────────────────────────────

    def call_tool(self, server_name: str, tool_name: str, arguments: dict) -> str:
        srv = self.servers.get(server_name)
        if not srv or not srv.running or not srv.session:
            return f"Error: server '{server_name}' is not running"
        try:
            return self._submit(
                self._async_call_tool(srv.session, tool_name, arguments),
            )
        except Exception as exc:
            return f"Error calling {server_name}/{tool_name}: {exc}"

    async def _async_call_tool(self, session, tool_name: str, arguments: dict) -> str:
        result = await session.call_tool(tool_name, arguments)
        texts = []
        for content in result.content:
            if hasattr(content, "text"):
                texts.append(content.text)
            else:
                texts.append(str(content))
        return "\n".join(texts) if texts else "(empty result)"

    # ── Tool descriptions for system prompt ───────────

    def get_tools_prompt(self) -> str:
        """Build a system prompt section listing all available MCP tools."""
        lines: list[str] = []
        for srv in self.servers.values():
            if not srv.running:
                continue
            for tool_name, desc, schema in srv.tools:
                params = schema.get("properties", {})
                param_str = ", ".join(params.keys()) if params else ""
                lines.append(f"- {srv.name}/{tool_name}({param_str}): {desc}")
        if not lines:
            return ""
        return MCP_SYSTEM_PROMPT_HEADER + "\n" + "\n".join(lines)

    # ── Parse tool calls from AI response ─────────────

    @staticmethod
    def parse_tool_calls(text: str) -> list[dict]:
        """Extract <mcp_tool .../> blocks from AI response."""
        calls = []
        for m in MCP_TOOL_RE.finditer(text):
            args_str = m.group("args")
            try:
                args = json.loads(args_str)
            except (json.JSONDecodeError, TypeError):
                args = {}
            calls.append({
                "server": m.group("server"),
                "tool": m.group("tool"),
                "args": args,
                "raw": m.group(0),
            })
        return calls

    # ── Status helpers ────────────────────────────────

    def has_running_servers(self) -> bool:
        return any(s.running for s in self.servers.values())

    def add_server(self, name: str, command: str, args: list[str]) -> None:
        self.servers[name] = MCPServerInfo(
            name=name, command=command, args=args, enabled=False,
        )
        self.save_config()

    # ── Shutdown ──────────────────────────────────────

    def shutdown(self) -> None:
        for name in list(self._stacks):
            try:
                self._submit(self._async_disconnect(name), timeout=5)
            except Exception:
                pass
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread:
            self._thread.join(timeout=5)
