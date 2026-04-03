"""
agent.py — Agent mode for Axon.
Detects code language, saves files to AgentFiles,
runs them with the correct interpreter, returns output.
"""

import os
import re
import ast
import operator
import subprocess
from config import Config


# ── Language detection ─────────────────────────────────

_PYTHON_SIGNALS = [
    "import ", "from ", "def ", "print(", "if __name__",
    "class ", "#!/usr/bin/env python", "#!python",
    "elif ", "lambda ", "range(", "len(", "str(", "int(",
]

_POWERSHELL_SIGNALS = [
    "Write-Host", "Get-", "Set-", "New-", "Remove-",
    "Invoke-", "$PSVersionTable", "param(", "[CmdletBinding]",
    "Write-Output", "ForEach-Object", "Where-Object",
]

_BATCH_SIGNALS = [
    "@echo", "echo ", "pause", "cls", "set ", "goto ",
    "if exist", "for /f", "call ", "start ", "cmd /k", "cmd /c",
    "rem ", "::",
]


def _detect_language(code, suggested_filename=""):
    """Detect code language and return (extension, run_command_prefix)."""
    suggested_ext = os.path.splitext(suggested_filename)[1].lower() if suggested_filename else ""
    code_lower = code.lower()

    py_score = sum(1 for s in _PYTHON_SIGNALS if s.lower() in code_lower)
    ps_score = sum(1 for s in _POWERSHELL_SIGNALS if s.lower() in code_lower)
    bat_score = sum(1 for s in _BATCH_SIGNALS if s.lower() in code_lower)

    python_exe = Config.PYTHON_EXE

    if py_score > 0 and py_score >= ps_score and py_score >= bat_score:
        return ".py", [python_exe]
    if ps_score > bat_score and ps_score > 0:
        return ".ps1", ["powershell", "-ExecutionPolicy", "Bypass", "-File"]
    if bat_score > 0 or suggested_ext == ".bat":
        return ".bat", None  # shell=True handles .bat
    # Honour suggested extension as fallback
    if suggested_ext == ".py":
        return ".py", [python_exe]
    if suggested_ext == ".ps1":
        return ".ps1", ["powershell", "-ExecutionPolicy", "Bypass", "-File"]
    return ".bat", None


# ── Think-block and fence stripping ───────────────────

def strip_think_blocks(text):
    """Remove <think>...</think> reasoning blocks from text."""
    return re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.IGNORECASE).strip()


def strip_code_fences(text):
    """Remove markdown code fences wrapping the text."""
    text = re.sub(r"^```[\w]*\n?", "", text, flags=re.MULTILINE).strip()
    text = re.sub(r"^```$", "", text, flags=re.MULTILINE).strip()
    return text


def clean_code(text):
    """Strip think blocks and code fences from AI-generated code."""
    return strip_code_fences(strip_think_blocks(text))


# ── File execution ────────────────────────────────────

def execute_code(code, filename="agent_script", run=True):
    """
    Save code to AgentFiles folder and optionally run it.
    Returns dict with success, path, filename, language, output.
    """
    code = clean_code(code)
    if not code:
        return {"success": False, "error": "No code after stripping think blocks"}

    ext, run_prefix = _detect_language(code, filename)

    # Sanitise filename
    base_name = re.sub(r"\.[^.]+$", "", filename)
    safe_name = re.sub(r"[^\w\-]", "_", base_name) + ext
    if not safe_name or safe_name == ext:
        safe_name = "agent_script" + ext

    agent_dir = Config.AGENT_FILES_FOLDER
    os.makedirs(agent_dir, exist_ok=True)
    file_path = os.path.join(agent_dir, safe_name)

    try:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(code)
    except Exception as e:
        return {"success": False, "error": "Failed to write file: %s" % e}

    output = ""
    if run:
        try:
            if run_prefix:
                cmd = run_prefix + [file_path]
                result = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=30,
                    cwd=agent_dir,
                )
            else:
                result = subprocess.run(
                    file_path, capture_output=True, text=True, timeout=30,
                    shell=True, cwd=agent_dir,
                )
            output = (result.stdout + result.stderr).strip()
        except subprocess.TimeoutExpired:
            output = "[Timed out after 30s]"
        except Exception as e:
            output = "[Run error: %s]" % e

    return {
        "success": True,
        "path": file_path,
        "filename": safe_name,
        "language": ext.lstrip("."),
        "output": output,
    }


# ── Auto-detect file writes in AI responses ───────────

# Matches ```lang\n# filename.ext  or  ```lang:filename.ext  or  ```filename.ext
_FILE_BLOCK_RE = re.compile(
    r"```(\w+)?\s*\n"                        # opening fence with optional language
    r"(?:#\s*(\S+\.\w+)\s*\n)?"              # optional  # filename.ext  on first line
    r"([\s\S]*?)"                             # code body
    r"\n```",                                 # closing fence
)

# Patterns in prose that indicate a file path right before a code block
_PROSE_FILE_RE = re.compile(
    r"(?:save|write|create|put)\s+(?:this\s+)?(?:to|in|as|into)\s+[`\"']?(\S+\.\w{1,10})[`\"']?",
    re.IGNORECASE,
)

# Comment-line filename patterns (first line of code block)
_COMMENT_FILE_RE = re.compile(
    r"^(?:#|//|--|/\*)\s*(?:file(?:name)?:?\s*)?(\S+\.\w{1,10})\s*(?:\*/)?$",
    re.MULTILINE,
)


def detect_file_writes(response_text):
    """
    Scan an AI response for code blocks that should be saved to files.
    Returns list of {filename, code, language} dicts.
    """
    response_text = strip_think_blocks(response_text)
    results = []
    seen_files = set()

    # Split into segments around code blocks to check prose context
    parts = re.split(r"(```\w*\s*\n[\s\S]*?\n```)", response_text)

    for i, part in enumerate(parts):
        fence_match = re.match(r"```(\w*)\s*\n([\s\S]*?)\n```$", part)
        if not fence_match:
            continue

        lang = fence_match.group(1) or ""
        code = fence_match.group(2)

        if not code.strip():
            continue

        filename = None

        # Strategy 1: Check for filename comment on first line of code
        first_line = code.split("\n", 1)[0]
        cm = _COMMENT_FILE_RE.match(first_line)
        if cm:
            filename = cm.group(1)
            # Strip the filename comment from the code
            code = code.split("\n", 1)[1] if "\n" in code else ""

        # Strategy 2: Check preceding prose for "save to filename.ext"
        if not filename and i > 0:
            preceding = parts[i - 1]
            # Only check the last ~200 chars of preceding prose
            pm = _PROSE_FILE_RE.search(preceding[-200:])
            if pm:
                filename = pm.group(1)

        if not filename:
            continue

        # Sanitise — only allow basename, no path traversal
        filename = os.path.basename(filename)
        if not filename or filename in seen_files:
            continue

        seen_files.add(filename)
        results.append({
            "filename": filename,
            "code": code.strip(),
            "language": lang or os.path.splitext(filename)[1].lstrip("."),
        })

    return results


def save_file(code, filename):
    """
    Save code to AgentFiles without running it.
    Returns dict with success, path, filename.
    """
    code = clean_code(code)
    if not code:
        return {"success": False, "error": "Empty code"}

    safe_name = re.sub(r"[^\w.\-]", "_", os.path.basename(filename))
    if not safe_name:
        safe_name = "untitled.txt"

    agent_dir = Config.AGENT_FILES_FOLDER
    os.makedirs(agent_dir, exist_ok=True)
    file_path = os.path.join(agent_dir, safe_name)

    try:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(code)
    except Exception as e:
        return {"success": False, "error": "Failed to write: %s" % e}

    return {"success": True, "path": file_path, "filename": safe_name}


# ── Real filesystem operations ─────────────────────────

# Allowed root directories for file operations (security boundary)
_ALLOWED_ROOTS = None


def _get_allowed_roots():
    """Lazily build the set of allowed root directories."""
    global _ALLOWED_ROOTS
    if _ALLOWED_ROOTS is None:
        home = os.path.normcase(os.path.abspath(os.path.expanduser("~")))
        _ALLOWED_ROOTS = [
            os.path.normcase(os.path.abspath(Config.AGENT_FILES_FOLDER)),
            os.path.join(home, os.path.normcase("desktop")),
            os.path.join(home, os.path.normcase("documents")),
            os.path.join(home, os.path.normcase("downloads")),
        ]
        # Also allow the workspace tree
        workspace = os.path.normcase(os.path.abspath(
            os.path.join(os.path.dirname(os.path.dirname(__file__)), "..")
        ))
        _ALLOWED_ROOTS.append(workspace)
    return _ALLOWED_ROOTS


def _validate_path(file_path):
    """
    Validate and resolve a file path. Returns (resolved_path, error).
    Blocks path traversal and access outside allowed roots.
    """
    if not file_path or not file_path.strip():
        return None, "Empty file path"

    # Resolve relative paths against _BASE_DIR (the axon/ folder)
    if not os.path.isabs(file_path):
        base = os.path.dirname(Config.AGENT_FILES_FOLDER)  # axon/
        resolved = os.path.normcase(os.path.abspath(
            os.path.join(base, file_path)
        ))
    else:
        resolved = os.path.normcase(os.path.abspath(file_path))

    # Block path traversal
    allowed = _get_allowed_roots()
    if not any(resolved.startswith(root) for root in allowed):
        return None, "Access denied: path is outside allowed directories"

    return resolved, None


def read_file_from_disk(file_path):
    """
    Actually read a file from disk and return its contents.
    Returns dict with success, path, content, size.
    """
    resolved, err = _validate_path(file_path)
    if err:
        return {"success": False, "error": err}

    if not os.path.exists(resolved):
        return {"success": False, "error": "File not found: %s" % file_path}

    if not os.path.isfile(resolved):
        return {"success": False, "error": "Not a file: %s" % file_path}

    try:
        with open(resolved, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        # Truncate very large files
        truncated = len(content) > 50000
        if truncated:
            content = content[:50000]
        return {
            "success": True,
            "path": resolved,
            "content": content,
            "size": os.path.getsize(resolved),
            "truncated": truncated,
        }
    except Exception as e:
        return {"success": False, "error": "Failed to read: %s" % e}


def write_file_to_disk(file_path, content):
    """
    Actually write content to a file on disk.
    Returns dict with success, path, bytes_written.
    """
    resolved, err = _validate_path(file_path)
    if err:
        return {"success": False, "error": err}

    # Create parent directory if needed
    parent = os.path.dirname(resolved)
    try:
        os.makedirs(parent, exist_ok=True)
    except Exception as e:
        return {"success": False, "error": "Cannot create directory: %s" % e}

    try:
        with open(resolved, "w", encoding="utf-8") as f:
            f.write(content)
        return {
            "success": True,
            "path": resolved,
            "bytes_written": len(content.encode("utf-8")),
        }
    except Exception as e:
        return {"success": False, "error": "Failed to write: %s" % e}


def list_directory(dir_path):
    """
    List contents of a directory.
    Returns dict with success, path, entries.
    """
    resolved, err = _validate_path(dir_path)
    if err:
        return {"success": False, "error": err}

    if not os.path.isdir(resolved):
        return {"success": False, "error": "Not a directory: %s" % dir_path}

    try:
        entries = []
        for name in sorted(os.listdir(resolved)):
            full = os.path.join(resolved, name)
            entries.append({
                "name": name,
                "is_dir": os.path.isdir(full),
                "size": os.path.getsize(full) if os.path.isfile(full) else 0,
            })
        return {"success": True, "path": resolved, "entries": entries}
    except Exception as e:
        return {"success": False, "error": "Failed to list: %s" % e}


# ── Detect file-operation intent in user messages ──────

_READ_PATTERNS = [
    re.compile(r"(?:read|open|show|display|cat|view|print|load|get)\s+(?:me\s+)?(?:the\s+)?(?:file\s+|contents?\s+of\s+)?[`\"']?([\w./\\:\-]+\.[a-zA-Z0-9]{1,10})[`\"']?", re.IGNORECASE),
    re.compile(r"what(?:'s| is) in [`\"']?([\w./\\:\-]+\.[a-zA-Z0-9]{1,10})[`\"']?", re.IGNORECASE),
]

_WRITE_PATTERNS = [
    re.compile(r"(?:write|save|create|make|put|update|edit|modify|change|add)\s+(?:a\s+)?(?:file\s+)?(?:to|called|named)?\s*[`\"']?([\w./\\:\-]+\.[a-zA-Z0-9]{1,10})[`\"']?", re.IGNORECASE),
    re.compile(r"(?:write|save|create|put)\s+(?:this\s+)?(?:to|into|in)\s+[`\"']?([\w./\\:\-]+\.[a-zA-Z0-9]{1,10})[`\"']?", re.IGNORECASE),
]

_LIST_PATTERNS = [
    re.compile(r"(?:list|ls|dir|show)\s+(?:the\s+)?(?:files?\s+in\s+|contents?\s+of\s+)?(?:directory\s+|folder\s+)?[`\"']?([\w./\\:\-]+)[`\"']?", re.IGNORECASE),
]

_CALC_PATTERNS = [
    re.compile(r"(?:calculate|compute|evaluate|solve|what is|what's)\s+(.+)", re.IGNORECASE),
    re.compile(r"^([\d][\d\s\+\-\*/\(\)\.%\^]+)$", re.MULTILINE),
]

_SEARCH_PATTERNS = [
    re.compile(r"(?:search\s+(?:for|the\s+web)|look\s+up|find\s+(?:information|info)\s+(?:about|on)|google|search\s+online)\s+(.+)", re.IGNORECASE),
]


def detect_file_intent(message):
    """
    Detect agent intent in a user message.
    Returns dict with 'type' (read/write/list/calculate/web_search/none) and details.
    """
    msg = message.strip()

    # Check for read intent
    for pat in _READ_PATTERNS:
        m = pat.search(msg)
        if m:
            return {"type": "read", "path": m.group(1)}

    # Check for write intent — only detect the path, content comes from AI
    for pat in _WRITE_PATTERNS:
        m = pat.search(msg)
        if m:
            return {"type": "write", "path": m.group(1)}

    # Check for list intent
    for pat in _LIST_PATTERNS:
        m = pat.search(msg)
        if m:
            path = m.group(1)
            # Only if it looks like a directory (no extension or ends with / or \)
            if not re.search(r"\.[a-zA-Z0-9]{1,5}$", path) or path.endswith(("/", "\\")):
                return {"type": "list", "path": path}

    # Check for calculate intent
    for pat in _CALC_PATTERNS:
        m = pat.search(msg)
        if m:
            expr = m.group(1).strip()
            # Only if expression contains at least one operator and a digit
            if re.search(r"\d", expr) and re.search(r"[\+\-\*/\%\^]", expr):
                # Convert ^ to ** for Python
                expr = expr.replace("^", "**")
                return {"type": "calculate", "expression": expr}

    # Check for web search intent
    for pat in _SEARCH_PATTERNS:
        m = pat.search(msg)
        if m:
            return {"type": "web_search", "query": m.group(1).strip()}

    return {"type": "none"}


# ── Safe calculator ────────────────────────────────────

_CALC_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _safe_eval_node(node):
    """Recursively evaluate an AST node containing only numbers and arithmetic."""
    if isinstance(node, ast.Expression):
        return _safe_eval_node(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.UnaryOp) and type(node.op) in _CALC_OPS:
        return _CALC_OPS[type(node.op)](_safe_eval_node(node.operand))
    if isinstance(node, ast.BinOp) and type(node.op) in _CALC_OPS:
        left = _safe_eval_node(node.left)
        right = _safe_eval_node(node.right)
        if isinstance(node.op, ast.Pow) and right > 1000:
            raise ValueError("Exponent too large")
        return _CALC_OPS[type(node.op)](left, right)
    raise ValueError("Unsupported expression")


def safe_calculate(expression):
    """
    Safely evaluate an arithmetic expression.
    Only allows numbers and basic math operators (+, -, *, /, //, %, **).
    Returns dict with success, expression, result.
    """
    expression = expression.strip()
    if not expression:
        return {"success": False, "error": "Empty expression"}
    try:
        tree = ast.parse(expression, mode="eval")
        result = _safe_eval_node(tree)
        return {
            "success": True,
            "expression": expression,
            "result": str(result),
        }
    except ZeroDivisionError:
        return {"success": False, "error": "Division by zero"}
    except Exception as e:
        return {"success": False, "error": "Cannot compute: %s" % e}
