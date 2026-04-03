"""
memory.py — Persistent memory system for Axon.
Stores facts about the user across sessions in SQLite.
Allows viewing, adding, deleting, and automatic extraction of memories.
"""

import json
import re
import threading
import uuid
from database.db import get_connection


# ── Extraction prompt ──────────────────────────────────

_EXTRACT_PROMPT = (
    "You are a strict memory filter. Analyze the conversation below and extract "
    "ONLY facts that are genuinely worth remembering about the user long-term.\n\n"
    "SAVE these kinds of facts:\n"
    "- User's name, location, age, job, or background\n"
    "- Stated preferences (e.g. 'I prefer dark mode', 'I like Python over JS')\n"
    "- Ongoing projects or goals they mention\n"
    "- Interests, hobbies, or areas of expertise\n"
    "- Things the user EXPLICITLY asks you to remember ('remember that', 'save this', 'do not forget')\n"
    "- Important personal facts that would still matter in a week\n\n"
    "DO NOT SAVE:\n"
    "- Greetings, small talk, or test messages ('hi', 'hello', 'test', 'thanks')\n"
    "- Temporary file names, code snippets, or one-off technical details\n"
    "- Anything about the assistant's behavior or capabilities\n"
    "- Facts that are only relevant to the current conversation\n"
    "- Vague or trivial statements ('user asked a question', 'user wants help')\n"
    "- Anything you are not confident is a real, persistent fact about the user\n\n"
    "Ask yourself: would this fact still be useful to know in a week? If not, skip it.\n"
    "When in doubt, return an EMPTY array. It is better to save nothing than to save junk.\n\n"
    "Return ONLY a valid JSON array of objects with \"key\" and \"value\" fields.\n"
    "If nothing is worth saving, return exactly: []\n\n"
    "Example of good extraction:\n"
    '[{"key": "name", "value": "User name is Alex"}, '
    '{"key": "work", "value": "Works as a backend developer at a startup"}]\n\n'
    "Example of conversations with NOTHING worth saving (return []):\n"
    "- 'Hello!' / 'Hi there! How can I help?'\n"
    "- 'Write me a Python script to sort a list' / [code response]\n"
    "- 'Thanks!' / 'You are welcome!'\n"
    "- 'Test' / 'This is a test response'\n\n"
    "Respond with ONLY the JSON array. No markdown, no explanation."
)


def get_all_memories():
    """Retrieve all stored memories."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, key, value, created_at FROM memories ORDER BY created_at DESC")
    memories = [dict(r) for r in cur.fetchall()]
    conn.close()
    return memories


def add_memory(key, value):
    """Store a new memory. Returns the new memory dict."""
    mem_id = str(uuid.uuid4())
    conn = get_connection()
    conn.execute(
        "INSERT INTO memories (id, key, value) VALUES (?, ?, ?)",
        (mem_id, key, value),
    )
    conn.commit()
    conn.close()
    return {"id": mem_id, "key": key, "value": value}


def delete_memory(memory_id):
    """Delete a memory by ID."""
    conn = get_connection()
    conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
    conn.commit()
    conn.close()


def clear_all_memories():
    """Delete all memories."""
    conn = get_connection()
    conn.execute("DELETE FROM memories")
    conn.commit()
    conn.close()


def search_memories(query):
    """Search memories relevant to a query."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, key, value, created_at FROM memories WHERE key LIKE ? OR value LIKE ? ORDER BY created_at DESC",
        ("%" + query + "%", "%" + query + "%"),
    )
    memories = [dict(r) for r in cur.fetchall()]
    conn.close()
    return memories


def get_memory_context():
    """Build a formatted string of all stored memories for system prompt injection."""
    memories = get_all_memories()
    if not memories:
        return ""
    lines = []
    for m in memories:
        lines.append("- %s: %s" % (m["key"], m["value"]))
    return (
        "\n\n[User Memory — things you know about this user from past conversations]\n"
        + "\n".join(lines)
        + "\n[End of User Memory]\n"
    )


def detect_memory_command(message):
    """
    Detect explicit memory commands in user message.
    Returns dict with 'action' and optional 'content', or None if no command.
    Actions: 'remember', 'forget', 'recall'
    """
    msg = message.strip().lower()

    # Recall commands
    recall_patterns = [
        r"^what do you (know|remember) about me",
        r"^what are my memories",
        r"^show (my |)memories",
        r"^list (my |)memories",
        r"^what have you (saved|stored|remembered)",
    ]
    for pat in recall_patterns:
        if re.search(pat, msg):
            return {"action": "recall"}

    # Forget commands
    forget_patterns = [
        r"^forget (?:that |about |)(.*)",
        r"^delete memory[: ]+(.*)",
        r"^remove memory[: ]+(.*)",
        r"^don'?t remember (.*)",
    ]
    for pat in forget_patterns:
        m = re.search(pat, msg)
        if m:
            return {"action": "forget", "content": m.group(1).strip()}

    # Remember commands
    remember_patterns = [
        r"^remember (?:that |)(.*)",
        r"^save (?:that |this[: ]* |)(.*)",
        r"^store (?:that |this[: ]* |)(.*)",
        r"^do not forget (?:that |)(.*)",
        r"^don'?t forget (?:that |)(.*)",
    ]
    for pat in remember_patterns:
        m = re.search(pat, msg)
        if m and len(m.group(1).strip()) > 3:
            return {"action": "remember", "content": m.group(1).strip()}

    return None


# ── Post-extraction quality filter ─────────────────────

# Words/phrases that indicate a memory is trivial junk
_JUNK_PATTERNS = [
    "user asked", "user wants", "user said", "user is asking",
    "user greeted", "user tested", "user thanked",
    "assistant ", "the ai ", "the bot ",
    "hello", "hi there", "hey", "thanks", "thank you", "goodbye",
    "test message", "test response", "testing",
    "wants help", "needs help", "asked for help",
    "asked a question", "had a conversation",
    "is using axon", "is chatting",
]


def _is_worth_saving(key, value):
    """Return True only if a memory fact passes quality checks."""
    combined = (key + " " + value).lower().strip()

    # Too short to be meaningful
    if len(value) < 5:
        return False

    # Reject if it matches known junk patterns
    for pattern in _JUNK_PATTERNS:
        if pattern in combined:
            return False

    # Reject very generic keys that aren't informative
    generic_keys = {"conversation", "chat", "message", "response", "query", "request", "greeting"}
    if key.lower().strip() in generic_keys:
        return False

    return True


# ── Automatic extraction ──────────────────────────────

def extract_memories_from_exchange(user_message, assistant_response, model_id, base_url=None):
    """
    Send the exchange to the LLM with an extraction prompt,
    parse the JSON response, and save any new facts.
    """
    from core.llm import complete_chat

    messages = [
        {
            "role": "user",
            "content": (
                "User said:\n" + user_message + "\n\n"
                "Assistant responded:\n" + assistant_response
            ),
        }
    ]

    raw = complete_chat(messages, model_id, _EXTRACT_PROMPT, base_url=base_url)
    if not raw:
        return

    # Parse JSON array from response
    try:
        start = raw.find("[")
        end = raw.rfind("]")
        if start == -1 or end == -1:
            return
        facts = json.loads(raw[start : end + 1])
    except (json.JSONDecodeError, ValueError):
        return

    if not isinstance(facts, list):
        return

    for fact in facts:
        if not isinstance(fact, dict):
            continue
        key = str(fact.get("key", "")).strip()[:100]
        value = str(fact.get("value", "")).strip()[:500]
        if not key or not value:
            continue
        # Quality filter — reject trivial or junk memories
        if not _is_worth_saving(key, value):
            continue
        # Skip duplicates
        existing = search_memories(key)
        if any(m["value"].lower() == value.lower() for m in existing):
            continue
        add_memory(key, value)


def extract_memories_async(user_message, assistant_response, model_id, base_url=None):
    """Run memory extraction in a background thread so it doesn't block SSE."""
    t = threading.Thread(
        target=extract_memories_from_exchange,
        args=(user_message, assistant_response, model_id, base_url),
        daemon=True,
    )
    t.start()
