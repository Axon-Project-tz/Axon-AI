# AXON — Master Context Document for Copilot

## What is Axon?
Axon is a locally hosted AI chat interface built with Python and Flask.
It connects to LM Studio (which runs local LLM models) via its OpenAI-compatible API at `http://localhost:1234/v1`.
The goal is a clean, powerful, personal AI control center — think ChatGPT but fully local, fully private, and far more capable.

## Why we are building it
- Full privacy — nothing leaves the machine
- Full control — no restrictions unless the user wants them
- Modular — every feature can be toggled on or off
- Personal — remembers the user, learns preferences, works across sessions

## Core Philosophy
- Every feature has an on/off toggle in settings — nothing forces itself on the user
- Clean code, one feature at a time, never break what already works
- Mobile accessible on local network from day one
- Built to grow — Phase 2 features will be added later without rewriting anything

---

## Tech Stack
| Layer | Technology |
|---|---|
| Backend | Python 3.11+ with Flask |
| Frontend | HTML + CSS + Vanilla JS (no React, keep it simple) |
| AI Backend | LM Studio via OpenAI-compatible REST API |
| Memory | SQLite (chat history + persistent memory) |
| RAG / Vector DB | ChromaDB (local, no cloud) |
| Voice Input | OpenAI Whisper (local) |
| Voice Output | pyttsx3 or Piper TTS (local) |
| File Parsing | PyMuPDF (PDF), python-docx (Word), built-in (txt, code) |
| Web Search | DuckDuckGo Search API (free, no key needed) |

---

## Folder Structure
```
axon/
├── app.py                  # Flask entry point, routes
├── config.py               # All settings, model slots, toggles
├── requirements.txt        # All Python dependencies
│
├── core/
│   ├── llm.py              # LM Studio API calls, streaming
│   ├── memory.py           # Persistent memory system (SQLite)
│   ├── rag.py              # RAG system (ChromaDB, folder indexing)
│   ├── agent.py            # Agent mode (tool calling logic)
│   ├── deepthink.py        # DeepThink mode (multi-source web synthesis)
│   ├── router.py           # Auto model routing logic
│   ├── voice.py            # Whisper STT + TTS output
│   └── files.py            # File parsing (PDF, docx, txt, code)
│
├── models/
│   └── slots.py            # 6 model slot definitions + system prompts
│
├── database/
│   ├── db.py               # SQLite setup and helpers
│   ├── chats.db            # Chat history (auto created)
│   └── memory.db           # Persistent memory (auto created)
│
├── vector_store/           # ChromaDB files live here (auto created)
│
├── static/
│   ├── css/
│   │   └── style.css       # Main stylesheet (pure black ChatGPT style)
│   ├── js/
│   │   ├── main.js         # Core UI logic
│   │   ├── chat.js         # Chat sending, streaming, history
│   │   ├── sidebar.js      # Sidebar, chat sessions management
│   │   ├── settings.js     # Settings panel, toggles
│   │   ├── voice.js        # Voice input/output UI
│   │   └── upload.js       # File and image upload handling
│   └── icons/              # SVG icons
│
├── templates/
│   ├── index.html          # Main app shell
│   ├── settings.html       # Settings page
│   └── components/
│       ├── sidebar.html    # Chat sidebar component
│       ├── message.html    # Message bubble component
│       └── modals.html     # All modal dialogs
│
└── uploads/                # Temporary uploaded files (auto created)
```

---

## 6 Model Slots

Each slot has:
- A name and purpose
- A hardcoded model ID (user can override in settings)
- A preset system prompt
- A color accent in the UI so the user knows which slot is active

| # | Name | Model ID | Style | Accent Color |
|---|---|---|---|---|
| 1 | Chat | meta-llama/Meta-Llama-3.1-8B-Instruct | DeepSeek official | Blue |
| 2 | Vision | Qwen/Qwen2-VL-7B-Instruct | DeepSeek official | Green |
| 3 | Coding | Qwen/Qwen2.5-Coder-32B-Instruct | DeepSeek official | Purple |
| 4 | Reasoning | Qwen/QwQ-32B | DeepSeek official | Amber |
| 5 | Unrestricted | cognitivecomputations/dolphin-llama3.1-8b | WormGPT style | Red |
| 6 | Unrestricted+ | cognitivecomputations/dolphin-2.9-mixtral-8x22b | WormGPT style | Dark Red |

---

## Features — Phase 1 (build these)

### Core Chat
- Multi-session chat with sidebar (like ChatGPT)
- Streaming responses token by token
- Markdown rendering in messages
- Code blocks with syntax highlighting and copy button
- Per-model system prompt presets + manual editor

### File Handling
- Upload PDF, docx, txt, code files
- AI reads and understands the content
- Image upload for vision slot

### Agent Mode (toggleable)
- Web search via DuckDuckGo
- Run Python code and return results
- Read and write files on the PC
- Calculator / math tool
- Each tool action shows a visible "thinking" indicator in UI

### DeepThink Mode (toggleable)
- User asks a question
- Axon searches multiple web sources
- Scrapes and reads the content
- Synthesizes one clean answer with citations
- Shows sources used

### Persistent Memory (toggleable)
- Stores facts about the user across sessions in SQLite
- Example: remembers name, preferences, ongoing projects
- User can view and delete memories in settings

### RAG — Document Chat (toggleable)
- User points Axon at a folder on their PC
- Axon indexes all documents into ChromaDB
- User can then ask questions across the entire folder

### Voice (toggleable)
- Whisper for speech-to-text input
- pyttsx3 or Piper for text-to-speech output
- Microphone button in chat input

### Auto Model Routing (toggleable)
- Axon reads the user's message
- Automatically picks the best slot
- Example: code question → slot 3, image attached → slot 2
- Shows which slot it picked and why

### Settings Panel
- Toggle every feature on/off
- Edit system prompts per slot
- Edit model IDs per slot
- Set LM Studio URL (default localhost:1234)
- View and manage persistent memories
- View and manage indexed folders (RAG)

---

## Features — Phase 2 (do NOT build yet, just be aware)
- Conversation branching
- Multi-model comparison (same prompt, all slots)
- Canvas / artifacts panel (render HTML, charts)
- Custom agent builder

---

## UI Style
- Pure black background (#000000)
- White text (#FFFFFF) for primary
- Gray (#888888) for secondary text
- Sidebar on the left like ChatGPT
- Chat area in the center
- Input bar fixed at the bottom
- Settings accessible from sidebar bottom
- Mobile responsive from day one (phone on local network)
- Each model slot has a colored dot indicator showing which is active
- No gradients, no heavy animations — clean and fast

---

## API Behavior
All LLM calls go through LM Studio at:
```
http://localhost:1234/v1/chat/completions
```
Use the OpenAI Python SDK with `base_url` pointed at LM Studio.
Always stream responses — never wait for full completion.
Handle connection errors gracefully — show "LM Studio not running" message if unreachable.

---

## Important Rules for Copilot
1. Build one feature at a time — never jump ahead
2. Never hardcode things that belong in config.py
3. Every new feature gets its own file in /core/
4. All toggles live in config.py and are respected everywhere
5. Keep frontend vanilla JS — no React, no Vue, no frameworks
6. Always test that existing features still work after adding new ones
7. Mobile responsive is not optional — build it from the start
8. Never store user data outside the /database/ folder
