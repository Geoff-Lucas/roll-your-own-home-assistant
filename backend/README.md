# Home Organizer — backend

FastAPI + SQLModel (SQLite) backend. See `../PLAN.md` for the overall design
and `../deploy/README.md` for running it on the kiosk.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate   # on Linux; on Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
```

Optionally copy `.env.example` to `.env` and adjust settings (all prefixed
`HOME_ORGANIZER_`, documented in `app/config.py`).

## Run

```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Then check `http://127.0.0.1:8000/api/health` and the interactive API docs at
`http://127.0.0.1:8000/docs`. The API only answers requests addressed to
`localhost` or `127.0.0.1` (see `allowed_hosts` in `app/config.py`), and is
never meant to listen beyond this machine.

On first run this creates the SQLite DB (under `data/` by default), applies
the database migrations (`migrations/`, see `alembic.ini`), and makes a Fernet
encryption key (under `~/.home_organizer/secret.key` by default) used to
encrypt stored calendar account credentials at rest.

## Test

```bash
pytest
```
