"""
axon_cli.py — Main entry point for the Axon CLI tool.

Interactive: axon
One-shot:    axon -m "your prompt"
"""

import argparse
import os
import sys

# Ensure the project root is on sys.path so `cli.*` imports work
# regardless of where the script is invoked from.
_CLI_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_CLI_DIR)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="axon",
        description="⚡ Axon CLI — local AI assistant powered by LM Studio",
    )
    parser.add_argument(
        "-m", "--message",
        type=str,
        default=None,
        help="One-shot prompt (prints response and exits)",
    )
    parser.add_argument(
        "--slot",
        type=int,
        default=1,
        help="Model slot to use (default: 1 — Chat)",
    )
    parser.add_argument(
        "--no-stream",
        action="store_true",
        default=False,
        help="Wait for full response instead of streaming",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Output raw JSON (for piping)",
    )

    args = parser.parse_args()

    if args.message:
        from cli.one_shot import run_one_shot

        run_one_shot(
            message=args.message,
            slot=args.slot,
            stream=not args.no_stream,
            raw_json=args.json,
        )
    else:
        from cli.tui import run_interactive

        run_interactive(initial_slot=args.slot)


if __name__ == "__main__":
    main()
