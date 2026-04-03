"""
agent_executor.py — Execute agent actions (read/write/run) for Axon CLI.
"""

import os
import re
import subprocess

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax

console = Console()

# ── Action parsing ────────────────────────────────────

_ACTION_RE = re.compile(
    r'<axon_action\s+'
    r'type="(?P<type>read_file|write_file|run_command)"\s+'
    r'(?:path="(?P<path>[^"]*)"\s*)?'
    r'(?:command="(?P<command>[^"]*)"\s*)?'
    r'(?:content="(?P<content>[^"]*)"\s*)?'
    r'/>'
)

# More lenient: content can span multiple lines via a separate pattern
_ACTION_WRITE_RE = re.compile(
    r'<axon_action\s+type="write_file"\s+'
    r'path="(?P<path>[^"]*)"\s+'
    r'content="(?P<content>.*?)"\s*/\s*>',
    re.DOTALL,
)


def parse_actions(text: str) -> list[dict]:
    """Extract all <axon_action .../> blocks from AI response text."""
    actions = []

    # First pass: multi-line write_file actions
    write_paths_found = set()
    for m in _ACTION_WRITE_RE.finditer(text):
        path = m.group("path")
        content = m.group("content")
        # Unescape common XML entities
        content = content.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
        actions.append({
            "type": "write_file",
            "path": path,
            "content": content,
            "raw": m.group(0),
        })
        write_paths_found.add(path)

    # Second pass: read_file and run_command (single-line)
    for m in _ACTION_RE.finditer(text):
        atype = m.group("type")
        if atype == "write_file":
            # Skip if already handled by multi-line regex
            if m.group("path") in write_paths_found:
                continue
            actions.append({
                "type": "write_file",
                "path": m.group("path") or "",
                "content": (m.group("content") or "").replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&"),
                "raw": m.group(0),
            })
        elif atype == "read_file":
            actions.append({
                "type": "read_file",
                "path": m.group("path") or "",
                "raw": m.group(0),
            })
        elif atype == "run_command":
            actions.append({
                "type": "run_command",
                "command": m.group("command") or "",
                "raw": m.group(0),
            })

    return actions


# ── Action execution ──────────────────────────────────

def execute_read_file(path: str) -> str:
    """Read a file and return its contents or an error string."""
    resolved = os.path.abspath(path)
    if not os.path.isfile(resolved):
        return f"Error: file not found — {path}"
    try:
        with open(resolved, encoding="utf-8", errors="replace") as f:
            content = f.read()
        return content
    except Exception as exc:
        return f"Error reading {path}: {exc}"


def execute_write_file(path: str, content: str) -> str:
    """Write content to a file. Creates directories as needed. Returns status."""
    resolved = os.path.abspath(path)
    try:
        os.makedirs(os.path.dirname(resolved), exist_ok=True)
        with open(resolved, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
        lines = content.count("\n") + 1
        return f"Written: {path} ({lines} lines)"
    except Exception as exc:
        return f"Error writing {path}: {exc}"


def execute_run_command(command: str) -> str:
    """Run a shell command and return combined stdout+stderr."""
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=30,
        )
        output = (result.stdout + result.stderr).strip()
        if not output:
            return f"(command completed with exit code {result.returncode})"
        return output
    except subprocess.TimeoutExpired:
        return "Error: command timed out after 30s"
    except Exception as exc:
        return f"Error running command: {exc}"


# ── Display helpers ───────────────────────────────────

_ACTION_LABELS = {
    "read_file": ("READ FILE", "cyan"),
    "write_file": ("WRITE FILE", "yellow"),
    "run_command": ("RUN COMMAND", "bright_magenta"),
}


def print_action_prompt(action: dict) -> None:
    """Display the approval prompt for an action."""
    atype = action["type"]
    label, color = _ACTION_LABELS.get(atype, (atype.upper(), "white"))

    console.print()
    console.print(f"  [bold {color}]⚡ Agent wants to: {label}[/bold {color}]")

    if atype == "read_file":
        console.print(f"     Path: [bright_white]{action['path']}[/bright_white]")
    elif atype == "write_file":
        console.print(f"     Path: [bright_white]{action['path']}[/bright_white]")
        preview = action.get("content", "")
        preview_lines = preview.splitlines()
        if len(preview_lines) > 8:
            preview = "\n".join(preview_lines[:8]) + f"\n... ({len(preview_lines)} lines total)"
        console.print(Panel(preview, title="content preview", border_style="dim", padding=(0, 1)))
    elif atype == "run_command":
        console.print(f"     Command: [bright_white]{action['command']}[/bright_white]")

    console.print()
    console.print("  [white]\\[A] Allow[/white]   [dim]\\[D] Deny[/dim]   [white]\\[E] Edit[/white]   ?", end="  ")


def get_agent_system_prompt() -> str:
    """Build a dynamic agent system prompt with current OS and filesystem context."""
    import platform

    cwd = os.getcwd()
    home = os.path.expanduser("~")
    username = os.path.basename(home)
    os_name = platform.system()  # "Windows", "Linux", "Darwin"
    desktop = os.path.join(home, "Desktop")
    downloads = os.path.join(home, "Downloads")
    documents = os.path.join(home, "Documents")

    context_lines = [
        f"OS: {os_name}",
        f"Username: {username}",
        f"Home directory: {home}",
        f"Current working directory: {cwd}",
    ]
    if os.path.isdir(desktop):
        context_lines.append(f"Desktop: {desktop}")
    if os.path.isdir(downloads):
        context_lines.append(f"Downloads: {downloads}")
    if os.path.isdir(documents):
        context_lines.append(f"Documents: {documents}")

    context = "\n".join(context_lines)

    return (
        "You are an AI agent with the ability to read files, write files, and run commands.\n"
        "When you need to perform an action, output it using this exact XML format on its own line:\n"
        "\n"
        '<axon_action type="read_file" path="path/to/file" />\n'
        '<axon_action type="write_file" path="path/to/file" content="full file content here" />\n'
        '<axon_action type="run_command" command="the command to run" />\n'
        "\n"
        "IMPORTANT: Always use the real absolute paths from the environment below. "
        "Never guess or invent paths like /Users/username.\n"
        "Only use actions when necessary. Always explain what you are doing before the action tag.\n"
        "\n"
        f"Current environment:\n{context}"
    )


# Keep for backwards compatibility
AGENT_SYSTEM_PROMPT = get_agent_system_prompt()
