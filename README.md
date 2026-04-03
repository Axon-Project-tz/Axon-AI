# Axon AI 🧠

![Axon AI Banner](https://img.shields.io/badge/Status-Active-brightgreen) ![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue) ![Flask](https://img.shields.io/badge/Framework-Flask-black?logo=flask) ![License](https://img.shields.io/badge/License-MIT-blue.svg)

**Axon AI** is a powerful, fully-local, and highly modular AI chat interface designed to act as your personal AI control center. Built to deliver a ChatGPT-like experience with zero telemetry, complete privacy, and advanced local capabilities like RAG, deep research, voice interactions, and specialized agent modes.

Axon interfaces directly with local LLMs (Large Language Models) via [LM Studio](https://lmstudio.ai/)'s OpenAI-compatible REST API, keeping all data securely on your machine.

---

## 🌟 Key Features

- **100% Local & Private:** No data ever leaves your machine. Your chats, files, and voice inputs are processed locally.
- **Deep Research & DeepThink:** Advanced multi-source web synthesis utilizing DuckDuckGo Search API for real-time information gathering.
- **RAG & Document Chat:** Upload PDFs, Word docs, text files, and code. Processed locally via ChromaDB to provide accurate contextual answers.
- **Persistent Memory:** Axon remembers your preferences and past context across sessions using a local SQLite database.
- **Voice Capabilities:** Features localized Speech-to-Text (Whisper) and Text-to-Speech (pyttsx3 / Piper) for hands-free interactions.
- **6 Configurable Model Slots:** Set up unique, dedicated LLM models for specific tasks (e.g., General Chat, Vision parsing, Coding).
- **Specialized Agents:** Includes specialized multi-step agents (like the Roblox Agent) capable of complex task execution.
- **Modular & Configurable:** Every feature has an on/off toggle. You control what runs and how it behaves.

---

## 🛠 Tech Stack

| Component | Technology |
| :--- | :--- |
| **Backend Framework** | Python 3.11+ with Flask |
| **Frontend UI** | HTML5, CSS3, Vanilla JS (Clean, dependency-light) |
| **AI Inference** | LM Studio (Local OpenAI-compatible REST API) |
| **Memory & Storage** | SQLite |
| **Vector DB (RAG)** | ChromaDB |
| **Voice Processing** | OpenAI Whisper (STT) + pyttsx3/Piper (TTS) |
| **Document Parsing** | PyMuPDF (PDF), python-docx (Word) |

---

## 📋 Prerequisites

Before starting, ensure you have the following installed:
1. **[Python 3.11+](https://www.python.org/downloads/)**
2. **[Git](https://git-scm.com/)**
3. **[LM Studio](https://lmstudio.ai/)** (Running and serving models locally on port `1234`)

---

## 🚀 Installation & Setup

**1. Clone the repository**
```bash
git clone https://github.com/Axon-Project-tz/Axon-AI.git
cd Axon-AI
```

**2. Create a Virtual Environment**
```bash
python -m venv .venv

# On Windows:
.venv\Scripts\activate
# On macOS/Linux:
source .venv/bin/activate
```

**3. Install Dependencies**
```bash
cd axon
pip install -r requirements.txt
```

**4. Set up LM Studio**
* Open LM Studio.
* Download your preferred instruction-tuned models (e.g., Llama-3 8B, Qwen2-VL).
* Start the Local Server in LM Studio (ensure it's running on `http://localhost:1234/v1`).

---

## 💻 Running Axon

You can start the Axon web server by utilizing the provided batch file or manually running the Flask app:

**Option 1: Using the Batch Script (Windows)**
Simply run the included batch file at the root of the project:
```bash
START_AXON.bat
```

**Option 2: Manual Start**
Make sure your virtual environment is active, then run:
```bash
cd axon
python app.py
```

*The interface will be available in your browser at `http://127.0.0.1:5000` (or the respective local network IP).*

---

## 📂 Project Structure Overview

```text
Axon-AI/
├── axon/
│   ├── app.py              # Main Flask application entry point
│   ├── config.py           # Application settings and toggles
│   ├── core/               # Core engine (Agents, Deep Research, RAG, Memory, etc.)
│   ├── models/             # Slot configurations and system prompts
│   ├── static/             # Frontend assets (CSS, JS, Icons)
│   ├── templates/          # HTML views and components
│   ├── database/           # SQLite databases (chats, explicit memory)
│   └── vector_store/       # Local ChromaDB instance for indexing
├── cli/                    # Experimental CLI & TUI modes
└── START_AXON.bat          # Startup script
```

---

## 🎯 Philosophy

Axon is built under a strict philosophy:
* **The User is in Control:** No features are forced. If you just want a raw LLM interface, you can toggle off memory, tools, and RAG.
* **Clean & Maintainable:** Features are built independently to prevent regressions.
* **Grow Naturally:** The application is architected to be expanded (Phase 2 features) without rewriting the core engine.

---

## 📜 License

This project is open-source and available under the MIT License. Feel free to fork, modify, and improve!
