"""
app.py — Flask entry point for Axon.
Registers all routes and initializes the database on startup.
"""

import logging
import os
import socket
import uuid
import httpx
from flask import Flask, Response, jsonify, render_template, request, stream_with_context
from flask_cors import CORS
from config import Config
from database.db import (
    init_db, get_connection, get_setting, set_setting,
    get_all_settings, clear_all_settings,
)
from core.llm import stream_chat, check_connection, unload_other_models
from core.memory import (
    get_all_memories, add_memory, delete_memory, clear_all_memories,
    extract_memories_async, get_memory_context, detect_memory_command,
    search_memories,
)
from core.agent import (
    execute_code, strip_think_blocks, detect_file_writes, save_file,
    read_file_from_disk, write_file_to_disk, list_directory, detect_file_intent,
    safe_calculate,
)
from core.deepthink import deepthink_stream
from core.files import extract_text
from core.rag import index_folder as rag_index_folder, query_documents as rag_query, get_indexed_folders as rag_get_folders, remove_folder as rag_remove_folder, get_roblox_docs_stats
from models.slots import get_slot, get_system_prompt, get_default_system_prompt, get_default_model_id
from core.roblox_agent import get_or_create_agent as get_roblox_agent
from routes.deep_research import deep_research_bp

app = Flask(__name__)
CORS(app)
app.register_blueprint(deep_research_bp)

logging.basicConfig(level=logging.DEBUG, format='%(name)s %(levelname)s: %(message)s')
logging.getLogger('roblox_agent').setLevel(logging.DEBUG)

# Ensure required folders exist
os.makedirs(Config.UPLOAD_FOLDER, exist_ok=True)
os.makedirs(Config.VECTOR_STORE_FOLDER, exist_ok=True)
os.makedirs(Config.DATABASE_FOLDER, exist_ok=True)
os.makedirs(Config.AGENT_FILES_FOLDER, exist_ok=True)


# ── Helpers ────────────────────────────────────────────

TOGGLE_KEYS = ["memory", "agent", "deepthink", "rag", "voice", "auto_routing"]

TOGGLE_DEFAULTS = {k: "true" for k in TOGGLE_KEYS}


def _get_effective_url():
    """Get LM Studio URL from DB or config default."""
    return get_setting("lm_studio_url", Config.LM_STUDIO_URL)


def _get_toggle(key):
    """Get a toggle state as bool."""
    return get_setting("enable_" + key, "true") == "true"


def _build_settings_response():
    """Build the full settings JSON response."""
    db_settings = get_all_settings()

    toggles = {}
    for k in TOGGLE_KEYS:
        toggles[k] = db_settings.get("enable_" + k, "true") == "true"

    lm_url = db_settings.get("lm_studio_url", Config.LM_STUDIO_URL)

    slots = []
    for slot in Config.MODEL_SLOTS:
        sid = slot["id"]
        default_mid = slot["model_id"]
        default_prompt = get_default_system_prompt(sid)
        custom_mid = db_settings.get("slot_%d_model_id" % sid)
        custom_prompt = db_settings.get("slot_%d_system_prompt" % sid)

        slots.append({
            "id": sid,
            "name": slot["name"],
            "accent": slot["accent"],
            "description": slot["description"],
            "model_id": custom_mid or default_mid,
            "system_prompt": custom_prompt or default_prompt,
            "default_model_id": default_mid,
            "default_system_prompt": default_prompt,
            "is_custom_model": custom_mid is not None,
            "is_custom_prompt": custom_prompt is not None,
        })

    roblox_project_root = db_settings.get("roblox_project_root", "")

    return {
        "toggles": toggles,
        "lm_studio_url": lm_url,
        "slots": slots,
        "roblox_project_root": roblox_project_root,
    }


# ── Pages ──────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html", config=Config)


# ── Chat API ───────────────────────────────────────────

@app.route("/api/chat", methods=["POST"])
def api_chat():
    data = request.get_json()
    chat_id = data.get("chat_id")
    slot_id = data.get("slot_id", 1)
    user_message = data.get("message", "").strip()

    if not chat_id or not user_message:
        return jsonify({"error": "Missing chat_id or message"}), 400

    conn = get_connection()
    cur = conn.cursor()

    # Save user message
    msg_id = str(uuid.uuid4())
    cur.execute(
        "INSERT INTO messages (id, chat_id, role, content) VALUES (?, ?, ?, ?)",
        (msg_id, chat_id, "user", user_message),
    )

    # Update chat timestamp and slot
    cur.execute(
        "UPDATE chats SET updated_at = CURRENT_TIMESTAMP, slot_id = ? WHERE id = ?",
        (slot_id, chat_id),
    )

    # Auto-generate title from first user message
    cur.execute(
        "SELECT title FROM chats WHERE id = ?", (chat_id,)
    )
    row = cur.fetchone()
    if row and row["title"] == "New conversation":
        title = user_message[:50].split("\n")[0]
        if len(user_message) > 50:
            title = title.rsplit(" ", 1)[0] + "..."
        cur.execute("UPDATE chats SET title = ? WHERE id = ?", (title, chat_id))

    conn.commit()

    # Build message history from DB
    cur.execute(
        "SELECT role, content FROM messages WHERE chat_id = ? ORDER BY created_at ASC",
        (chat_id,),
    )
    history = [{"role": r["role"], "content": r["content"]} for r in cur.fetchall()]
    conn.close()

    # Auto-routing — pick best slot for this message
    routed_slot_id = slot_id
    slot_was_routed = False
    if _get_toggle("auto_routing"):
        from core.router import detect_slot
        routed_slot_id = detect_slot(
            user_message,
            attached_file=data.get("attached_file"),
            attached_image=data.get("attached_image"),
            current_slot_id=slot_id,
        )
        slot_was_routed = routed_slot_id != slot_id

    # Get model info — check for DB overrides first
    db_settings = get_all_settings()
    slot = get_slot(routed_slot_id)
    default_model_id = slot["model_id"] if slot else Config.MODEL_SLOTS[0]["model_id"]
    model_id = db_settings.get("slot_%d_model_id" % routed_slot_id, default_model_id)
    custom_prompt = db_settings.get("slot_%d_system_prompt" % routed_slot_id)
    system_prompt = custom_prompt if custom_prompt else get_system_prompt(routed_slot_id)
    lm_url = db_settings.get("lm_studio_url", Config.LM_STUDIO_URL)

    # Memory context injection — append stored memories to system prompt
    if _get_toggle("memory"):
        mem_context = get_memory_context()
        if mem_context:
            system_prompt = system_prompt + mem_context

    # RAG context injection — prepend relevant chunks to the last user message
    if _get_toggle("rag"):
        try:
            rag_docs = rag_query(user_message, n_results=5)
            if rag_docs:
                context_parts = []
                for doc in rag_docs:
                    src = doc["metadata"].get("file", "unknown")
                    context_parts.append("[Source: %s]\n%s" % (src, doc["text"]))
                rag_context = "\n\n---\n\n".join(context_parts)
                # Modify the last message in history to include RAG context
                if history and history[-1]["role"] == "user":
                    history[-1]["content"] = (
                        "[Relevant document context]\n\n"
                        + rag_context
                        + "\n\n[User question]: "
                        + history[-1]["content"]
                    )
        except Exception:
            pass  # RAG query failure should not break chat

    # Unload any other loaded models before starting — keeps VRAM clean
    unload_other_models(model_id, lm_url)

    # Collect full response while streaming, then save
    full_response = []

    def generate():
        for chunk in stream_chat(history, model_id, system_prompt, base_url=lm_url):
            # Parse out the token to collect it
            import json as _json
            modified_chunk = chunk
            try:
                payload = chunk.replace("data: ", "").strip()
                parsed = _json.loads(payload)
                if "token" in parsed:
                    full_response.append(parsed["token"])
                elif "done" in parsed:
                    # Save full assistant message to DB
                    assistant_text = "".join(full_response)
                    if assistant_text:
                        c = get_connection()
                        c.execute(
                            "INSERT INTO messages (id, chat_id, role, content) VALUES (?, ?, ?, ?)",
                            (str(uuid.uuid4()), chat_id, "assistant", assistant_text),
                        )
                        c.execute(
                            "UPDATE chats SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                            (chat_id,),
                        )
                        c.commit()
                        c.close()
                        # Auto-extract memories in background
                        if _get_toggle("memory"):
                            extract_memories_async(
                                user_message, assistant_text,
                                model_id, base_url=lm_url,
                            )
                    # Emit done event enriched with routing info
                    done_data = {"done": True}
                    if slot_was_routed:
                        done_data["routed_slot_id"] = routed_slot_id
                        _rs = get_slot(routed_slot_id)
                        done_data["routed_slot_name"] = _rs["name"] if _rs else str(routed_slot_id)
                    modified_chunk = "data: " + _json.dumps(done_data) + "\n\n"
            except Exception:
                pass
            yield modified_chunk

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.route("/api/chats", methods=["GET"])
def api_get_chats():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, title, slot_id, created_at, updated_at FROM chats ORDER BY updated_at DESC")
    chats = [dict(r) for r in cur.fetchall()]
    conn.close()
    return jsonify({"chats": chats})


@app.route("/api/chats/new", methods=["POST"])
def api_new_chat():
    data = request.get_json() or {}
    slot_id = data.get("slot_id", 1)
    chat_id = str(uuid.uuid4())
    conn = get_connection()
    conn.execute(
        "INSERT INTO chats (id, title, slot_id) VALUES (?, ?, ?)",
        (chat_id, "New conversation", slot_id),
    )
    conn.commit()

    cur = conn.cursor()
    cur.execute("SELECT id, title, slot_id, created_at, updated_at FROM chats WHERE id = ?", (chat_id,))
    chat = dict(cur.fetchone())
    conn.close()
    return jsonify({"chat": chat})


@app.route("/api/chats/<chat_id>", methods=["GET"])
def api_get_chat(chat_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, role, content, created_at FROM messages WHERE chat_id = ? ORDER BY created_at ASC",
        (chat_id,),
    )
    messages = [dict(r) for r in cur.fetchall()]
    conn.close()
    return jsonify({"messages": messages})


@app.route("/api/chats/<chat_id>", methods=["DELETE"])
def api_delete_chat(chat_id):
    conn = get_connection()
    conn.execute("DELETE FROM messages WHERE chat_id = ?", (chat_id,))
    conn.execute("DELETE FROM chats WHERE id = ?", (chat_id,))
    conn.commit()
    conn.close()
    return jsonify({"deleted": chat_id})


# ── Connection check ───────────────────────────────────

@app.route("/api/connection", methods=["GET"])
def api_connection():
    url = _get_effective_url()
    connected = check_connection(base_url=url)
    return jsonify({"connected": connected})


@app.route("/api/connection/test", methods=["POST"])
def api_test_connection():
    data = request.get_json() or {}
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"connected": False, "error": "No URL provided"}), 400
    connected = check_connection(base_url=url)
    return jsonify({"connected": connected, "url": url})


# ── Network Info ──────────────────────────────────────

@app.route("/api/network-info", methods=["GET"])
def api_network_info():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
    except Exception:
        try:
            local_ip = socket.gethostbyname(socket.gethostname())
        except Exception:
            local_ip = "127.0.0.1"
    return jsonify({"local_ip": local_ip, "url": "http://{}:5000".format(local_ip)})


@app.route("/api/settings/reset", methods=["POST"])
def api_settings_reset():
    clear_all_settings()
    return jsonify({"ok": True})


# ── Models API ─────────────────────────────────────────

@app.route("/api/models", methods=["GET"])
def api_get_models():
    return jsonify({"models": Config.MODEL_SLOTS})


# ── Upload API ─────────────────────────────────────────

@app.route("/api/upload", methods=["POST"])
def api_upload():
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "Empty filename"}), 400

    # Sanitise filename — keep only basename, no path traversal
    safe_name = os.path.basename(f.filename)
    save_path = os.path.join(Config.UPLOAD_FOLDER, safe_name)

    try:
        f.save(save_path)
        text, truncated = extract_text(save_path)
        return jsonify({
            "filename": safe_name,
            "text": text,
            "truncated": truncated,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        # Clean up temp file
        if os.path.exists(save_path):
            os.remove(save_path)


# ── Memory API ─────────────────────────────────────────

@app.route("/api/memory", methods=["GET"])
def api_get_memory():
    memories = get_all_memories()
    return jsonify({"memories": memories})


@app.route("/api/memory", methods=["POST"])
def api_add_memory():
    data = request.get_json() or {}
    key = data.get("key", "").strip()
    value = data.get("value", "").strip()
    if not key or not value:
        return jsonify({"error": "Missing key or value"}), 400
    mem = add_memory(key, value)
    return jsonify({"memory": mem})


@app.route("/api/memory/<memory_id>", methods=["DELETE"])
def api_delete_memory(memory_id):
    delete_memory(memory_id)
    return jsonify({"deleted": memory_id})


@app.route("/api/memory/all", methods=["DELETE"])
def api_clear_memory():
    clear_all_memories()
    return jsonify({"cleared": True})


@app.route("/api/memory/command", methods=["POST"])
def api_memory_command():
    """Handle explicit memory commands: remember, forget, recall."""
    data = request.get_json() or {}
    message = data.get("message", "").strip()
    if not message:
        return jsonify({"handled": False})

    if not _get_toggle("memory"):
        return jsonify({"handled": False})

    cmd = detect_memory_command(message)
    if not cmd:
        return jsonify({"handled": False})

    action = cmd["action"]

    if action == "recall":
        memories = get_all_memories()
        if not memories:
            return jsonify({"handled": True, "response": "I don't have any memories stored about you yet."})
        lines = []
        for m in memories:
            lines.append("- **%s**: %s" % (m["key"], m["value"]))
        text = "Here's what I remember about you:\n\n" + "\n".join(lines)
        return jsonify({"handled": True, "response": text})

    elif action == "remember":
        content = cmd.get("content", "")
        # Use the content as both key summary and value
        key = content.split()[0].lower() if content.split() else "fact"
        if len(key) < 2:
            key = "fact"
        add_memory(key, content)
        return jsonify({"handled": True, "response": "Got it — I'll remember that."})

    elif action == "forget":
        content = cmd.get("content", "")
        # Search for matching memories and delete them
        matches = search_memories(content)
        if not matches:
            return jsonify({"handled": True, "response": "I don't have any memories matching that."})
        for m in matches:
            delete_memory(m["id"])
        return jsonify({"handled": True, "response": "Done — I've forgotten %d memory%s matching that." % (len(matches), "" if len(matches) == 1 else "s")})

    return jsonify({"handled": False})


# ── Agent API ──────────────────────────────────────────

@app.route("/api/agent/execute", methods=["POST"])
def api_agent_execute():
    """Save code to AgentFiles and optionally run it."""
    data = request.get_json() or {}
    code = data.get("code", "")
    filename = data.get("filename", "agent_script")
    run = data.get("run", True)

    if not code:
        return jsonify({"success": False, "error": "No code provided"}), 400

    result = execute_code(code, filename=filename, run=run)
    status = 200 if result.get("success") else 400
    return jsonify(result), status


@app.route("/api/agent/auto-save", methods=["POST"])
def api_agent_auto_save():
    """Detect file-write intentions in AI response and save them."""
    data = request.get_json() or {}
    response_text = data.get("response", "")

    if not response_text:
        return jsonify({"files": []})

    detected = detect_file_writes(response_text)
    saved = []

    for item in detected:
        result = save_file(item["code"], item["filename"])
        if result.get("success"):
            saved.append({
                "filename": result["filename"],
                "path": result["path"],
            })

    return jsonify({"files": saved})


@app.route("/api/agent/file-read", methods=["POST"])
def api_agent_file_read():
    """Read a file from disk and return its contents."""
    if not _get_toggle("agent"):
        return jsonify({"success": False, "error": "Agent mode is disabled"}), 403

    data = request.get_json() or {}
    file_path = data.get("path", "").strip()
    if not file_path:
        return jsonify({"success": False, "error": "No path provided"}), 400

    result = read_file_from_disk(file_path)
    status = 200 if result.get("success") else 400
    return jsonify(result), status


@app.route("/api/agent/file-write", methods=["POST"])
def api_agent_file_write():
    """Write content to a file on disk."""
    if not _get_toggle("agent"):
        return jsonify({"success": False, "error": "Agent mode is disabled"}), 403

    data = request.get_json() or {}
    file_path = data.get("path", "").strip()
    content = data.get("content", "")

    if not file_path:
        return jsonify({"success": False, "error": "No path provided"}), 400
    if content is None:
        return jsonify({"success": False, "error": "No content provided"}), 400

    result = write_file_to_disk(file_path, content)
    status = 200 if result.get("success") else 400
    return jsonify(result), status


@app.route("/api/agent/file-list", methods=["POST"])
def api_agent_file_list():
    """List contents of a directory."""
    if not _get_toggle("agent"):
        return jsonify({"success": False, "error": "Agent mode is disabled"}), 403

    data = request.get_json() or {}
    dir_path = data.get("path", "").strip()
    if not dir_path:
        return jsonify({"success": False, "error": "No path provided"}), 400

    result = list_directory(dir_path)
    status = 200 if result.get("success") else 400
    return jsonify(result), status


@app.route("/api/agent/detect-intent", methods=["POST"])
def api_agent_detect_intent():
    """Detect file operation intent in a user message."""
    data = request.get_json() or {}
    message = data.get("message", "")
    intent = detect_file_intent(message)
    return jsonify(intent)


@app.route("/api/agent/run-code", methods=["POST"])
def api_agent_run_code():
    """Execute code and return stdout/stderr."""
    if not _get_toggle("agent"):
        return jsonify({"success": False, "error": "Agent mode is disabled"}), 403

    data = request.get_json() or {}
    code = data.get("code", "")
    language = data.get("language", "py")

    if not code.strip():
        return jsonify({"success": False, "error": "No code provided"}), 400

    filename = "agent_run." + language
    result = execute_code(code, filename=filename, run=True)
    return jsonify(result), 200 if result.get("success") else 400


@app.route("/api/agent/calculate", methods=["POST"])
def api_agent_calculate():
    """Safely evaluate a math expression."""
    if not _get_toggle("agent"):
        return jsonify({"success": False, "error": "Agent mode is disabled"}), 403

    data = request.get_json() or {}
    expression = data.get("expression", "")
    result = safe_calculate(expression)
    return jsonify(result), 200 if result.get("success") else 400


# ── DeepThink API ──────────────────────────────────────

@app.route("/api/deepthink", methods=["POST"])
def api_deepthink():
    """Run DeepThink — web search + synthesis, streamed as SSE."""
    data = request.get_json() or {}
    query = data.get("query", "").strip()
    chat_id = data.get("chat_id")
    slot_id = data.get("slot_id", 1)

    if not query:
        return jsonify({"error": "Missing query"}), 400

    # Get model config
    db_settings = get_all_settings()
    slot = get_slot(slot_id)
    default_model_id = slot["model_id"] if slot else Config.MODEL_SLOTS[0]["model_id"]
    model_id = db_settings.get("slot_%d_model_id" % slot_id, default_model_id)
    custom_prompt = db_settings.get("slot_%d_system_prompt" % slot_id)
    system_prompt = custom_prompt if custom_prompt else get_system_prompt(slot_id)
    lm_url = db_settings.get("lm_studio_url", Config.LM_STUDIO_URL)

    # Save user message to DB if we have a chat
    if chat_id:
        conn = get_connection()
        conn.execute(
            "INSERT INTO messages (id, chat_id, role, content) VALUES (?, ?, ?, ?)",
            (str(uuid.uuid4()), chat_id, "user", "[DeepThink] " + query),
        )
        conn.execute(
            "UPDATE chats SET updated_at = CURRENT_TIMESTAMP, slot_id = ? WHERE id = ?",
            (slot_id, chat_id),
        )
        conn.commit()
        conn.close()

    full_response = []

    def generate():
        for chunk in deepthink_stream(query, model_id, system_prompt, base_url=lm_url):
            # Collect tokens for DB save
            import json as _json
            try:
                payload = chunk.replace("data: ", "").strip()
                parsed = _json.loads(payload)
                if "token" in parsed:
                    full_response.append(parsed["token"])
                elif "done" in parsed and chat_id:
                    assistant_text = "".join(full_response)
                    if assistant_text:
                        c = get_connection()
                        c.execute(
                            "INSERT INTO messages (id, chat_id, role, content) VALUES (?, ?, ?, ?)",
                            (str(uuid.uuid4()), chat_id, "assistant", assistant_text),
                        )
                        c.execute(
                            "UPDATE chats SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                            (chat_id,),
                        )
                        c.commit()
                        c.close()
            except Exception:
                pass
            yield chunk

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ── RAG API ────────────────────────────────────────────

@app.route("/api/rag/index", methods=["POST"])
def api_rag_index():
    data = request.get_json() or {}
    folder = data.get("folder", "").strip()
    if not folder:
        return jsonify({"error": "No folder path provided"}), 400
    if not os.path.isdir(folder):
        return jsonify({"error": "Folder does not exist"}), 400

    result = rag_index_folder(folder)
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result)


@app.route("/api/rag/folders", methods=["GET"])
def api_rag_folders():
    folders = rag_get_folders()
    return jsonify({"folders": folders})


@app.route("/api/rag/folder", methods=["DELETE"])
def api_rag_delete_folder():
    data = request.get_json() or {}
    folder = data.get("folder", "").strip()
    if not folder:
        return jsonify({"error": "No folder path provided"}), 400
    result = rag_remove_folder(folder)
    return jsonify(result)


@app.route("/api/rag/query", methods=["POST"])
def api_rag_query():
    data = request.get_json() or {}
    query = data.get("query", "").strip()
    n_results = data.get("n_results", 5)
    if not query:
        return jsonify({"error": "No query provided"}), 400
    docs = rag_query(query, n_results=n_results)
    return jsonify({"results": docs})


# ── Settings API ───────────────────────────────────────

@app.route("/api/settings", methods=["GET"])
def api_get_settings():
    return jsonify(_build_settings_response())


@app.route("/api/settings", methods=["POST"])
def api_save_settings():
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data"}), 400

    key = data.get("key", "").strip()
    value = data.get("value")

    if not key:
        return jsonify({"error": "Missing key"}), 400

    # Validate toggle keys
    valid_keys = (
        ["lm_studio_url", "roblox_project_root"]
        + ["enable_" + k for k in TOGGLE_KEYS]
        + ["slot_%d_model_id" % i for i in range(1, 8)]
        + ["slot_%d_system_prompt" % i for i in range(1, 8)]
    )

    if key not in valid_keys:
        return jsonify({"error": "Invalid setting key"}), 400

    if value is None or str(value).strip() == "":
        # Clearing a custom override — delete the key
        from database.db import delete_setting
        delete_setting(key)
    else:
        set_setting(key, value)

    return jsonify({"saved": True, "key": key})


@app.route("/api/settings/reset", methods=["POST"])
def api_reset_settings():
    clear_all_settings()
    return jsonify({"reset": True})


@app.route("/api/settings/reset-slot", methods=["POST"])
def api_reset_slot():
    data = request.get_json() or {}
    slot_id = data.get("slot_id")
    if not slot_id or slot_id not in range(1, 8):
        return jsonify({"error": "Invalid slot_id"}), 400
    from database.db import delete_setting
    delete_setting("slot_%d_model_id" % slot_id)
    delete_setting("slot_%d_system_prompt" % slot_id)
    return jsonify({"reset": True, "slot_id": slot_id})

# ── Roblox Agent API ─────────────────────────────────────────

@app.route("/roblox-chat", methods=["POST"])
def roblox_chat():
    """Roblox Agent streaming endpoint — uses Slot 7 + game.json context."""
    data = request.get_json() or {}
    chat_id = data.get("chat_id")
    user_message = data.get("message", "").strip()
    project_root = data.get("project_root", "").strip()

    if not user_message:
        return jsonify({"error": "Missing message"}), 400

    # Validate project root — allow empty (agent works without file writes)
    if project_root and not os.path.isdir(project_root):
        project_root = ""

    # Save user message + build history from DB
    history = []
    if chat_id:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO messages (id, chat_id, role, content) VALUES (?, ?, ?, ?)",
            (str(uuid.uuid4()), chat_id, "user", user_message),
        )
        cur.execute(
            "UPDATE chats SET updated_at = CURRENT_TIMESTAMP, slot_id = 7 WHERE id = ?",
            (chat_id,),
        )
        # Auto-generate title
        cur.execute("SELECT title FROM chats WHERE id = ?", (chat_id,))
        row = cur.fetchone()
        if row and row["title"] == "New conversation":
            title = user_message[:50].split("\n")[0]
            if len(user_message) > 50:
                title = title.rsplit(" ", 1)[0] + "..."
            cur.execute("UPDATE chats SET title = ? WHERE id = ?", (title, chat_id))
        conn.commit()
        cur.execute(
            "SELECT role, content FROM messages WHERE chat_id = ? ORDER BY created_at ASC",
            (chat_id,),
        )
        history = [{"role": r["role"], "content": r["content"]} for r in cur.fetchall()]
        conn.close()

    # prior_history = everything except the last message (the one we just added)
    prior_history = history[:-1] if history else []

    # Get model config for Slot 7
    db_settings = get_all_settings()
    slot = get_slot(7)
    default_model_id = slot["model_id"] if slot else "qwen2.5-coder-32b-instruct"
    model_id = db_settings.get("slot_7_model_id", default_model_id)
    custom_prompt = db_settings.get("slot_7_system_prompt")
    system_prompt = custom_prompt if custom_prompt else get_system_prompt(7)
    lm_url = db_settings.get("lm_studio_url", Config.LM_STUDIO_URL)

    agent = get_roblox_agent(project_root)
    full_response = []

    def generate():
        for chunk in agent.run(user_message, prior_history, model_id, system_prompt, base_url=lm_url):
            import json as _json
            try:
                payload = chunk.replace("data: ", "").strip()
                parsed = _json.loads(payload)
                if "token" in parsed:
                    full_response.append(parsed["token"])
                elif "done" in parsed and chat_id:
                    assistant_text = "".join(full_response)
                    if assistant_text:
                        c = get_connection()
                        c.execute(
                            "INSERT INTO messages (id, chat_id, role, content) VALUES (?, ?, ?, ?)",
                            (str(uuid.uuid4()), chat_id, "assistant", assistant_text),
                        )
                        c.execute(
                            "UPDATE chats SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                            (chat_id,),
                        )
                        c.commit()
                        c.close()
            except Exception:
                pass
            yield chunk

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/roblox-manifest", methods=["GET"])
def roblox_manifest():
    """Return the current game.json manifest for a project root."""
    project_root = request.args.get("project_root", "").strip()
    if not project_root or not os.path.isdir(project_root):
        return jsonify({"error": "Invalid or missing project_root"}), 400
    from core.roblox_manifest import get_manifest
    return jsonify(get_manifest(project_root))


@app.route("/api/rag/roblox-stats", methods=["GET"])
def api_roblox_docs_stats():
    """Return chunk count for the roblox_docs ChromaDB collection."""
    try:
        stats = get_roblox_docs_stats()
        return jsonify(stats)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Anthropic Messages API Proxy ───────────────────────
# Translates Anthropic Messages API requests into OpenAI format,
# forwards to LM Studio, and converts responses back to Anthropic format.
# Usage:  ANTHROPIC_BASE_URL=http://localhost:5000 claude

import json as _json
import time as _time

_CLAUDE_MODEL_MAP = {
    # ── Haiku → Slot 1 Chat (fast, Llama 8B) ──────────
    "claude-haiku-4-5":             "meta-llama-3.1-8b-instruct",
    "claude-3-haiku-20240307":      "meta-llama-3.1-8b-instruct",

    # ── Sonnet v4 → Slot 5 Unrestricted (Dolphin 8B, fast & uncensored) ──
    "claude-sonnet-4-6":            "dolphin3.0-llama3.1-8b",
    "claude-sonnet-4-20250514":     "dolphin3.0-llama3.1-8b",

    # ── Sonnet v3.5 → Slot 6 Unrestricted+ (Dolphin Mixtral, smarter) ──
    "claude-3-5-sonnet-20241022":   "dolphin-2.9.2-mixtral-8x22b",
    "claude-3-5-sonnet-20240620":   "dolphin-2.9.2-mixtral-8x22b",

    # ── Opus v4 → Slot 3 Coding (Qwen 2.5 Coder 32B) ─
    "claude-opus-4-6":              "qwen2.5-coder-32b-instruct",
    "claude-opus-4-20250514":       "qwen2.5-coder-32b-instruct",

    # ── Opus v3 → Slot 4 Reasoning/Thinking (QwQ 32B) ─
    "claude-3-opus-20240229":       "qwen/qwq-32b",
}


def _resolve_claude_model(model_name):
    """Map any Claude model string to the local LM Studio model (Slot 1 default)."""
    if model_name in _CLAUDE_MODEL_MAP:
        return _CLAUDE_MODEL_MAP[model_name]
    # Any unrecognised claude-* model → slot 1 default
    if model_name and "claude" in model_name.lower():
        db_settings = get_all_settings()
        return db_settings.get("slot_1_model_id", get_default_model_id(1))
    return model_name


def _anthropic_to_openai_messages(data):
    """Convert Anthropic Messages API request body to OpenAI chat format."""
    oai_messages = []

    # System prompt — Anthropic puts it as a top-level 'system' field
    system = data.get("system")
    if system:
        if isinstance(system, list):
            # Anthropic allows system as list of content blocks
            text_parts = []
            for block in system:
                if isinstance(block, dict) and block.get("type") == "text":
                    text_parts.append(block["text"])
                elif isinstance(block, str):
                    text_parts.append(block)
            system = "\n".join(text_parts)
        oai_messages.append({"role": "system", "content": system})

    # Convert messages
    for msg in data.get("messages", []):
        role = msg.get("role", "user")
        content = msg.get("content", "")

        # Anthropic content can be a string or list of content blocks
        if isinstance(content, list):
            text_parts = []
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
                    elif block.get("type") == "tool_result":
                        text_parts.append(block.get("content", ""))
                elif isinstance(block, str):
                    text_parts.append(block)
            content = "\n".join(text_parts)

        oai_messages.append({"role": role, "content": content})

    return oai_messages


def _make_msg_id():
    return "msg_axon_" + uuid.uuid4().hex[:12]


@app.route("/v1/messages", methods=["POST"])
def anthropic_messages():
    """Anthropic Messages API proxy — converts to OpenAI, forwards to LM Studio."""
    data = request.get_json()
    if not data:
        return jsonify({"type": "error", "error": {"type": "invalid_request_error",
                        "message": "Request body is required"}}), 400

    requested_model = data.get("model", "claude-opus-4-6")
    local_model = _resolve_claude_model(requested_model)
    max_tokens = data.get("max_tokens", 4096)
    stream = data.get("stream", False)
    oai_messages = _anthropic_to_openai_messages(data)

    lm_url = _get_effective_url()
    client = _get_client(lm_url)

    if stream:
        return _anthropic_stream(client, local_model, oai_messages, max_tokens, requested_model)
    else:
        return _anthropic_non_stream(client, local_model, oai_messages, max_tokens, requested_model)


def _get_client(base_url):
    """Create an OpenAI client for the proxy."""
    from openai import OpenAI
    return OpenAI(
        base_url=base_url,
        api_key=Config.LM_STUDIO_API_KEY,
        timeout=httpx.Timeout(connect=10.0, read=None, write=30.0, pool=10.0),
    )


def _anthropic_non_stream(client, model, messages, max_tokens, requested_model):
    """Handle non-streaming Anthropic request."""
    try:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            stream=False,
            extra_body={"num_ctx": 32768},
        )
        text = response.choices[0].message.content or ""
        usage = response.usage
        return jsonify({
            "id": _make_msg_id(),
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": text}],
            "model": requested_model,
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {
                "input_tokens": usage.prompt_tokens if usage else 0,
                "output_tokens": usage.completion_tokens if usage else 0,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
            },
        })
    except Exception as e:
        return jsonify({"type": "error", "error": {"type": "api_error",
                        "message": str(e)}}), 500


def _anthropic_stream(client, model, messages, max_tokens, requested_model):
    """Handle streaming Anthropic request — returns SSE in Anthropic format."""
    msg_id = _make_msg_id()

    def generate():
        # message_start
        yield "event: message_start\n"
        yield "data: " + _json.dumps({
            "type": "message_start",
            "message": {
                "id": msg_id,
                "type": "message",
                "role": "assistant",
                "content": [],
                "model": requested_model,
                "stop_reason": None,
                "stop_sequence": None,
                "usage": {"input_tokens": 0, "output_tokens": 0,
                          "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0},
            },
        }) + "\n\n"

        # content_block_start
        yield "event: content_block_start\n"
        yield "data: " + _json.dumps({
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "text", "text": ""},
        }) + "\n\n"

        # Stream from LM Studio
        output_tokens = 0
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=max_tokens,
                stream=True,
                extra_body={"num_ctx": 32768},
            )
            for chunk in response:
                delta = chunk.choices[0].delta if chunk.choices else None
                if delta and delta.content:
                    output_tokens += 1
                    yield "event: content_block_delta\n"
                    yield "data: " + _json.dumps({
                        "type": "content_block_delta",
                        "index": 0,
                        "delta": {"type": "text_delta", "text": delta.content},
                    }) + "\n\n"
        except Exception as e:
            # Send error as a text delta so Claude Code sees it
            yield "event: content_block_delta\n"
            yield "data: " + _json.dumps({
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": "\n[LM Studio error: " + str(e) + "]"},
            }) + "\n\n"

        # content_block_stop
        yield "event: content_block_stop\n"
        yield "data: " + _json.dumps({
            "type": "content_block_stop",
            "index": 0,
        }) + "\n\n"

        # message_delta
        yield "event: message_delta\n"
        yield "data: " + _json.dumps({
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn", "stop_sequence": None},
            "usage": {"output_tokens": output_tokens},
        }) + "\n\n"

        # message_stop
        yield "event: message_stop\n"
        yield "data: " + _json.dumps({"type": "message_stop"}) + "\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.route("/health", methods=["GET"])
@app.route("/v1/health", methods=["GET"])
def health_check():
    return jsonify({"status": "ok"})


# ── Claude Code v2 auth endpoints ─────────────────────
@app.route("/v1/me", methods=["GET"])
def v1_me():
    return jsonify({
        "id": "usr_axon_local",
        "type": "user",
        "display_name": "Axon Local",
        "email": "local@axon",
        "phone": None,
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-01T00:00:00Z",
    })

@app.route("/api/auth/check", methods=["GET", "POST"])
def auth_check():
    return jsonify({"authenticated": True})


@app.route("/v1/organizations", methods=["GET"])
def v1_organizations():
    return jsonify({
        "data": [{"id": "org_axon_local", "name": "Axon Local"}]
    })


@app.route("/v1/entitlements", methods=["GET"])
def v1_entitlements():
    return jsonify({
        "entitlements": [{"name": "claude_code", "enabled": True}]
    })


@app.route("/v1/models", methods=["GET"])
def v1_models():
    """Return models list including Claude model aliases for compatibility."""
    claude_models = [
        {"id": name, "object": "model", "owned_by": "axon-proxy"}
        for name in _CLAUDE_MODEL_MAP
    ]
    # Also include the real LM Studio models from slots
    local_models = [
        {"id": slot["model_id"], "object": "model", "owned_by": "lm-studio"}
        for slot in Config.MODEL_SLOTS
    ]
    return jsonify({"object": "list", "data": claude_models + local_models})


# ── Start ──────────────────────────────────────────────

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000, debug=True)
