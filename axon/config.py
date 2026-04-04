"""
config.py — Central configuration for Axon.
All settings, model slots, feature toggles, and paths.
"""


import os as _os

from dotenv import load_dotenv as _load_dotenv

_BASE_DIR = _os.path.dirname(_os.path.abspath(__file__))
_load_dotenv(_os.path.join(_BASE_DIR, ".env"))


class Config:
    # LM Studio
    LM_STUDIO_URL = "http://127.0.0.1:1234/v1"
    LM_STUDIO_API_KEY = "lm-studio"  # LM Studio doesn't need a real key

    # Tavily search API
    TAVILY_API_KEY = _os.getenv("TAVILY_API_KEY", "")

    # Feature toggles — all True by default, user can turn off in settings
    ENABLE_MEMORY = True
    ENABLE_RAG = True
    ENABLE_VOICE = True
    ENABLE_AGENT = True
    ENABLE_DEEPTHINK = True
    ENABLE_AUTO_ROUTING = True

    # Python executable — used by agent mode for running scripts
    PYTHON_EXE = _os.path.join(
        _os.path.expanduser("~"),
        "AppData", "Local", "Programs", "Python", "Python311", "python.exe",
    )

    # Paths — absolute, anchored to the axon/ project directory
    UPLOAD_FOLDER = _os.path.join(_BASE_DIR, "uploads")
    VECTOR_STORE_FOLDER = _os.path.join(_BASE_DIR, "vector_store")
    DATABASE_FOLDER = _os.path.join(_BASE_DIR, "database")
    AGENT_FILES_FOLDER = _os.path.join(
        _os.path.expanduser("~"), "Desktop", "AgentFiles"
    )

    # Model slots — 6 slots, each with name, model_id, style, accent color
    MODEL_SLOTS = [
        {
            "id": 1,
            "name": "Chat",
            "model_id": "meta-llama-3.1-8b-instruct",
            "style": "deepseek",
            "accent": "#3B82F6",  # Blue
            "description": "Casual conversation, fast replies"
        },
        {
            "id": 2,
            "name": "Vision",
            "model_id": "qwen2.5-vl-7b-instruct",
            "style": "deepseek",
            "accent": "#22C55E",  # Green
            "description": "Image reading and analysis"
        },
        {
            "id": 3,
            "name": "Coding",
            "model_id": "qwen2.5-coder-32b-instruct",
            "style": "deepseek",
            "accent": "#A855F7",  # Purple
            "description": "Best open source coding model"
        },
        {
            "id": 4,
            "name": "Reasoning",
            "model_id": "qwen/qwq-32b",
            "style": "deepseek",
            "accent": "#F59E0B",  # Amber
            "description": "Deep thinking and logic"
        },
        {
            "id": 5,
            "name": "Unrestricted",
            "model_id": "dolphin3.0-llama3.1-8b",
            "style": "wormgpt",
            "accent": "#EF4444",  # Red
            "description": "No filter, light and fast"
        },
        {
            "id": 6,
            "name": "Unrestricted+",
            "model_id": "dolphin-2.9.2-mixtral-8x22b",
            "style": "wormgpt",
            "accent": "#991B1B",  # Dark Red
            "description": "No filter, smarter but slower"
        },
        {
            "id": 7,
            "name": "Roblox",
            "model_id": "r1-distill-qwen-14b-roblox-luau",
            "style": "deepseek",
            "accent": "#FF6B35",  # Roblox Orange
            "description": "Roblox game dev — Luau scripting & Studio"
        },
        {
            "id": 8,
            "name": "Gemma 4 E2B",
            "model_id": "gemma4:e2b",
            "style": "gemma4",
            "accent": "#00BFA5",  # Teal/Cyan
            "description": "7.2 GB • Lightweight / Edge / On-device (Text, Image, Audio) • Context: 128K",
            "capabilities": {
                "vision": True,
                "audio": True,
                "thinking": True,
                "context_window": 131072,
                "size_gb": 7.2
            },
            "sampling": {
                "temperature": 1.0,
                "top_p": 0.95,
                "top_k": 64
            }
        },
        {
            "id": 9,
            "name": "Gemma 4 26B",
            "model_id": "gemma4:26b",
            "style": "gemma4",
            "accent": "#3D5AFE",  # Indigo/Teal Darker
            "description": "18 GB • Workstation / Frontier Intelligence (Text, Image) • Context: 256K",
            "capabilities": {
                "vision": True,
                "audio": False,
                "thinking": True,
                "context_window": 262144,
                "size_gb": 18.0
            },
            "sampling": {
                "temperature": 1.0,
                "top_p": 0.95,
                "top_k": 64
            }
        }
    ]
