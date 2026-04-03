"""
tui.py — Interactive TUI for Axon CLI.

Uses rich for rendering and prompt_toolkit for input.
"""

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from glob import glob

import pyperclip
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import CompleteEvent, Completer, Completion
from prompt_toolkit.document import Document
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.styles import Style
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.rule import Rule
from rich.syntax import Syntax
from rich.text import Text

from cli.lm_client import (
    MODEL_SLOTS,
    check_lm_studio,
    slot_info,
    stream_completion,
)
from cli.agent_executor import (
    get_agent_system_prompt,
    execute_read_file,
    execute_run_command,
    execute_write_file,
    parse_actions,
    print_action_prompt,
)
from cli.mcp_manager import MCPManager

console = Console()

_CLI_DIR = os.path.dirname(os.path.abspath(__file__))
_SESSIONS_DIR = os.path.join(_CLI_DIR, "sessions")
_CODE_BLOCK_RE = re.compile(r'```(\w*)\n?(.*?)```', re.DOTALL)
_AT_FILE_RE = re.compile(r'@([^\s]+)')
_CODE_EXTENSIONS = {".py", ".js", ".ts", ".lua", ".md", ".txt", ".json", ".yaml", ".yml", ".html", ".css"}

_SLASH_COMMANDS = [
    "/model", "/slot", "/clear", "/history",
    "/save", "/load", "/sessions", "/copy",
    "/theme", "/permissions", "/agent", "/mcp",
    "/help", "/exit", "/quit",
]

_DEFAULT_SHELL_CMDS = [
    "git status", "git log", "git diff", "git add .", 'git commit -m ""',
    "ls", "dir", "pwd", "python --version", "pip list",
]

_PROMPT_STYLE = Style.from_dict({
    "completion-menu.completion":              "bg:#1a1a1a #a0a0a0",
    "completion-menu.completion.current":      "bg:#003333 #00ffff bold",
    "completion-menu.meta.completion":         "bg:#1a1a1a #606060",
    "completion-menu.meta.completion.current": "bg:#003333 #00cccc",
    "scrollbar.background": "bg:#1a1a1a",
    "scrollbar.button":     "bg:#444444",
})

# ── Config ──────────────────────────────────────────

_CONFIG_PATH = os.path.join(_CLI_DIR, "config.json")
_CONFIG_DEFAULTS = {"theme": "cyber", "default_slot": 1, "permissions": "normal"}


def _load_config() -> dict:
    try:
        with open(_CONFIG_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return {**_CONFIG_DEFAULTS, **data}
    except Exception:
        return dict(_CONFIG_DEFAULTS)


def _save_config(cfg: dict) -> None:
    try:
        with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except Exception:
        pass


# ── Themes ─────────────────────────────────────────

_THEMES = {
    "cyber":  {"border": "cyan",    "accent": "cyan",         "mascot": "cyan",         "desc": "Default — electric cyan"},
    "dark":   {"border": "white",   "accent": "white",        "mascot": "white",        "desc": "Minimal monochrome"},
    "matrix": {"border": "green",   "accent": "bright_green", "mascot": "bright_green", "desc": "Classic terminal green"},
    "warm":   {"border": "yellow",  "accent": "yellow",       "mascot": "yellow",       "desc": "Warm amber tones"},
}


# ── Context meter ──────────────────────────────────

_MAX_CONTEXT_TOKENS = 8192


def _estimate_tokens(history: list) -> int:
    total_chars = sum(len(m.get("content", "")) for m in history)
    return max(0, total_chars // 4)


def _context_bar(tokens: int) -> tuple[str, str]:
    """Return (bar_markup, pct_str). Bar is 10 chars wide."""
    pct = min(1.0, tokens / _MAX_CONTEXT_TOKENS)
    filled = round(pct * 10)
    bar = "█" * filled + "░" * (10 - filled)
    pct_str = f"{int(pct * 100)}%"
    if pct >= 0.9:
        color = "red"
    elif pct >= 0.7:
        color = "yellow"
    else:
        color = "dim"
    return f"[{color}]{bar}[/{color}]", pct_str


class _AxonCompleter(Completer):
    """Context-aware completer: @files, !shell history, /commands."""

    def __init__(self, shell_history: list) -> None:
        self._shell_history = shell_history

    def get_completions(self, document: Document, complete_event: CompleteEvent):
        text = document.text_before_cursor

        # /commands
        if text.startswith("/"):
            partial = text.lower()
            for cmd in _SLASH_COMMANDS:
                if cmd.startswith(partial):
                    yield Completion(cmd[len(text):], start_position=0, display=cmd)
            return

        # !shell history
        if text.startswith("!"):
            partial = text[1:].lower()
            candidates = list(reversed(self._shell_history)) if self._shell_history else _DEFAULT_SHELL_CMDS
            seen: set = set()
            for cmd in candidates:
                if cmd.lower().startswith(partial) and cmd not in seen:
                    seen.add(cmd)
                    yield Completion(
                        cmd[len(partial):],
                        start_position=0,
                        display="!" + cmd,
                    )
            return

        # @file picker
        at_idx = text.rfind("@")
        if at_idx != -1:
            partial = text[at_idx + 1:]
            try:
                entries = os.listdir(".")
            except OSError:
                return
            for entry in sorted(entries):
                if entry.startswith("."):
                    continue
                is_dir = os.path.isdir(entry)
                if not is_dir:
                    _, ext = os.path.splitext(entry)
                    if ext.lower() not in _CODE_EXTENSIONS:
                        continue
                if entry.lower().startswith(partial.lower()):
                    suffix = "/" if is_dir else ""
                    yield Completion(
                        entry[len(partial):] + suffix,
                        start_position=0,
                        display="@" + entry + suffix,
                    )


def _render_with_syntax(text: str) -> None:
    """Print response text, rendering fenced code blocks with Syntax highlighting."""
    last = 0
    for m in _CODE_BLOCK_RE.finditer(text):
        before = text[last:m.start()]
        if before:
            console.print(before, markup=False, highlight=False, end="")
        lang = m.group(1).strip() or "text"
        code = m.group(2).rstrip("\n")
        console.print(Syntax(code, lang, theme="monokai", line_numbers=False, word_wrap=True))
        last = m.end()
    remaining = text[last:]
    if remaining:
        console.print(remaining, markup=False, highlight=False, end="")
    console.print()


# ── Session save/load ─────────────────────────────────

def _save_session(history: list, slot: int) -> None:
    os.makedirs(_SESSIONS_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"session_{ts}.json"
    path = os.path.join(_SESSIONS_DIR, filename)
    data = {
        "saved_at": datetime.now().isoformat(),
        "slot": slot,
        "model": slot_info(slot)["model_id"],
        "messages": history,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    console.print(f"  [green]💾 Session saved → {os.path.relpath(path)}[/green]\n")


def _list_sessions() -> list[dict]:
    """Return sorted list of session dicts (newest first)."""
    files = glob(os.path.join(_SESSIONS_DIR, "session_*.json"))
    sessions = []
    for f in sorted(files, reverse=True):
        try:
            with open(f, encoding="utf-8") as fh:
                data = json.load(fh)
            sessions.append({
                "path": f,
                "filename": os.path.basename(f),
                "saved_at": data.get("saved_at", ""),
                "slot": data.get("slot", 1),
                "model": data.get("model", ""),
                "messages": data.get("messages", []),
                "count": len(data.get("messages", [])),
            })
        except Exception:
            pass
    return sessions


def _print_sessions() -> list[dict]:
    sessions = _list_sessions()
    if not sessions:
        console.print("  [dim]No saved sessions yet.[/dim]\n")
        return []
    console.print()
    console.print("[cyan]Saved sessions:[/cyan]")
    for i, s in enumerate(sessions, 1):
        ts = s["saved_at"][:19].replace("T", " ") if s["saved_at"] else "unknown"
        console.print(
            f"  [white]{i}[/white]  [dim]{ts}[/dim]  "
            f"[bright_white]{s['count']} messages[/bright_white]  "
            f"[dim]{s['filename']}[/dim]"
        )
    console.print()
    return sessions


def _load_session_interactive(session: PromptSession) -> tuple[list, int] | tuple[None, None]:
    sessions = _print_sessions()
    if not sessions:
        return None, None
    try:
        pick = session.prompt(HTML("<ansiwhite>Load session # (or Enter to cancel): </ansiwhite>")).strip()
    except (KeyboardInterrupt, EOFError):
        return None, None
    if not pick.isdigit():
        return None, None
    n = int(pick)
    if n < 1 or n > len(sessions):
        console.print(f"  [red]Invalid choice.[/red]\n")
        return None, None
    s = sessions[n - 1]
    ts = s["saved_at"][:19].replace("T", " ") if s["saved_at"] else "unknown"
    console.print(f"  [green]📂 Loaded session from {ts} ({s['count']} messages)[/green]\n")
    return s["messages"], s["slot"]


# ── Shell command (`!`) ───────────────────────────────

def _run_shell(cmd: str, history: list) -> None:
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    console.print(f"  [dim]$ {cmd}[/dim]")
    console.print(Rule(style="dim"))
    if result.stdout:
        console.print(result.stdout.rstrip(), markup=False, highlight=False)
    if result.stderr:
        console.print(result.stderr.rstrip(), style="red", markup=False, highlight=False)
    console.print(Rule(style="dim"))
    console.print()
    # Inject output into conversation context
    output = (result.stdout + result.stderr).strip()
    if output:
        history.append({
            "role": "system",
            "content": f"Shell output of '{cmd}':\n{output}",
        })


# ── @ file attachment ─────────────────────────────────

def _expand_at_files(message: str, session: PromptSession) -> str | None:
    """
    Expand @filename tokens in message with file contents.
    Returns the expanded message, or None to abort.
    """
    matches = _AT_FILE_RE.findall(message)
    if not matches:
        return message

    for ref in matches:
        # Bare `@` with no name → fuzzy picker
        if not ref:
            continue

        path = os.path.join(os.getcwd(), ref)
        if not os.path.isfile(path):
            console.print(f"  [red]❌ File not found: {ref}[/red]\n")
            return None

        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                content = fh.read()
        except Exception as exc:
            console.print(f"  [red]❌ Could not read {ref}: {exc}[/red]\n")
            return None

        lines = content.splitlines()
        _, ext = os.path.splitext(ref)
        lang = ext.lstrip(".") or "text"
        console.print(f"  [cyan]📎 Attached: {ref} ({len(lines)} lines)[/cyan]")

        replacement = (
            f"[Contents of {os.path.basename(ref)}]\n"
            f"```{lang}\n{content}\n```"
        )
        message = message.replace(f"@{ref}", replacement)

    return message


def _at_file_picker(session: PromptSession) -> str | None:
    """Show top-10 files in cwd for bare `@` prompt."""
    files = [
        f for f in os.listdir(".") if os.path.isfile(f)
        and not f.startswith(".")
        and os.path.splitext(f)[1].lower() in _CODE_EXTENSIONS
    ][:10]
    if not files:
        console.print("  [dim]No matching files in current directory.[/dim]\n")
        return None
    console.print()
    console.print("[cyan]Files to attach:[/cyan]")
    for i, f in enumerate(files, 1):
        console.print(f"  [white]{i}[/white]  {f}")
    console.print()
    try:
        pick = session.prompt(HTML("<ansiwhite>Attach file # (or Enter to cancel): </ansiwhite>")).strip()
    except (KeyboardInterrupt, EOFError):
        return None
    if not pick.isdigit() or not (1 <= int(pick) <= len(files)):
        return None
    return files[int(pick) - 1]


# ── Header / help / model list / history ─────────────


def _print_header(
    slot: int,
    online: bool,
    theme: str = "cyber",
    history: list | None = None,
    permissions: str = "normal",
    **kwargs,
) -> None:
    t = _THEMES.get(theme, _THEMES["cyber"])
    border = t["border"]
    accent = t["accent"]
    mascot_color = t["mascot"]

    info = slot_info(slot)
    model_short = info["model_id"].split("/")[-1]
    if len(model_short) > 30:
        model_short = model_short[:30]

    tokens = _estimate_tokens(history or [])
    bar_markup, pct_str = _context_bar(tokens)
    ctx_line = f"{bar_markup} {pct_str}  ([dim]{tokens}[/dim]/[dim]{_MAX_CONTEXT_TOKENS}[/dim] tokens)"

    perm_label = ""
    if permissions == "readonly":
        perm_label = "  [dim white]\[READONLY][/dim white]"
    elif permissions == "yolo":
        perm_label = "  [bold red]\[YOLO][/bold red]"

    if kwargs.get("agent_mode"):
        perm_label += "  [bold bright_magenta]\[AGENT][/bold bright_magenta]"

    status = "" if online else "  [dim red]offline[/dim red]"

    # Build mascot as a Text object to avoid markup-parsing issues with backslashes
    _mascot_lines = [
        "  \u25c9\u2500\u25c9",
        " /\u2502 \u2502\\",
        "\u25c9 \u2502 \u2502 \u25c9",
        " \\\u2502 \u2502/",
        "  \u25c9\u2500\u25c9",
        "  \u26a1",
    ]
    mascot_text = Text()
    for i, line in enumerate(_mascot_lines):
        mascot_text.append(line, style=mascot_color)
        if i < len(_mascot_lines) - 1:
            mascot_text.append("\n")

    right = (
        f"[bold {accent}]\u26a1 AXON CLI[/bold {accent}]{status}\n"
        f"[white]model:[/white] [bright_white]{model_short}[/bright_white]  [dim]/model to switch[/dim]\n"
        f"[white]slot:[/white]  [bright_white]{slot} \u2014 {info['name']}[/bright_white]{perm_label}\n"
        f"[dim]context:[/dim] {ctx_line}"
    )

    # Combine mascot and right side into a single table-like grid
    from rich.table import Table
    grid = Table.grid(padding=(0, 2))
    grid.add_column(no_wrap=True)
    grid.add_column()
    grid.add_row(mascot_text, Text.from_markup(right))

    console.print()
    console.print(Panel(grid, border_style=border, padding=(0, 1)))
    if not online:
        console.print(f"  [{accent}]⚠  LM Studio is offline. Start it to use Axon.[/{accent}]")
    if tokens / _MAX_CONTEXT_TOKENS >= 0.9:
        console.print("  [red]⚠ Context almost full — /clear to reset[/red]")
    console.print(f"  [dim]Tip: Type /help for commands, /exit to quit[/dim]\n")


def _print_help() -> None:
    console.print()
    console.print("[cyan]Commands:[/cyan]")
    console.print("  [white]/model[/white]             Show available model slots and switch")
    console.print("  [white]/slot <n>[/white]          Switch to slot number directly")
    console.print("  [white]/clear[/white]             Clear conversation history")
    console.print("  [white]/history[/white]           Show last 5 messages")
    console.print("  [white]/save[/white]              Save session to cli/sessions/")
    console.print("  [white]/load[/white]              Load a saved session")
    console.print("  [white]/sessions[/white]          List saved sessions")
    console.print("  [white]/copy[/white]              Copy last AI response to clipboard")
    console.print("  [white]/theme [name][/white]      Switch color theme (cyber/dark/matrix/warm)")
    console.print("  [white]/permissions [mode][/white] Set permission mode (normal/readonly/yolo)")
    console.print("  [white]/agent[/white]             Toggle agent mode (read/write/run actions)")
    console.print("  [white]/mcp[/white]               Manage MCP servers and tools")
    console.print("  [white]/exit[/white]              Exit Axon CLI")
    console.print("  [dim]!<cmd>[/dim]             Run a shell command (e.g. !git status)")
    console.print("  [dim]@<file>[/dim]            Attach a file to your message")
    console.print("  [dim]Ctrl+C[/dim]              Exit cleanly")
    console.print()


def _print_model_list(current_slot: int) -> None:
    console.print()
    console.print("[cyan]Available model slots:[/cyan]")
    for sid, info in sorted(MODEL_SLOTS.items()):
        marker = " [bold cyan]◀[/bold cyan]" if sid == current_slot else ""
        console.print(
            f"  [white]{sid}[/white]  [bright_white]{info['name']:<15}[/bright_white]"
            f"  [dim]{info['model_id']}[/dim]{marker}"
        )
    console.print("\n  [dim]Type /slot <number> to switch[/dim]\n")


def _print_history(history: list) -> None:
    if not history:
        console.print("  [dim]No conversation history yet.[/dim]\n")
        return
    console.print()
    last = history[-10:]  # up to 5 pairs
    for msg in last:
        role = msg["role"]
        content = msg["content"]
        if role == "user":
            console.print(f"  [bold white]› {content}[/bold white]")
        else:
            preview = content[:200] + ("..." if len(content) > 200 else "")
            console.print(f"  [dim]{preview}[/dim]")
    console.print()


# ── Streaming response ────────────────────────────────

def _stream_response(messages: list, slot: int, context_tokens: int = 0) -> str:
    """Buffer streamed tokens, then render with syntax highlighting."""
    full = []
    token_count = 0
    t0 = time.time()

    console.print()
    try:
        with Live(
            Text("▸ Generating\u2026", style="dim"),
            console=console,
            transient=True,
            refresh_per_second=8,
        ) as live:
            for token, _finish in stream_completion(messages, slot=slot):
                full.append(token)
                token_count += 1
                live.update(Text(f"▸ Generating\u2026 {token_count} tokens", style="dim"))
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        console.print(f"  [red]Error: {exc}[/red]")

    elapsed = time.time() - t0
    text = "".join(full)

    if text:
        _render_with_syntax(text)

    ctx_pct = int(min(1.0, context_tokens / _MAX_CONTEXT_TOKENS) * 100)
    console.print(
        f"\n[dim]{'─' * 40}[/dim]\n"
        f"[dim]✓ Done  •  {token_count} tokens  •  {elapsed:.1f}s  •  context: {ctx_pct}%[/dim]\n"
    )
    return text


# ── Main loop ─────────────────────────────────────────

def run_interactive(initial_slot: int = 1) -> None:
    """Main interactive TUI loop."""
    cfg = _load_config()
    theme = cfg["theme"]
    permissions = cfg["permissions"]
    slot = cfg.get("default_slot", initial_slot) if initial_slot == 1 else initial_slot
    online = check_lm_studio()
    history: list[dict] = []
    last_response: str = ""
    shell_history: list[str] = []
    agent_mode: bool = False

    _print_header(slot, online, theme, history, permissions, agent_mode=agent_mode)

    # ── AXON.md auto-load ─────────────────────────────
    _axon_md = os.path.join(os.getcwd(), "AXON.md")
    if os.path.isfile(_axon_md):
        try:
            with open(_axon_md, encoding="utf-8") as _f:
                _axon_contents = _f.read()
            history.append({
                "role": "system",
                "content": f"Project instructions from AXON.md:\n{_axon_contents}",
            })
            console.print("  [dim]📋 AXON.md loaded — project instructions active[/dim]")
        except Exception:
            pass

    # ── MCP server startup ────────────────────────────
    mcp_mgr = MCPManager()
    mcp_errors = mcp_mgr.start()
    if mcp_mgr.has_running_servers():
        running = [n for n, s in mcp_mgr.servers.items() if s.running]
        tool_count = sum(len(s.tools) for s in mcp_mgr.servers.values() if s.running)
        console.print(f"  [dim]🔌 MCP: {', '.join(running)} ({tool_count} tools)[/dim]")
    for _err in mcp_errors:
        console.print(f"  [red]MCP: {_err}[/red]")
    console.print()

    completer = _AxonCompleter(shell_history)
    session = PromptSession(completer=completer, style=_PROMPT_STYLE, complete_while_typing=True)

    while True:
        try:
            user_input = session.prompt(HTML("<ansiwhite><b>› </b></ansiwhite>")).strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Goodbye.[/dim]")
            break

        if not user_input:
            continue

        lower = user_input.lower()

        # ── /exit ──────────────────────────────────
        if lower in ("/exit", "/quit"):
            console.print("[dim]Goodbye.[/dim]")
            break

        # ── /help ──────────────────────────────────
        if lower == "/help":
            _print_help()
            continue

        # ── /model ─────────────────────────────────
        if lower == "/model":
            _print_model_list(slot)
            continue

        # ── /slot <n> ──────────────────────────────
        if lower.startswith("/slot"):
            parts = user_input.split()
            if len(parts) == 2 and parts[1].isdigit():
                n = int(parts[1])
                if n in MODEL_SLOTS:
                    slot = n
                    online = check_lm_studio()
                    console.print(
                        f"  [cyan]Switched to Slot {slot} — "
                        f"{slot_info(slot)['name']} "
                        f"({slot_info(slot)['model_id']})[/cyan]\n"
                    )
                else:
                    console.print(f"  [red]Invalid slot {n}. Use 1-{max(MODEL_SLOTS)}.[/red]\n")
            else:
                console.print("  [dim]Usage: /slot <number>[/dim]\n")
            continue

        # ── /clear ─────────────────────────────────
        if lower == "/clear":
            history.clear()
            last_response = ""
            console.print("  [dim]Conversation history cleared.[/dim]\n")
            continue

        # ── /history ───────────────────────────────
        if lower == "/history":
            _print_history(history)
            continue

        # ── /save ──────────────────────────────────
        if lower == "/save":
            if not history:
                console.print("  [dim]Nothing to save yet.[/dim]\n")
            else:
                _save_session(history, slot)
            continue

        # ── /sessions ──────────────────────────────
        if lower == "/sessions":
            _print_sessions()
            continue

        # ── /load ──────────────────────────────────
        if lower == "/load":
            loaded_msgs, loaded_slot = _load_session_interactive(session)
            if loaded_msgs is not None:
                history = loaded_msgs
                slot = loaded_slot
            continue

        # ── /copy ──────────────────────────────────
        if lower == "/copy":
            if not last_response:
                console.print("  [dim]No response to copy yet.[/dim]\n")
            else:
                try:
                    pyperclip.copy(last_response)
                    words = len(last_response.split())
                    console.print(f"  [green]📋 Copied to clipboard ({words} tokens)[/green]\n")
                except Exception as exc:
                    console.print(f"  [red]Clipboard error: {exc}[/red]\n")
            continue

        # ── /agent ─────────────────────────────────
        if lower == "/agent":
            agent_mode = not agent_mode
            label = "[bold bright_magenta]ON[/bold bright_magenta]" if agent_mode else "[dim]OFF[/dim]"
            console.print(f"  [cyan]Agent mode: {label}[/cyan]\n")
            continue
        # ── /mcp ──────────────────────────────────────
        if lower.startswith("/mcp"):
            parts = user_input.split()
            if len(parts) == 1:
                # /mcp — show status
                if not mcp_mgr.servers:
                    console.print("  [dim]No MCP servers configured. Edit cli/mcp_config.json or use /mcp add <name> <command>[/dim]\n")
                else:
                    console.print()
                    console.print("[cyan]MCP Servers:[/cyan]")
                    for sname, srv in mcp_mgr.servers.items():
                        if srv.running:
                            status = f"[green]running[/green]  [dim]{len(srv.tools)} tools[/dim]"
                        elif srv.enabled:
                            status = "[yellow]enabled (not connected)[/yellow]"
                        else:
                            status = "[dim]disabled[/dim]"
                        console.print(f"  [white]{sname:<15}[/white] {status}")
                    console.print("  [dim]/mcp enable|disable|show <name>[/dim]\n")
            elif parts[1] == "add" and len(parts) >= 4:
                sname = parts[2]
                cmd = parts[3]
                cmd_args = parts[4:] if len(parts) > 4 else []
                mcp_mgr.add_server(sname, cmd, cmd_args)
                console.print(f"  [green]Added MCP server '{sname}' (disabled). Use /mcp enable {sname}[/green]\n")
            elif parts[1] == "enable" and len(parts) == 3:
                sname = parts[2]
                if sname not in mcp_mgr.servers:
                    console.print(f"  [red]Unknown server '{sname}'[/red]\n")
                elif mcp_mgr.servers[sname].running:
                    console.print(f"  [dim]{sname} is already running[/dim]\n")
                else:
                    try:
                        console.print(f"  [dim]Connecting to {sname}...[/dim]")
                        mcp_mgr.connect_server(sname)
                        srv = mcp_mgr.servers[sname]
                        console.print(f"  [green]✓ {sname} connected — {len(srv.tools)} tools available[/green]\n")
                    except Exception as exc:
                        console.print(f"  [red]✗ Failed to connect {sname}: {exc}[/red]\n")
            elif parts[1] == "disable" and len(parts) == 3:
                sname = parts[2]
                if sname not in mcp_mgr.servers:
                    console.print(f"  [red]Unknown server '{sname}'[/red]\n")
                elif not mcp_mgr.servers[sname].running:
                    console.print(f"  [dim]{sname} is not running[/dim]\n")
                else:
                    try:
                        mcp_mgr.disconnect_server(sname)
                        console.print(f"  [dim]Disconnected {sname}[/dim]\n")
                    except Exception as exc:
                        console.print(f"  [red]Error disconnecting {sname}: {exc}[/red]\n")
            elif parts[1] == "show" and len(parts) == 3:
                sname = parts[2]
                if sname not in mcp_mgr.servers:
                    console.print(f"  [red]Unknown server '{sname}'[/red]\n")
                elif not mcp_mgr.servers[sname].running:
                    console.print(f"  [dim]{sname} is not running. Use /mcp enable {sname}[/dim]\n")
                else:
                    srv = mcp_mgr.servers[sname]
                    console.print()
                    console.print(f"[cyan]Tools from {sname}:[/cyan]")
                    for tname, tdesc, tschema in srv.tools:
                        params = tschema.get("properties", {})
                        param_str = ", ".join(params.keys()) if params else ""
                        console.print(f"  [white]{tname}({param_str})[/white]")
                        if tdesc:
                            console.print(f"    [dim]{tdesc}[/dim]")
                    console.print()
            else:
                console.print("  [dim]Usage: /mcp, /mcp add <name> <cmd>, /mcp enable|disable <name>, /mcp show <name>[/dim]\n")
            continue
        # ── /theme ────────────────────────────────
        if lower.startswith("/theme"):
            parts = user_input.split(maxsplit=1)
            if len(parts) == 1:
                from rich.table import Table as _T
                tbl = _T(box=None, padding=(0, 2))
                tbl.add_column("Name", style="white")
                tbl.add_column("Description")
                for name, td in _THEMES.items():
                    marker = " ◀" if name == theme else ""
                    tbl.add_row(f"[{td['accent']}]{name}[/{td['accent']}]{marker}", td["desc"])
                console.print()
                console.print("[cyan]Available themes:[/cyan]")
                console.print(tbl)
                console.print("  [dim]Usage: /theme <name>[/dim]\n")
            else:
                name = parts[1].lower()
                if name not in _THEMES:
                    console.print(f"  [red]Unknown theme '{name}'. Options: {', '.join(_THEMES)}[/red]\n")
                else:
                    theme = name
                    cfg["theme"] = theme
                    _save_config(cfg)
                    t = _THEMES[theme]
                    console.print(f"  [{t['accent']}]Theme set to '{theme}' — {t['desc']}[/{t['accent']}]\n")
                    _print_header(slot, online, theme, history, permissions)
            continue

        # ── /permissions ──────────────────────────
        if lower.startswith("/permissions"):
            parts = user_input.split(maxsplit=1)
            _MODES = {
                "normal":   "Default — all commands allowed",
                "readonly": "Shell commands (`!`) blocked",
                "yolo":     "No confirmations, all commands allowed",
            }
            if len(parts) == 1:
                console.print()
                console.print("[cyan]Permission modes:[/cyan]")
                for mode, desc in _MODES.items():
                    marker = " ◀" if mode == permissions else ""
                    console.print(f"  [white]{mode:<10}[/white] {desc}{marker}")
                console.print(f"  [dim]Usage: /permissions <mode>[/dim]\n")
            else:
                mode = parts[1].lower()
                if mode not in _MODES:
                    console.print(f"  [red]Unknown mode '{mode}'. Options: normal, readonly, yolo[/red]\n")
                else:
                    permissions = mode
                    cfg["permissions"] = permissions
                    _save_config(cfg)
                    console.print(f"  [cyan]Permissions set to '{permissions}'[/cyan]\n")
                    _print_header(slot, online, theme, history, permissions)
            continue

        # ── Unknown /command ───────────────────────
        if lower.startswith("/"):
            console.print(f"  [dim]Unknown command: {user_input}. Type /help[/dim]\n")
            continue

        # ── ! shell command ────────────────────────
        if user_input.startswith("!"):
            if permissions == "readonly":
                console.print("  [red]🔒 Shell commands blocked in readonly mode[/red]\n")
                continue
            cmd = user_input[1:].strip()
            shell_history.append(cmd)
            if len(shell_history) > 50:
                shell_history.pop(0)
            _run_shell(cmd, history)
            continue

        # ── @ file bare picker ──────────────────────
        if user_input.strip() == "@":
            fname = _at_file_picker(session)
            if not fname:
                continue
            user_input = f"@{fname}"

        # ── @ file expansion ──────────────────────
        if "@" in user_input:
            expanded = _expand_at_files(user_input, session)
            if expanded is None:
                continue
            user_input = expanded

        # ── Chat ──────────────────────────────────
        if not online:
            online = check_lm_studio()
            if not online:
                console.print("  [yellow]⚠  LM Studio is offline. Cannot send.[/yellow]\n")
                continue

        # ── Inject agent system prompt if active ──
        if agent_mode:
            # Ensure agent system prompt is present as first message (refresh each turn for current cwd)
            agent_prompt = get_agent_system_prompt()
            if not history or not history[0].get("content", "").startswith("You are an AI agent"):
                history.insert(0, {"role": "system", "content": agent_prompt})
            else:
                history[0]["content"] = agent_prompt

        history.append({"role": "user", "content": user_input})

        # Build messages — inject MCP tools prompt if servers are running
        messages = list(history)
        mcp_tools_prompt = mcp_mgr.get_tools_prompt()
        if mcp_tools_prompt:
            messages.insert(0, {"role": "system", "content": mcp_tools_prompt})

        response_text = _stream_response(messages, slot, _estimate_tokens(history))

        if response_text:
            last_response = response_text
            history.append({"role": "assistant", "content": response_text})

            # ── Process agent actions ──────────────
            if agent_mode:
                actions = parse_actions(response_text)
                for action in actions:
                    atype = action["type"]

                    # Permissions check
                    if permissions == "readonly" and atype in ("write_file", "run_command"):
                        console.print(f"  [red]🔒 {atype} blocked in readonly mode[/red]\n")
                        history.append({
                            "role": "system",
                            "content": f"Action {atype} was DENIED (readonly mode).",
                        })
                        continue

                    # YOLO mode: auto-approve
                    if permissions == "yolo":
                        choice = "a"
                    else:
                        # Show approval prompt
                        print_action_prompt(action)
                        try:
                            choice = session.prompt("").strip().lower() or "a"
                        except (KeyboardInterrupt, EOFError):
                            choice = "d"

                    if choice == "d":
                        console.print("  [dim]⏭ Action denied[/dim]\n")
                        history.append({
                            "role": "system",
                            "content": f"Action {atype} was DENIED by the user.",
                        })
                        continue

                    if choice == "e":
                        # Inline edit
                        try:
                            if atype == "run_command":
                                edited = session.prompt(
                                    HTML("<ansiwhite>  Edit command: </ansiwhite>"),
                                    default=action.get("command", ""),
                                ).strip()
                                if not edited:
                                    console.print("  [dim]⏭ Action cancelled[/dim]\n")
                                    continue
                                action["command"] = edited
                            else:
                                edited = session.prompt(
                                    HTML("<ansiwhite>  Edit path: </ansiwhite>"),
                                    default=action.get("path", ""),
                                ).strip()
                                if not edited:
                                    console.print("  [dim]⏭ Action cancelled[/dim]\n")
                                    continue
                                action["path"] = edited
                        except (KeyboardInterrupt, EOFError):
                            console.print("  [dim]⏭ Action cancelled[/dim]\n")
                            continue

                    # Execute
                    if atype == "read_file":
                        result = execute_read_file(action["path"])
                        console.print(f"  [cyan]📄 Read: {action['path']}[/cyan]")
                        history.append({
                            "role": "system",
                            "content": f"Contents of {action['path']}:\n{result}",
                        })
                    elif atype == "write_file":
                        result = execute_write_file(action["path"], action.get("content", ""))
                        console.print(f"  [green]✅ {result}[/green]")
                        history.append({
                            "role": "system",
                            "content": f"File write result: {result}",
                        })
                    elif atype == "run_command":
                        console.print(f"  [bright_magenta]▶ Running: {action['command']}[/bright_magenta]")
                        result = execute_run_command(action["command"])
                        console.print(Panel(result, border_style="dim", padding=(0, 1)))
                        history.append({
                            "role": "system",
                            "content": f"Command output of '{action['command']}':\n{result}",
                        })
                    console.print()

            # ── Process MCP tool calls ─────────────
            if mcp_mgr.has_running_servers():
                tool_calls = MCPManager.parse_tool_calls(response_text)
                for tc in tool_calls:
                    tc_server = tc["server"]
                    tc_tool = tc["tool"]
                    tc_args = tc["args"]

                    console.print()
                    console.print(f"  [bold bright_magenta]⚡ MCP tool call: {tc_server}/{tc_tool}[/bold bright_magenta]")
                    console.print(f"     args: [dim]{json.dumps(tc_args)}[/dim]")
                    console.print()
                    console.print("  [white]\\[A] Allow[/white]   [dim]\\[D] Deny[/dim]   ?", end="  ")

                    if permissions == "yolo":
                        choice = "a"
                    else:
                        try:
                            choice = session.prompt("").strip().lower() or "a"
                        except (KeyboardInterrupt, EOFError):
                            choice = "d"

                    if choice == "d":
                        console.print("  [dim]⏭ Tool call denied[/dim]\n")
                        history.append({
                            "role": "system",
                            "content": f"MCP tool call {tc_server}/{tc_tool} was DENIED by the user.",
                        })
                        continue

                    console.print(f"  [dim]⏳ Calling {tc_server}/{tc_tool}...[/dim]")
                    tc_result = mcp_mgr.call_tool(tc_server, tc_tool, tc_args)
                    console.print(Panel(tc_result, title=f"{tc_server}/{tc_tool}", border_style="dim", padding=(0, 1)))
                    history.append({
                        "role": "system",
                        "content": f"MCP tool result from {tc_server}/{tc_tool}:\n{tc_result}",
                    })
                    console.print()

    # ── Cleanup ───────────────────────────────────
    mcp_mgr.shutdown()
