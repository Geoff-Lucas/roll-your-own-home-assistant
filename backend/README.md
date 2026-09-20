# Home Organizer — backend

FastAPI + SQLModel (SQLite) backend. See `../PLAN.md` for the overall design.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate   # on the Pi; on Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Optionally copy `.env.example` to `.env` and adjust `HOME_ORGANIZER_DATA_DIR`
to point at the USB3 SSD mount once that's set up.

## Run

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Then check `http://<pi-address>:8000/health` and the interactive API docs at
`http://<pi-address>:8000/docs`.

On first run this creates the SQLite DB (under `data/` by default) and a
Fernet encryption key (under `~/.home_organizer/secret.key` by default) used
to encrypt stored calendar account credentials at rest.
