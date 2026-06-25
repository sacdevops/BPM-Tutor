# BPM-Tutor

A web-based learning platform for Business Process Modeling (BPMN) with AI tutoring agents. Students model BPMN processes in the browser while interacting with configurable AI agents — Mentor, Colleague, Supervisor, Assistant, or Delegant — that guide them through the task via chat.

Designed for use in university courses and empirical research studies. Supports within- and between-subjects experimental designs, survey pipelines, and full data export.

---

## Features

- **In-browser BPMN modeling** — powered by [bpmn.io](https://bpmn.io/)
- **Five AI agent roles** — each with configurable prompts, memory, and interaction style
- **Research study management** — within- and between-subjects designs, multi-step flows, condition assignment, leaderboard
- **Survey system** — multi-page surveys with Likert scales, radio buttons, free text, and more
- **Grading** — manual and AI-assisted grading with inline BPMN annotations
- **Analytics & export** — per-study ZIP export (participants, surveys, task submissions, step timings, LLM interaction logs, BPMN files)
- **Interaction tracking** — optional cursor, BPMN change, and chat event recording
- **Bilingual UI** — English and German (extensible via the admin panel)
- **Admin CMS** — full configuration without code changes (agents, tasks, users, settings, backups)

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11, Flask, Flask-SocketIO (gevent) |
| Database | SQLite (WAL mode) |
| Message queue | Redis (optional — required for multi-worker) |
| AI API | OpenAI-compatible endpoint (CampusKI by default) |
| Server | Gunicorn + geventwebsocket worker |
| Reverse proxy | nginx |
| Container | Docker + Docker Compose |

---

## Quick Start (Docker)

### 1. Clone and configure

```bash
git clone <repo-url>
cd BPM-Tutor
```

Create a `.env` file in the project root:

```dotenv
# Required
SECRET_KEY=change-me-to-a-long-random-string

# Optional — defaults shown
FLASK_DEBUG=false
DEFAULT_LANGUAGE=en
LOG_LLM_IO=false
```

> **Note:** The AI endpoint URL, API key, and mail settings can be configured at runtime via **Admin → Settings** — no rebuild required.

### 2. Start the stack

```bash
docker compose up -d
```

The application is available at **http://localhost:5001**.

### 3. Seed the database

Run once after the first start (or after a factory reset):

```bash
docker compose exec app python deploy/seed.py
```

This creates:
- All database tables
- Default system settings
- EN/DE language entries
- 5 built-in BPMN tasks
- 5 built-in AI agent types
- A default admin account

Default admin credentials (override via environment variables):

| Variable | Default |
|---|---|
| `ADMIN_EMAIL` | `admin@bpmtutor.local` |
| `ADMIN_USERNAME` | `admin` |
| `ADMIN_PASSWORD` | `admin1234!` |

Change the password immediately after first login via **Admin → Users**.

---

## Configuration Reference

All settings are read from environment variables (`.env` file or server environment).

### Application

| Variable | Default | Description |
|---|---|---|
| `SECRET_KEY` | *(required)* | Flask session signing key — use a long random string |
| `FLASK_DEBUG` | `false` | Enable debug mode (never use in production) |
| `DEFAULT_LANGUAGE` | `en` | Default interface language (`en` or `de`) |
| `LOG_LLM_IO` | `false` | Log full LLM prompt/response pairs to the console |

### Database

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `sqlite:///data/bpmtutor.db` | SQLAlchemy database URL |

### Redis (optional)

| Variable | Default | Description |
|---|---|---|
| `REDIS_URL` | *(unset)* | Redis connection string, e.g. `redis://redis:6379/0`. Required when running multiple Gunicorn workers or Celery tasks. |

### Mail (optional)

Mail settings can also be configured at runtime via **Admin → Settings**.

| Variable | Default | Description |
|---|---|---|
| `MAIL_SERVER` | `localhost` | SMTP server hostname |
| `MAIL_PORT` | `587` | SMTP port |
| `MAIL_USE_TLS` | `true` | Enable STARTTLS |
| `MAIL_USERNAME` | *(unset)* | SMTP username |
| `MAIL_PASSWORD` | *(unset)* | SMTP password |
| `MAIL_DEFAULT_SENDER` | `noreply@bpmtutor.local` | From address |

### CORS (optional)

| Variable | Default | Description |
|---|---|---|
| `CORS_ALLOWED_ORIGINS` | `*` | Comma-separated list of allowed WebSocket origins |

---

## Deployment Notes

### Ports

The nginx reverse proxy listens on port **5001** by default. To change this, edit `docker-compose.yml`:

```yaml
ports:
  - "8080:80"   # host:container
```

### HTTPS

HTTPS termination is handled externally (nginx upstream proxy, load balancer, or Cloudflare). Set `FORCE_HTTPS=true` in the app environment only if the application itself must redirect HTTP → HTTPS.

### Code updates (no rebuild needed)

Source code is bind-mounted into the container. After `git pull`, restart the app service:

```bash
git pull
docker compose restart app
```

A full rebuild (`docker compose up --build`) is only needed when `requirements.txt` changes.

### Backups

- Automatic and manual database backups can be triggered via **Admin → Settings → Backup**.
- Hot backup: copy `data/bpmtutor.db` while the container is running (SQLite WAL mode is safe for live copies).

---

## Admin CMS

Log in at `/admin` with your admin credentials.

| Section | Description |
|---|---|
| **Tasks** | Create and edit BPMN tasks (title, description, agent, grading, availability) |
| **Agents** | Configure AI agents, prompts (per language), modeling mode, memory |
| **Studies** | Research study management (steps, conditions, tracking, surveys) |
| **Surveys** | Build multi-page surveys with various question types |
| **Users** | Manage accounts, roles, cohorts |
| **Grading** | Review and grade student submissions; trigger AI grading |
| **Analytics** | Submission statistics, per-study export |
| **Settings** | API endpoint, mail, registration, maintenance mode, DB backup/restore |

---

## Development Setup

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux

pip install -r requirements.txt

# Create .env with at minimum: SECRET_KEY=...
python deploy/seed.py           # create DB + seed data
python main.py                  # dev server on http://localhost:5001
```

> The dev server uses Flask's built-in server with SocketIO — suitable for development only.

---

## Project Structure

```
app/
  blueprints/       # Flask blueprints (admin, auth, main, study, survey, user)
  models/           # SQLAlchemy models
  services/         # AI service, session store, BPMN/LION parsers, prompts
  sockets/          # WebSocket handlers (chat, submission manager)
  utils/            # Helpers (crypto, email, i18n, stats, validators, ...)
  static/           # CSS, JS, CMS assets
  templates/        # Jinja2 templates
config.py           # Environment-based configuration
main.py             # WSGI entry point (Gunicorn target: main:app)
deploy/
  seed.py           # Initial database seed
  migrate_schema.py # Schema migration (runs automatically on container start)
lib/
  bpmn/             # BPMN XML validator
  lion/             # LION encoding/decoding (compact process representation)
```
