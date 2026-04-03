"""
routes/deep_research.py — Flask Blueprint for Deep Research mode.

POST /deep-research         — starts autonomous research, returns SSE stream
GET  /deep-research/report/<filename> — serves a saved report file for download
"""

import json
import os
import threading
import uuid

from flask import Blueprint, Response, jsonify, request, send_from_directory, stream_with_context

from config import Config
from core.deep_research import DeepResearch, _REPORTS_DIR
from database.db import get_connection, get_all_settings
from models.slots import get_slot, get_system_prompt

deep_research_bp = Blueprint("deep_research", __name__)


@deep_research_bp.route("/deep-research", methods=["POST"])
def start_research():
    """Kick off a Deep Research session. Returns an SSE stream."""
    data = request.get_json() or {}
    topic = data.get("topic", "").strip()
    chat_id = data.get("chat_id")

    if not topic:
        return jsonify({"error": "Missing topic"}), 400

    # Use Slot 1 (Chat model) for all research LLM calls
    db_settings = get_all_settings()
    slot = get_slot(1)
    model_id = db_settings.get("slot_1_model_id", slot["model_id"] if slot else Config.MODEL_SLOTS[0]["model_id"])
    lm_url = db_settings.get("lm_studio_url", Config.LM_STUDIO_URL)

    # Save user message to DB
    if chat_id:
        conn = get_connection()
        conn.execute(
            "INSERT INTO messages (id, chat_id, role, content) VALUES (?, ?, ?, ?)",
            (str(uuid.uuid4()), chat_id, "user", "[Deep Research] " + topic),
        )
        conn.execute(
            "UPDATE chats SET updated_at = CURRENT_TIMESTAMP, slot_id = 1 WHERE id = ?",
            (chat_id,),
        )
        # Auto-title
        cur = conn.execute("SELECT title FROM chats WHERE id = ?", (chat_id,))
        row = cur.fetchone()
        if row and row["title"] == "New conversation":
            title = ("🔬 " + topic[:47]).split("\n")[0]
            conn.execute("UPDATE chats SET title = ? WHERE id = ?", (title, chat_id))
        conn.commit()
        conn.close()

    researcher = DeepResearch(base_url=lm_url, model_id=model_id)
    full_response = []

    def generate():
        for chunk in researcher.run(topic):
            # Collect tokens for DB save
            try:
                payload = chunk.replace("data: ", "").strip()
                parsed = json.loads(payload)
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


@deep_research_bp.route("/deep-research/report/<path:filename>")
def serve_report(filename):
    """Serve a saved report file for download."""
    # Sanitize — prevent directory traversal
    safe_name = os.path.basename(filename)
    if safe_name != filename:
        return jsonify({"error": "Invalid filename"}), 400
    if not os.path.isfile(os.path.join(_REPORTS_DIR, safe_name)):
        return jsonify({"error": "File not found"}), 404
    return send_from_directory(
        _REPORTS_DIR, safe_name, as_attachment=True
    )
