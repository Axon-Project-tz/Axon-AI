"""
router.py — Fast rule-based slot routing for Axon.
No AI calls; pure Python string/regex matching.
detect_slot() is safe to call on every message — it never crashes.
"""

import re

# Slots 5, 6 are "Unrestricted" and slot 7 is "Roblox" — never auto-route into or away from them
_UNRESTRICTED_SLOTS = frozenset((5, 6, 7))

# Any slot the user manually selected (not Chat/slot 1) is considered locked.
# Auto-routing only upgrades from slot 1 — it never overrides an explicit user choice.
_LOCKED_SLOTS = frozenset((2, 3, 4, 5, 6, 7, 8, 9))

# ── Pattern compilations ──────────────────────────────

_VISION_PATTERNS = re.compile(
    r'\b(look at (this|the|my)\b'
    r'|what (do you see|can you see)\b'
    r'|what.?s in (this|the) (image|photo|picture|screenshot|pic)\b'
    r'|(analyze|describe|explain|read|transcribe|summarize) (this|the|my) (image|photo|picture|screenshot|pic)\b'
    r'|what (is|does) (this|the) (image|photo|picture|screenshot) (show|say|contain|depict)\b'
    r'|is there .{0,40} (image|photo|picture|screenshot))',
    re.I,
)

_CODING_PATTERNS = re.compile(
    # Code fences — very strong signal
    r'```'
    # Python/JS/TS function and class definitions
    r'|\bdef\s+\w+\s*\('
    r'|\bclass\s+\w+[\s(:{]'
    r'|\bfunction\s+\w+\s*\('
    r'|\(\s*\)\s*=>'           # arrow functions
    # Variable declarations with assignment (JS/TS)
    r'|\b(?:const|let|var)\s+\w+\s*='
    # Python from/import with real module names
    r'|\bfrom\s+\w+\s+import\s+\w+'
    r'|\bimport\s+(?:os|sys|re|json|math|numpy|pandas|flask|react|express|torch|requests|datetime|pathlib|urllib|asyncio|typing|dataclasses)\b'
    # Explicit coding requests
    r'|\b(?:write|generate|create|fix|debug|refactor|implement|optimize)\s+(?:a\s+|an\s+|the\s+|this\s+|my\s+)?'
    r'(?:python|javascript|typescript|sql|bash|shell|powershell|html|css|java|cpp|rust|go|ruby|php|swift)\b'
    r'|\b(?:write|generate|create|fix|debug|refactor|implement|optimize)\s+(?:a\s+|an\s+|the\s+|this\s+|my\s+)?'
    r'(?:code|function|script|program|class|method|query|endpoint|api|component|algorithm|loop|regex|snippet)\b'
    # Generic code subject phrases
    r'|\b(?:code|function|script|program)\s+(?:that|to|which|for)\b'
    # Common runtime errors
    r'|\b(?:syntax error|type error|name error|key error|index error|attribute error|import error|runtime error)\b'
    # "how do I code/program/implement"
    r'|\bhow (?:do i|to)\s+(?:code|program|implement|build)\b',
    re.I,
)

_REASONING_PATTERNS = re.compile(
    r'\bexplain (?:why|how|the (?:difference|reason))\b'
    r'|\bwhat.?s the difference between\b'
    r'|\bpros and cons\b'
    r'|\bshould i\b.{0,60}\?'        # "should I X?" questions
    r'|\bhelp me decide\b'
    r'|\bthink (?:through|this) (?:through)?\b'
    r'|\bstep[- ]by[- ]step\b'
    r'|\b(?:prove|disprove) (?:that|this)\b'
    r'|\b(?:solve|work out|figure out) (?:this|the) (?:problem|equation|puzzle|challenge|question)\b'
    r'|\bmath(?:ematics)? problem\b'
    r'|\b(?:calculate|compute|evaluate)\b.{0,40}\?'
    r'|\bcompare (?:and contrast\b|the\b|these\b|those\b)'
    r'|\btrade.?offs?\b'
    r'|\bweigh (?:the|my|these|those) (?:options|pros|choices|tradeoffs)\b'
    r'|\banalyz(?:e|ing) (?:the |this |my )?(?:problem|situation|issue|approach|options?|data|question)\b'
    r'|\bwhat are the implications\b'
    r'|\bgive me (?:a |your )?(?:analysis|reasoning|breakdown|assessment)\b'
    r'|\b(?:logical|logically)\b'
    r'|\bcomplex (?:question|problem|topic)\b',
    re.I,
)


# ── Public API ────────────────────────────────────────

def detect_slot(message, attached_file=None, attached_image=None, current_slot_id=1):
    """
    Return the recommended slot_id (int) for the given message.

    Rules (first match wins):
      1. If current slot is 5 or 6 (Unrestricted), return it unchanged.
      2. Attached image → slot 2 (Vision).
      3. Explicit visual language → slot 2 (Vision).
      4. Code patterns / coding request → slot 3 (Coding).
      5. Analytical / reasoning keywords → slot 4 (Reasoning).
      6. Long complex question heuristic → slot 4 (Reasoning).
      7. Default → slot 1 (Chat).

    Never raises — returns current_slot_id on any error.
    """
    try:
        # Guard: user chose a specific slot — never override their manual selection.
        # Auto-routing only runs when on slot 1 (Chat, the generic slot).
        if current_slot_id in _LOCKED_SLOTS:
            return current_slot_id

        # ── From here we are on slot 1 (Chat) — try to upgrade ──

        # Vision: actual image attached → always upgrade to vision slot
        if attached_image:
            return 2

        # Vision: explicit visual language in text
        if _VISION_PATTERNS.search(message):
            return 2

        # Coding: code syntax or coding action verbs
        if _CODING_PATTERNS.search(message):
            return 3

        # Reasoning: analytical / decision keywords
        if _REASONING_PATTERNS.search(message):
            return 4

        # Reasoning heuristic: long question (> 200 chars) with a question mark
        if len(message) > 200 and '?' in message:
            return 4

        # Default: stay on Chat
        return 1

    except Exception:
        return current_slot_id



def detect_intent(message):
    """Detect the intent/category of a user message."""
    pass
