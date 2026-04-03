"""
lm_client.py — Direct LM Studio streaming client for Axon CLI.

Bypasses Flask entirely; talks straight to LM Studio's OpenAI-compatible API.
"""

import httpx

LM_STUDIO_BASE = "http://127.0.0.1:1234/v1"
LM_STUDIO_CHAT = LM_STUDIO_BASE + "/chat/completions"

MODEL_SLOTS = {
    1: {"name": "Chat",          "model_id": "meta-llama-3.1-8b-instruct"},
    2: {"name": "Vision",        "model_id": "qwen2.5-vl-7b-instruct"},
    3: {"name": "Coding",        "model_id": "qwen2.5-coder-32b-instruct"},
    4: {"name": "Reasoning",     "model_id": "qwen/qwq-32b"},
    5: {"name": "Unrestricted",  "model_id": "dolphin3.0-llama3.1-8b"},
    6: {"name": "Unrestricted+", "model_id": "dolphin-2.9.2-mixtral-8x22b"},
    7: {"name": "Roblox",        "model_id": "r1-distill-qwen-14b-roblox-luau"},
}


def slot_info(slot: int) -> dict:
    """Return {'name': ..., 'model_id': ...} for a slot number."""
    return MODEL_SLOTS.get(slot, MODEL_SLOTS[1])


def check_lm_studio() -> bool:
    """Return True if LM Studio is reachable."""
    try:
        r = httpx.get(LM_STUDIO_BASE + "/models", timeout=3.0)
        return r.status_code == 200
    except Exception:
        return False


def stream_completion(messages: list, slot: int = 1, temperature: float = 0.7):
    """
    POST to LM Studio with stream=True.
    Yields (token_str, finish_reason|None) tuples as they arrive.
    """
    info = slot_info(slot)
    payload = {
        "model": info["model_id"],
        "messages": messages,
        "temperature": temperature,
        "stream": True,
    }
    with httpx.Client(timeout=httpx.Timeout(connect=10.0, read=300.0, write=30.0, pool=10.0)) as client:
        with client.stream("POST", LM_STUDIO_CHAT, json=payload) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line.startswith("data: "):
                    continue
                data = line[6:]
                if data.strip() == "[DONE]":
                    return
                import json
                try:
                    chunk = json.loads(data)
                except (json.JSONDecodeError, ValueError):
                    continue
                delta = chunk.get("choices", [{}])[0].get("delta", {})
                token = delta.get("content", "")
                finish = chunk.get("choices", [{}])[0].get("finish_reason")
                if token:
                    yield token, finish


def blocking_completion(messages: list, slot: int = 1, temperature: float = 0.7) -> str:
    """Non-streaming completion. Returns the full response text."""
    info = slot_info(slot)
    payload = {
        "model": info["model_id"],
        "messages": messages,
        "temperature": temperature,
        "stream": False,
    }
    with httpx.Client(timeout=httpx.Timeout(connect=10.0, read=300.0, write=30.0, pool=10.0)) as client:
        resp = client.post(LM_STUDIO_CHAT, json=payload)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]
