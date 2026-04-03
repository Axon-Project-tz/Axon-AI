"""
one_shot.py — One-shot mode for Axon CLI.

Usage:  axon -m "prompt" [--slot N] [--no-stream] [--json]
"""

import json
import re
import sys
import time

from rich.console import Console
from rich.live import Live
from rich.syntax import Syntax
from rich.text import Text

from cli.lm_client import (
    blocking_completion,
    check_lm_studio,
    slot_info,
    stream_completion,
)

console = Console()

_CODE_BLOCK_RE = re.compile(r'```(\w*)\n?(.*?)```', re.DOTALL)


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


def run_one_shot(
    message: str,
    slot: int = 1,
    stream: bool = True,
    raw_json: bool = False,
) -> None:
    """Handle a single prompt, print the response, and exit."""
    if not check_lm_studio():
        console.print("[yellow]⚠  LM Studio is not running. Start it first.[/yellow]")
        sys.exit(1)

    info = slot_info(slot)
    messages = [{"role": "user", "content": message}]

    if raw_json:
        text = blocking_completion(messages, slot=slot)
        print(json.dumps({"slot": slot, "model": info["model_id"], "response": text}))
        return

    console.print(
        f"\n[bold cyan]⚡ Axon[/bold cyan] "
        f"[dim]\\[Slot {slot} — {info['name']}][/dim]\n"
    )

    t0 = time.time()
    token_count = 0

    if stream:
        full_tokens: list[str] = []
        try:
            with Live(
                Text("▸ Generating\u2026", style="dim"),
                console=console,
                transient=True,
                refresh_per_second=8,
            ) as live:
                for token, _finish in stream_completion(messages, slot=slot):
                    full_tokens.append(token)
                    token_count += 1
                    live.update(Text(f"▸ Generating\u2026 {token_count} tokens", style="dim"))
        except KeyboardInterrupt:
            pass
        except Exception as exc:
            console.print(f"\n[red]Error: {exc}[/red]")
            sys.exit(1)
        text = "".join(full_tokens)
        _render_with_syntax(text)
    else:
        try:
            text = blocking_completion(messages, slot=slot)
        except Exception as exc:
            console.print(f"[red]Error: {exc}[/red]")
            sys.exit(1)
        token_count = len(text.split())
        _render_with_syntax(text)

    elapsed = time.time() - t0
    console.print(
        f"\n[dim]{'─' * 40}[/dim]\n"
        f"[dim]✓ Done  •  {token_count} tokens  •  {elapsed:.1f}s[/dim]\n"
    )
