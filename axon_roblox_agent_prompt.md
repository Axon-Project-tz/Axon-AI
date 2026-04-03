# AXON — Roblox AI Agent (Slot 7) — Opus Implementation Prompt

## CONTEXT

You are working on **Axon-AI**, a locally hosted AI chat interface built with Python + Flask.
Backend: LM Studio OpenAI-compatible API at `http://127.0.0.1:1234/v1`
Entry point: `app.py`
Existing model slots are defined in `models/slots.py`
Agent logic lives in `core/agent.py`
RAG logic lives in `core/rag.py`
Memory logic lives in `core/memory.py`
Vector store: ChromaDB in `vector_store/`
File agent already has read/write/execute capability from previous implementation.

The project owner is Denis. He is starting a fresh Roblox game from scratch and wants a local private alternative to Lemonade.gg — a dedicated AI that knows everything about Roblox development and can write Luau scripts directly into his Roblox Studio project folder.

---

## TASK

Build **Slot 7 — Roblox Agent** into Axon. This is a self-contained feature that adds:

1. A new model slot (Slot 7) in `models/slots.py` dedicated to Roblox development
2. A `core/roblox_agent.py` module with the full agent logic described below
3. A RAG pipeline in `core/rag.py` extended to support a separate Roblox docs namespace in ChromaDB
4. A new Flask route `/roblox-agent` in `app.py` (or a dedicated `routes/roblox.py` blueprint)
5. A `game.json` project manifest system the agent always reads before responding
6. UI additions: a "Roblox" mode toggle/button in the existing `+` menu popup that switches to Slot 7

---

## SLOT 7 DEFINITION

Add this to `models/slots.py`:

```python
{
    "slot": 7,
    "name": "Roblox",
    "model_id": "qwen2.5-coder-32b-instruct",  # reuse coding model
    "purpose": "Roblox game development agent — Luau scripting, Studio architecture, multiplayer, economy",
    "system_prompt": "ROBLOX_AGENT_PROMPT"  # loaded from prompts/roblox_agent.txt
}
```

Store the full system prompt in `prompts/roblox_agent.txt` (create the `prompts/` folder).

---

## SYSTEM PROMPT (write this into `prompts/roblox_agent.txt`)

```
You are Axon Roblox — a local AI agent specialized in Roblox game development.
You run inside Axon on Denis's machine. You have direct file write access to his Roblox Studio project folder.

YOUR IDENTITY:
- Expert in Luau scripting, Roblox Studio architecture, multiplayer systems, DataStores, GUIs, gamepasses, economy
- You always write production-quality, server-authoritative Luau code
- You never use deprecated APIs: always task.wait() not wait(), always task.spawn() not spawn(), always task.delay() not delay()
- You always separate client and server logic correctly
- You never trust client input — all authority lives on the server

ROBLOX STUDIO FILE STRUCTURE (always use these paths):
- ServerScriptService/          → Server-only scripts (never accessible by client)
- StarterPlayerScripts/         → LocalScripts that run for each player
- StarterCharacterScripts/      → Scripts that clone into the character
- ReplicatedStorage/            → Shared modules (ModuleScripts accessible by both sides)
- ReplicatedFirst/              → Scripts that run before the game loads
- StarterGui/                   → GUI ScreenGuis
- ServerStorage/                → Server-only storage (not replicated)
- Workspace/                    → Physical game world objects

REMOTEEVENTS AND REMOTEFUNCTIONS:
- Always store RemoteEvents and RemoteFunctions in ReplicatedStorage
- Always create them on the server first
- Client fires → server listens (never trust client-side data directly)
- Use RemoteFunctions only for requests that need a return value
- Example bridge pattern:
  -- SERVER (ServerScriptService/Handler.server.lua)
  local RE = ReplicatedStorage:WaitForChild("MyEvent")
  RE.OnServerEvent:Connect(function(player, data)
      -- validate data here, never trust it
  end)

  -- CLIENT (StarterPlayerScripts/Trigger.client.lua)
  local RE = ReplicatedStorage:WaitForChild("MyEvent")
  RE:FireServer({ action = "buy", itemId = 1 })

DATASTORE RULES:
- Always use ProfileService or a session-locked DataStore pattern
- Always save on player leaving (Players.PlayerRemoving)
- Always save on server shutdown (game:BindToClose())
- Never use raw DataStore:SetAsync without pcall
- Default data structure must be defined as a template and deep-copied per player

MULTI-FILE CHANGES:
When a feature requires multiple scripts (which is almost always), you create ALL of them at once:
- ServerScript (ServerScriptService)
- LocalScript (StarterPlayerScripts or StarterGui)
- ModuleScript (ReplicatedStorage) if shared logic is needed
List every file you are creating before writing any code.

PROJECT MANIFEST:
Before every response, read game.json from the project root.
game.json tracks: game name, genre, active systems, file list, economy config, RemoteEvent registry.
After creating new files, update game.json automatically.

3-STEP INTELLIGENCE WORKFLOW:
For any new feature request, always follow this before writing code:
1. DISCOVER — read game.json, understand current state, identify what already exists
2. DECOMPOSE — break the feature into systems (server logic, client logic, data layer, UI layer)
3. BUILD — write all files simultaneously, update game.json

CIRCUIT BREAKER:
If you attempt to implement something and it fails or produces broken output 3 times in a row, STOP.
Output: "Circuit breaker triggered — I need more information before continuing. [specific question]"
Do not keep retrying the same broken approach.

GAME REFERENCE UNDERSTANDING:
If Denis says "make something like [game name]", respond with:
1. A breakdown of that game's core systems
2. Which systems you'll build first
3. Estimated file count
Then ask for confirmation before starting.

DEBUG MODE:
If Denis pastes a Roblox error output, you:
1. Identify the script and line number from the error
2. Explain exactly what caused it in plain terms
3. Write the patched version of only the affected section
4. Never rewrite the whole file for a single bug fix

SECURITY CHECKER:
Before finalizing any script, scan for these anti-patterns and flag them:
- Client-side RemoteFunction that can be called without server validation
- DataStore write triggered by a client event without server-side auth check
- Humanoid health manipulation from a LocalScript
- Any .Value assignment on a server object from a LocalScript
If found, rewrite the vulnerable section and explain why it was dangerous.

ECONOMY SIMULATOR:
When building economy systems, simulate the math in Python first:
- Define item prices, earn rates, conversion ratios
- Run a 1-hour play session simulation
- Output: average earnings per hour, time-to-afford each item, balance curve
- Only proceed to code after Denis approves the numbers

STYLE RULES:
- All Luau code uses tabs for indentation
- All module scripts return a table: local Module = {} ... return Module
- All server scripts end in .server.lua, all local scripts end in .client.lua
- All module scripts end in .lua (no suffix)
- Comment every function with a one-line description
- Use PascalCase for RemoteEvents, camelCase for local variables, UPPER_CASE for constants

OUTPUT FORMAT:
For every file you create, use this format:
📄 [FilePath/FileName.lua]
[full code block]

Then at the end:
📋 game.json (updated)
[updated json block]

AFTER ANSWERING: STOP. No "let me know if you need anything", no "happy to help", no summaries. Just the files and the updated manifest.
```

---

## `game.json` MANIFEST SYSTEM

### Create `core/roblox_manifest.py`

```python
import json
import os

MANIFEST_PATH = None  # Set from settings: Denis's Roblox project folder path + "/game.json"

DEFAULT_MANIFEST = {
    "game_name": "Untitled",
    "genre": "unknown",
    "project_root": "",
    "systems": [],
    "files": [],
    "remote_events": [],
    "remote_functions": [],
    "datastores": [],
    "economy": {
        "currency": "Coins",
        "items": []
    },
    "last_updated": ""
}

def get_manifest(project_root: str) -> dict:
    path = os.path.join(project_root, "game.json")
    if not os.path.exists(path):
        manifest = DEFAULT_MANIFEST.copy()
        manifest["project_root"] = project_root
        save_manifest(project_root, manifest)
        return manifest
    with open(path, "r") as f:
        return json.load(f)

def save_manifest(project_root: str, manifest: dict):
    from datetime import datetime
    manifest["last_updated"] = datetime.now().isoformat()
    path = os.path.join(project_root, "game.json")
    with open(path, "w") as f:
        json.dump(manifest, f, indent=2)

def register_file(project_root: str, filepath: str, system: str):
    manifest = get_manifest(project_root)
    if filepath not in manifest["files"]:
        manifest["files"].append(filepath)
    if system and system not in manifest["systems"]:
        manifest["systems"].append(system)
    save_manifest(project_root, manifest)

def register_remote_event(project_root: str, name: str, event_type: str = "RemoteEvent"):
    manifest = get_manifest(project_root)
    key = "remote_events" if event_type == "RemoteEvent" else "remote_functions"
    if name not in manifest[key]:
        manifest[key].append(name)
    save_manifest(project_root, manifest)
```

---

## RAG — ROBLOX DOCS NAMESPACE

### Extend `core/rag.py`

Add a second ChromaDB collection for Roblox docs:

```python
ROBLOX_COLLECTION_NAME = "roblox_docs"

def get_roblox_collection():
    return chroma_client.get_or_create_collection(
        name=ROBLOX_COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"}
    )

def index_roblox_docs(docs_folder: str):
    """
    Index all .md or .html files from a downloaded copy of Roblox Creator Docs.
    Call this once from a setup script.
    docs_folder: path to the local copy of Roblox Creator Documentation
    """
    collection = get_roblox_collection()
    for root, _, files in os.walk(docs_folder):
        for fname in files:
            if fname.endswith((".md", ".html", ".txt")):
                fpath = os.path.join(root, fname)
                with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                chunks = chunk_text(content, chunk_size=800, overlap=100)
                for i, chunk in enumerate(chunks):
                    doc_id = f"roblox_{fpath}_{i}"
                    collection.upsert(
                        ids=[doc_id],
                        documents=[chunk],
                        metadatas=[{"source": fpath, "type": "roblox_docs"}]
                    )

def query_roblox_docs(query: str, n_results: int = 5) -> list[str]:
    collection = get_roblox_collection()
    results = collection.query(query_texts=[query], n_results=n_results)
    return results["documents"][0] if results["documents"] else []
```

Also create a one-time setup script: `scripts/index_roblox_docs.py`

```python
"""
Run this once to index the Roblox Creator Documentation into ChromaDB.
Usage: python scripts/index_roblox_docs.py --docs-path /path/to/roblox-docs
"""
import argparse
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from core.rag import index_roblox_docs

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--docs-path", required=True, help="Path to downloaded Roblox Creator Docs folder")
    args = parser.parse_args()
    print(f"Indexing Roblox docs from {args.docs_path}...")
    index_roblox_docs(args.docs_path)
    print("Done.")
```

---

## `core/roblox_agent.py`

```python
import os
import json
from core.rag import query_roblox_docs
from core.roblox_manifest import get_manifest, save_manifest
from core.llm import stream_chat  # reuse existing streaming function

CIRCUIT_BREAKER_LIMIT = 3

class RobloxAgent:
    def __init__(self, project_root: str):
        self.project_root = project_root
        self.failure_count = 0

    def build_context(self, user_message: str) -> str:
        """Inject game.json + relevant RAG docs into the prompt context."""
        manifest = get_manifest(self.project_root)
        manifest_str = json.dumps(manifest, indent=2)

        rag_results = query_roblox_docs(user_message, n_results=5)
        rag_context = "\n\n---\n".join(rag_results) if rag_results else "No relevant docs found."

        context = f"""
=== CURRENT PROJECT STATE (game.json) ===
{manifest_str}

=== RELEVANT ROBLOX DOCUMENTATION ===
{rag_context}

=== USER REQUEST ===
{user_message}
"""
        return context

    def write_file(self, relative_path: str, content: str):
        """Write a Luau script to the project folder."""
        full_path = os.path.join(self.project_root, relative_path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)

    def parse_and_write_output(self, response: str):
        """
        Parse the LLM response for 📄 file blocks and write them to disk.
        Also parse and save the updated game.json block.
        """
        import re
        # Match file blocks: 📄 path/to/file.lua followed by a code block
        file_pattern = re.compile(r'📄\s+(.+?)\n```(?:lua|luau|json)?\n(.*?)```', re.DOTALL)
        matches = file_pattern.findall(response)
        written = []
        for rel_path, code in matches:
            rel_path = rel_path.strip()
            if rel_path == "game.json":
                # Update manifest from the block
                try:
                    new_manifest = json.loads(code.strip())
                    save_manifest(self.project_root, new_manifest)
                except json.JSONDecodeError:
                    pass
            else:
                self.write_file(rel_path, code.strip())
                written.append(rel_path)
        return written

    def run(self, user_message: str, chat_history: list, stream=True):
        """Main entry point. Build context, call LLM, parse output, write files."""
        if self.failure_count >= CIRCUIT_BREAKER_LIMIT:
            yield "Circuit breaker triggered — too many consecutive failures. Please clarify what you need."
            return

        context = self.build_context(user_message)
        full_response = ""

        try:
            for chunk in stream_chat(
                slot=7,
                messages=chat_history + [{"role": "user", "content": context}],
                stream=stream
            ):
                full_response += chunk
                yield chunk

            written_files = self.parse_and_write_output(full_response)
            if written_files:
                yield f"\n\n✅ Written to disk: {', '.join(written_files)}"
            self.failure_count = 0  # reset on success

        except Exception as e:
            self.failure_count += 1
            yield f"\n\n❌ Agent error ({self.failure_count}/{CIRCUIT_BREAKER_LIMIT}): {str(e)}"
```

---

## FLASK ROUTE

Add to `app.py` (or create `routes/roblox.py` as a Blueprint if you prefer):

```python
from core.roblox_agent import RobloxAgent
from flask import request, Response, stream_with_context
import json

# Store agent instance per session (or create per-request if stateless is fine)
_roblox_agents = {}

@app.route("/roblox-chat", methods=["POST"])
def roblox_chat():
    data = request.json
    user_message = data.get("message", "")
    chat_history = data.get("history", [])
    project_root = data.get("project_root", "")  # Denis's Roblox project folder path

    if not project_root or not os.path.isdir(project_root):
        return {"error": "Invalid project_root path"}, 400

    agent = _roblox_agents.get(project_root) or RobloxAgent(project_root)
    _roblox_agents[project_root] = agent

    def generate():
        for chunk in agent.run(user_message, chat_history, stream=True):
            yield f"data: {json.dumps({'content': chunk})}\n\n"
        yield "data: [DONE]\n\n"

    return Response(stream_with_context(generate()), mimetype="text/event-stream")

@app.route("/roblox-manifest", methods=["GET"])
def roblox_manifest():
    project_root = request.args.get("project_root", "")
    if not project_root or not os.path.isdir(project_root):
        return {"error": "Invalid project_root"}, 400
    from core.roblox_manifest import get_manifest
    return get_manifest(project_root)
```

---

## SETTINGS PANEL ADDITION

In `static/js/settings.js`, add a new setting:

```javascript
// Roblox project folder path
const robloxProjectPath = document.getElementById("roblox-project-path");
robloxProjectPath.addEventListener("change", () => {
    saveSetting("roblox_project_root", robloxProjectPath.value.trim());
});
```

In `templates/index.html` settings panel section, add:

```html
<div class="setting-row">
  <label>Roblox Project Folder</label>
  <input type="text" id="roblox-project-path" placeholder="C:/Users/Denis/Documents/Roblox/MyGame" />
</div>
```

Store in the `settings` SQLite table under key `roblox_project_root`.

---

## UI — `+` MENU ADDITION

In the existing `+` popup menu (already implemented), add a **Roblox Mode** toggle button.

When active:
- Route all messages to `/roblox-chat` instead of the main chat endpoint
- Show a small 🎮 indicator pill in the input bar (same style as existing routing pill)
- Load the `roblox_project_root` from settings and pass it with every request

In `static/js/chat.js`, add:

```javascript
let robloxModeActive = false;

function toggleRobloxMode() {
    robloxModeActive = !robloxModeActive;
    document.getElementById("roblox-mode-btn").classList.toggle("active", robloxModeActive);
    document.getElementById("roblox-pill").style.display = robloxModeActive ? "flex" : "none";
}

// When sending a message, check robloxModeActive and use the correct endpoint + payload
```

---

## WHAT NOT TO DO

- Do NOT change any existing chat routes or break the current chat flow
- Do NOT modify the existing ChromaDB collection used for regular file RAG — use a separate `roblox_docs` collection
- Do NOT add Roblox mode to the auto-router — it is always user-triggered, never auto-routed
- Do NOT write any code that assumes the Roblox docs are already indexed — the first-run setup script handles that separately
- Do NOT use `spawn()`, `wait()`, or `delay()` anywhere in generated Luau — always `task.spawn()`, `task.wait()`, `task.delay()`
- Do NOT put server logic in StarterPlayerScripts or LocalScripts — always use ServerScriptService for server code
- Do NOT write the economy simulator in Luau — use Python code execution (already in agent.py) for math simulation

---

## DELIVERABLES CHECKLIST

When done, the following must exist and work:

- [ ] `prompts/roblox_agent.txt` — full system prompt
- [ ] `models/slots.py` — Slot 7 added
- [ ] `core/roblox_agent.py` — full agent class
- [ ] `core/roblox_manifest.py` — manifest read/write/register helpers
- [ ] `core/rag.py` — `roblox_docs` collection + `index_roblox_docs()` + `query_roblox_docs()`
- [ ] `scripts/index_roblox_docs.py` — one-time indexing script
- [ ] `app.py` — `/roblox-chat` and `/roblox-manifest` routes
- [ ] `templates/index.html` — Roblox project path setting field
- [ ] `static/js/settings.js` — saves `roblox_project_root`
- [ ] `static/js/chat.js` — Roblox mode toggle, correct endpoint routing
- [ ] `templates/index.html` `+` menu — Roblox Mode button added

Test: Denis types "create a basic coin collection system" in Roblox mode → agent reads `game.json`, queries Roblox docs RAG, responds with ServerScript + LocalScript + ModuleScript files, writes them to his project folder, updates `game.json`.
