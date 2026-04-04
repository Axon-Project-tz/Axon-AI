"""
llm.py — Handles all communication with LM Studio API.
Responsible for sending messages, streaming responses,
and managing the OpenAI-compatible API connection.
"""

import json
import httpx
from openai import OpenAI, APIConnectionError, APIError
from config import Config

# 10 s to establish the connection; None = wait forever for the first token.
# R1-class models need 60–120 s of thinking time before they start streaming.
_LLM_TIMEOUT = httpx.Timeout(connect=10.0, read=None, write=30.0, pool=10.0)


def _get_client(base_url=None):
    """Create an OpenAI client for the given or default LM Studio URL."""
    url = base_url or Config.LM_STUDIO_URL
    return OpenAI(
        base_url=url,
        api_key=Config.LM_STUDIO_API_KEY,
        timeout=_LLM_TIMEOUT,
    )


def stream_chat(messages, model_id, system_prompt, base_url=None, temperature=0.7, top_p=None, top_k=None):
    """
    Stream a chat completion from LM Studio.
    Yields SSE-formatted strings: 'data: {"token": "..."}'\n\n'
    Ends with 'data: {"done": true}\n\n'
    """
    full_messages = [{"role": "system", "content": system_prompt}] + messages
    client = _get_client(base_url)

    create_kwargs = {
        "model": model_id,
        "messages": full_messages,
        "stream": True,
        "temperature": temperature,
    }
    if top_p is not None:
        create_kwargs["top_p"] = top_p
    
    # Pass extra specific params for models like Gemma 4
    if top_k is not None:
        create_kwargs["extra_body"] = {"top_k": top_k}


    try:
        response = client.chat.completions.create(**create_kwargs)
        for chunk in response:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta and delta.content:
                yield "data: " + json.dumps({"token": delta.content}) + "\n\n"
        yield "data: " + json.dumps({"done": True}) + "\n\n"

    except APIConnectionError:
        yield "data: " + json.dumps({
            "error": "Could not reach LM Studio. Make sure it is running."
        }) + "\n\n"
    except APIError as e:
        err_text = str(e).lower()
        _unloaded_signals = (
            "model is not loaded",
            "model not loaded",
            "not currently loaded",
            "model is unloaded",
            "no model is loaded",
            "no model loaded",
            "model not found",
        )
        if any(sig in err_text for sig in _unloaded_signals):
            yield "data: " + json.dumps({
                "error": (
                    "The model for this slot is not loaded in LM Studio.\n"
                    "Please load \u2018" + model_id + "\u2019 in LM Studio and try again."
                ),
                "error_type": "model_unloaded",
                "model_id": model_id,
            }) + "\n\n"
        else:
            yield "data: " + json.dumps({
                "error": "LM Studio error: " + str(e)
            }) + "\n\n"
    except Exception as e:
        yield "data: " + json.dumps({
            "error": "Unexpected error: " + str(e)
        }) + "\n\n"


def complete_chat(messages, model_id, system_prompt, base_url=None):
    """Non-streaming chat completion for internal use. Returns the full text."""
    full_messages = [{"role": "system", "content": system_prompt}] + messages
    client = _get_client(base_url)
    try:
        response = client.chat.completions.create(
            model=model_id,
            messages=full_messages,
            stream=False,
            temperature=0.3,
        )
        return response.choices[0].message.content or ""
    except Exception:
        return ""


def check_connection(base_url=None):
    """Check if LM Studio is reachable. Returns True/False."""
    try:
        client = _get_client(base_url)
        client.models.list()
        return True
    except Exception:
        return False


def _lm_base(base_url=None):
    """Strip /v1 suffix to get the LM Studio root URL."""
    url = (base_url or Config.LM_STUDIO_URL).rstrip("/")
    if url.endswith("/v1"):
        url = url[:-3]
    return url


def unload_other_models(target_model_id, base_url=None):
    """
    Unload every model currently loaded in LM Studio except target_model_id.
    Uses the LM Studio /api/v0/ management API. Best-effort — never raises.
    """
    base = _lm_base(base_url)
    try:
        resp = httpx.get(base + "/api/v0/models", timeout=5.0)
        if resp.status_code != 200:
            return
        for m in resp.json().get("data", []):
            mid = m.get("id") or m.get("model_id") or ""
            state = m.get("state", "")
            # Only unload models that are actually loaded and aren't the target
            if mid and mid != target_model_id and state in ("loaded", "loading"):
                httpx.post(
                    base + "/api/v0/models/unload",
                    json={"identifier": mid},
                    timeout=15.0,
                )
    except Exception:
        pass  # best-effort — never block chat
