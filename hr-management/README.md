# HR Management — backend scaffold

FastAPI + Firebase Firestore backend for the WinoSoft HR Management app
(cahier des charges v3.0). This is the initial scaffold: the layered
architecture the spec mandates (`routers/ → services/ → repositories/ →
models.py`), proven end-to-end with a working Module 1 (Authentification)
vertical slice — login, JWT access/refresh tokens, lockout after 5 failed
attempts, and a protected placeholder `/dashboard`. The other 11 modules are
not implemented yet.

Firebase connectivity is **emulator-only** for now — no real Firebase project
or credentials are needed to run this.

## Prerequisites

- Docker + Docker Compose
- (optional, for running outside Docker) [uv](https://docs.astral.sh/uv/) and
  Python 3.12

## Run it

```powershell
Copy-Item .env.example .env
docker compose up --build
```

- App: http://localhost:8000
- Firestore/Auth/Storage emulator UI: http://localhost:4000

Create the first admin user (idempotent — safe to re-run):

```powershell
docker compose exec app uv run python -m scripts.seed
```

Then open http://localhost:8000/login and sign in with `SEED_ADMIN_EMAIL` /
`SEED_ADMIN_PASSWORD` from `.env` (defaults in `.env.example`).

## Run outside Docker

Point at an emulator started separately (`docker compose up firebase-emulators`),
then:

```powershell
uv sync
$env:FIRESTORE_EMULATOR_HOST = "localhost:8080"
uv run uvicorn app.main:app --reload
```

## Tests

Tests require a running emulator and refuse to start otherwise (see
`tests/conftest.py`).

```powershell
docker compose exec app uv run pytest -v
```

Or locally, with the emulator up and `FIRESTORE_EMULATOR_HOST` set:

```powershell
uv run pytest -v
```

## Lint

```powershell
uv run ruff check .
```

## Layout

```
app/
  core/          # settings, JWT/bcrypt, Firestore client, auth dependency
  models.py      # Pydantic document/request shapes — no business logic
  repositories/  # Firestore access only — _uniques/_counters/search_tokens/pagination helpers
  services/      # business rules (auth_service.authenticate, token issuance)
  routers/       # HTTP translation only
  templates/     # Jinja2, Bootstrap 5 (CDN)
scripts/seed.py  # creates the first admin user
tests/           # pytest against the Firestore emulator
```

See `firestore.rules`, `storage.rules`, and `firestore.indexes.json` for the
(currently empty/deny-all) database security and indexing config, versioned
alongside the app per the spec.

## What's deliberately not here yet

The other 11 functional modules (employees, departments, leaves,
certificates, trial periods, notifications, settings, AI assistant, etc.); a
real Firebase project; Fernet encryption for salary/RIB; WeasyPrint PDF
generation; Cloud Functions/scheduled tasks; the full onboarding script
(leave types, Moroccan holidays); Arabic/RTL. See the cahier des charges'
"Points laissés ouverts" for open questions the client still needs to
resolve (target scale, Arabic/RTL scope, Contracts module screens).
