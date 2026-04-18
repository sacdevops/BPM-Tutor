# Agentic Process Modeling Tool

A research prototype for AI-assisted BPMN process modeling. The system employs a single, cohesive autonomous AI agent that generates, refines, and validates BPMN 2.0 diagrams directly in the browser, guided by natural language task descriptions and iterative goal-based planning.

> **Note:** This tool was developed as part of academic research. See the [Citation](#citation) section at the bottom of this document.

---

## Table of Contents

- [Features](#features)
- [Architecture Overview](#architecture-overview)
- [Requirements](#requirements)
- [Setup](#setup)
- [Running the Application](#running-the-application)
- [Usage](#usage)
- [Project Structure](#project-structure)
- [Citation](#citation)

---

## Features

- **Autonomous Agentic Orchestration**: A single AI agent handles planning, executes modeling actions on the BPMN canvas, and performs internal self-reflection to validate outputs.
- **Self-Reflective Iteration**: The agent defines sub-goals, drafts the model, and reviews the draft against semantic and syntactic rules. The agent iterates internally up to three times to resolve detected issues before presenting the final result.
- **Human-in-the-Loop Escalation**: If the agent cannot resolve all issues within the internal loop, the system halts autonomous execution and hands control back to the user for targeted feedback.
- **Live BPMN Canvas**: Full bpmn.io modeler running in the browser — the agent creates, updates, and deletes elements in real time.
- **Visual Feedback Markers**: Structural validation of the generated diagram surfaces directly on the canvas using severity-graded visual markers (Info / Warning / Critical).
- **Custom Tasks**: Upload your own process description (`.txt`, `.md`, `.pdf`, `.docx`) or type instructions directly.
- **Conversational Q&A**: Ask the agent conceptual questions about BPMN or the current model without triggering a full re-modeling cycle.
- **Export**: Download the current diagram as a `.bpmn` file at any time.

---

## Architecture Overview

```text
User ──► Autonomous Agent (PLAN → EXECUTE → SELF-REVIEW)
              │
              ▼
         BPMN Canvas (bpmn.io)
```

All LLM input/output uses the custom **LION** serialization format. Designed to be highly compact and LLM-friendly, the notation drastically reduces data usage by 30 to 80 percent compared to conventional JSON files, minimizing context window overhead and latency.

---

## Requirements

- Python 3.10 or higher
- An [OpenAI API key](https://platform.openai.com/account/api-keys)

---

## Setup

### 1. Clone the repository

```bash
git clone [https://github.com/](https://github.com/)<your-username>/<your-repo>.git
cd <your-repo>
```

### 2. Create a virtual environment

```bash
python -m venv venv
```

Activate the virtual environment:

| OS | Command |
|----|---------|
| Windows | `venv\Scripts\activate` |
| macOS / Linux | `source venv/bin/activate` |

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

Create a `.env` file in the project root:

```env
OPENAI_API_KEY=sk-...
GPT_MODEL=gpt-5.2
SECRET_KEY=your-secret-key-here
FLASK_DEBUG=false
```

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENAI_API_KEY` | ✅ | Your OpenAI API key |
| `GPT_MODEL` | ✅ | Model identifier (for example `gpt-5.4`) |
| `SECRET_KEY` | ✅ | Flask session secret — use any long random string |
| `FLASK_DEBUG` | ❌ | Set to `true` for development hot-reload (default: `false`) |

---

## Running the Application

```bash
python main.py
```

The server starts at **http://127.0.0.1:8080**.

Open your browser and navigate to that address to access the task selection screen.

---

## Usage

### 1. Select or create a task

On the home screen you will see a list of predefined modeling tasks. Click **Start** on any task to open the modeling canvas, or use **Custom Task** to supply your own process description.

For custom tasks you can:
- Type or paste a process description directly into the text field.
- Upload a `.txt`, `.md`, `.pdf`, or `.docx` file — the application extracts the text automatically.

### 2. Interact with the AI agent

Once a task is open, the right-hand panel contains the chat interface. The system starts automatically:

- The **Agent** reads your task and defines a set of modeling **goals**.
- The **Agent** executes the goals step by step on the BPMN canvas (you can watch the diagram being built live).
- Upon finishing the draft, the **Agent** conducts an internal self-reflection to detect and fix errors.

You can interact at any point:

| What you want | How |
|---------------|-----|
| Ask a question about BPMN or the diagram | Type and send your message — the agent answers without re-modeling |
| Request a change | Describe the change — a new planning cycle begins |
| Stop the current iteration | Click **Stop** |

### 3. Review the plan panel

The left sidebar shows the current modeling goals and the respective status (`pending` / `in progress` / `complete`). This panel updates in real time as the agent works.

### 4. Inspect validation issues

After the self-reflection phase, any detected issues appear in the **Review** panel below the canvas with severity levels:

| Severity | Meaning |
|----------|---------|
| 🔴 Critical | Structural error or semantic deviation preventing valid BPMN |
| 🟡 Warning | Suboptimal modeling structure needing attention |
| 🔵 Info | Non-mandatory suggestion or best-practice note |

### 5. Complete the task

Click **Confirm Solution** when you are satisfied with the diagram.

- If only informational issues exist (or no issues at all), the task completes immediately and you are returned to the home screen.
- If warnings or critical issues were flagged in the last review, the system blocks the thoughtless completion of the task. A confirmation dialog asks whether you explicitly grant permission to ignore the highlighted issues. You can **Cancel** to continue working or **Confirm** to finish regardless.

### 6. Export

Click the **Export** button at any time to download the current BPMN diagram as an XML file compatible with any BPMN 2.0-compliant tool (for example Camunda Modeler, Signavio, or bpmn.io).

---

## Project Structure

```text
.
├── main.py                  # Flask application entry point
├── config.py                # Environment config & task definitions
├── requirements.txt
├── .env                     # (not committed) API keys & secrets
│
├── app/
│   ├── ai_service.py        # LLM wrappers, LION parsing, action conversion
│   ├── prompts.py           # All system prompts for the single agent
│   ├── sockets/
│   │   └── chat_handler.py  # Socket event handlers and agent orchestration
│   ├── static/
│   │   ├── css/
│   │   └── js/task.js       # Frontend logic, bpmn.io integration
│   └── templates/
│       ├── index.html
│       └── task.html
│
├── lion/                    # LION serialization library
│   ├── encoder.py
│   └── decoder.py
│
├── utils/
│   └── bpmn_validator.py    # Structural BPMN validation
│
└── benchmarks/              # Evaluation harness (not required to run the app)
    ├── runner.py
    ├── bpmn_executor.py
    └── results/             # (not committed) benchmark output files
```

---

## Citation

If you use this tool or build upon the code in your research, please cite the following:

```bibtex
@inproceedings{anonymous2026agentic,
  title     = {[Paper Title Placeholder]},
  author    = {[Author(s) Placeholder]},
  booktitle = {[Conference/Workshop Name Placeholder]},
  year      = {2026},
  note      = {[Additional details placeholder]}
}
```

> **Anonymous review:** Author information will be added after the review process is complete.