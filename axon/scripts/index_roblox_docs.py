"""
index_roblox_docs.py — One-time script to index a local copy of the
Roblox Creator Documentation into Axon's roblox_docs ChromaDB collection.

Usage:
    python scripts/index_roblox_docs.py --docs-path "C:/path/to/roblox-docs"

Download the docs from: https://github.com/Roblox/creator-docs
or export them as HTML/Markdown from the Roblox Creator Hub.
"""

import argparse
import os
import sys

# Make sure the axon package root is in the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.rag import index_roblox_docs


def main():
    parser = argparse.ArgumentParser(
        description="Index Roblox Creator Documentation into Axon's vector store."
    )
    parser.add_argument(
        "--docs-path",
        required=True,
        help="Path to the downloaded Roblox Creator Docs folder",
    )
    args = parser.parse_args()

    docs_path = os.path.abspath(args.docs_path)
    if not os.path.isdir(docs_path):
        print("Error: folder does not exist: %s" % docs_path)
        sys.exit(1)

    print("Indexing Roblox Creator Docs from: %s" % docs_path)
    print("This may take a few minutes on first run (embedding model loads)...")

    def on_progress(count, fname):
        print("  [%d] %s" % (count, fname))

    result = index_roblox_docs(docs_path, progress_callback=on_progress)

    if "error" in result:
        print("Error: %s" % result["error"])
        sys.exit(1)

    print("\nDone.")
    print("  Files indexed : %d" % result["files_indexed"])
    print("  Total chunks  : %d" % result["total_chunks"])
    print("\nRoblox docs are now available to the Roblox Agent (Slot 7).")


if __name__ == "__main__":
    main()
