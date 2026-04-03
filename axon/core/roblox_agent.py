"""
roblox_agent.py — Roblox game development agent for Axon (Slot 7).
Reads game.json, queries Roblox docs RAG, builds enriched context,
streams the LLM response, and writes Luau files directly to disk.
"""

import json
import os
import re

from core.llm import stream_chat
from core.roblox_manifest import get_manifest, save_manifest

CIRCUIT_BREAKER_LIMIT = 3

# Module-level cache: one agent instance per project_root
_agents: dict = {}


def get_or_create_agent(project_root: str) -> "RobloxAgent":
    """Return a cached RobloxAgent for the given project root."""
    if project_root not in _agents:
        _agents[project_root] = RobloxAgent(project_root)
    return _agents[project_root]


class RobloxAgent:
    def __init__(self, project_root: str):
        self.project_root = project_root
        self.failure_count = 0

    def build_context(self, user_message: str) -> str:
        """Inject game.json state + existing scripts + relevant RAG docs into the user message."""
        manifest = get_manifest(self.project_root)
        manifest_str = json.dumps(manifest, indent=2)

        # Scan project folder for existing Luau scripts
        existing_files_str = "No project folder set."
        if self.project_root and os.path.isdir(self.project_root):
            lua_files = []
            for dirpath, dirnames, filenames in os.walk(self.project_root):
                dirnames[:] = [d for d in dirnames if not d.startswith('.')]
                for fname in filenames:
                    if fname.endswith(('.lua', '.luau')):
                        rel = os.path.relpath(
                            os.path.join(dirpath, fname), self.project_root
                        ).replace('\\', '/')
                        lua_files.append(rel)
            existing_files_str = (
                "\n".join(sorted(lua_files)) if lua_files
                else "No .lua files yet — project is empty."
            )

        rag_context = "No Roblox docs indexed yet."
        try:
            from core.rag import query_roblox_docs
            results = query_roblox_docs(user_message, n_results=5)
            if results:
                rag_context = "\n\n---\n".join(results)
        except Exception:
            pass

        return (
            "=== CURRENT PROJECT STATE (game.json) ===\n"
            + manifest_str
            + "\n\n=== EXISTING SCRIPTS IN PROJECT ===\n"
            + existing_files_str
            + "\n\n=== RELEVANT ROBLOX DOCUMENTATION ===\n"
            + rag_context
            + "\n\n=== USER REQUEST ===\n"
            + user_message
        )

    def write_file(self, relative_path: str, content: str):
        """Write a Luau script to the project folder."""
        if not self.project_root:
            return
        full_path = os.path.join(self.project_root, relative_path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)

    def parse_and_write_output(self, response: str):
        """
        Parse 📄 file blocks and the 📋 game.json block from the LLM response.
        Strips <think> blocks first so reasoning text doesn't confuse the parser.
        Handles paths with or without [] or `` wrappers.
        Returns (written_paths: list[str], errors: list[str]).
        """
        # Strip <think>...</think> reasoning block — only parse the answer part
        text = re.sub(r'<think>.*?</think>', '', response, flags=re.DOTALL).strip()
        if not text:
            text = response  # fallback: use full text if nothing remains

        # Match 📄 blocks:
        #   📄 [optional-bracket-or-backtick] path [optional-bracket-or-backtick]
        #   (optional blank lines)
        #   ```[optional language — case insensitive]
        #   code
        #   ```
        file_pattern = re.compile(
            r'📄[ \t]*[\[`]?([^`\]\r\n]+?)[`\]]?[ \t]*\n+```[a-zA-Z]*\n(.*?)```',
            re.DOTALL
        )
        # Match the 📋 game.json block (e.g. "📋 game.json (updated)")
        manifest_pattern = re.compile(
            r'📋[^\r\n]*\n+```[a-zA-Z]*\n(.*?)```',
            re.DOTALL
        )

        written = []
        errors = []

        import logging as _log
        _log.getLogger('roblox_agent').debug(
            '[RobloxAgent] parse answer (%d chars), found %d 📄 blocks',
            len(text), len(file_pattern.findall(text))
        )

        for rel_path, code in file_pattern.findall(text):
            rel_path = rel_path.strip()
            code = code.strip()
            if rel_path.lower() == "game.json":
                try:
                    save_manifest(self.project_root, json.loads(code))
                    written.append("game.json")
                except json.JSONDecodeError as e:
                    errors.append(f"game.json parse error: {e}")
                except Exception as e:
                    errors.append(f"game.json write error: {e}")
            else:
                try:
                    self.write_file(rel_path, code)
                    written.append(rel_path)
                except Exception as e:
                    errors.append(f"{rel_path}: {e}")

        # Handle 📋 game.json if not already written via a 📄 block
        if "game.json" not in written:
            m = manifest_pattern.search(text)
            if m:
                try:
                    save_manifest(self.project_root, json.loads(m.group(1).strip()))
                    written.append("game.json")
                except json.JSONDecodeError as e:
                    errors.append(f"game.json parse error: {e}")
                except Exception as e:
                    errors.append(f"game.json write error: {e}")

        return written, errors

    def run(self, user_message: str, prior_history: list, model_id: str,
            system_prompt: str, base_url: str = None,
            temperature: float = 0.55, top_p: float = 0.95):
        """
        Main entry point. Builds context, streams LLM response, writes files.
        Yields SSE-formatted strings (same format as stream_chat).
        """
        if self.failure_count >= CIRCUIT_BREAKER_LIMIT:
            yield "data: " + json.dumps({
                "token": (
                    "\u26a0\ufe0f Circuit breaker triggered \u2014 "
                    "%d consecutive failures. Please clarify what you need."
                ) % self.failure_count
            }) + "\n\n"
            yield "data: " + json.dumps({"done": True}) + "\n\n"
            return

        context = self.build_context(user_message)
        messages = prior_history + [{"role": "user", "content": context}]
        collected = []

        try:
            for chunk in stream_chat(messages, model_id, system_prompt, base_url=base_url,
                                      temperature=temperature, top_p=top_p):
                try:
                    payload = chunk.replace("data: ", "").strip()
                    parsed = json.loads(payload)

                    if "token" in parsed:
                        collected.append(parsed["token"])
                        yield chunk

                    elif "done" in parsed:
                        # Write files before finishing
                        full_text = "".join(collected)
                        if full_text and self.project_root:
                            written, errors = self.parse_and_write_output(full_text)
                            if written:
                                notice = "\n\n\u2705 Written to disk:\n" + "\n".join(
                                    "- " + f for f in written
                                )
                                yield "data: " + json.dumps({"token": notice}) + "\n\n"
                            if errors:
                                err_notice = "\n\n\u26a0\ufe0f Write errors:\n" + "\n".join(
                                    "- " + e for e in errors
                                )
                                yield "data: " + json.dumps({"token": err_notice}) + "\n\n"
                        self.failure_count = 0
                        yield chunk
                        return

                    else:
                        # Error or unknown payload — pass through
                        yield chunk

                except (json.JSONDecodeError, Exception):
                    yield chunk

        except Exception as e:
            self.failure_count += 1
            yield "data: " + json.dumps({
                "token": "\n\n\u274c Roblox Agent error (%d/%d): %s" % (
                    self.failure_count, CIRCUIT_BREAKER_LIMIT, str(e)
                )
            }) + "\n\n"
            yield "data: " + json.dumps({"done": True}) + "\n\n"
