# HR Management

A full-stack HR management platform built for **WinoSoft**, covering the
employee lifecycle end to end — from hiring and trial periods to leave,
certificates, and an AI-assisted module for CV import and drafting — on a
strictly layered FastAPI + Firestore backend.

Server-rendered (Jinja2 + Bootstrap 5), content-negotiated (every route
serves JSON or HTML from the same handler), and covered by 160+ automated
tests run against a real Firestore emulator rather than mocks.

## Features

The app implements the 12 functional modules of the WinoSoft cahier des
charges (v3.0):

| # | Module | Highlights |
|---|--------|------------|
| 1 | Authentification | JWT access/refresh tokens, lockout after 5 failed attempts, role-based redirect after login |
| 2 | Tableau de bord | Role-scoped KPIs, alert lists, and charts — Admin sees everything, Manager sees their department, Employé gets a lightweight home page |
| 3 | Gestion du personnel | Employee CRUD with validation, Fernet-encrypted salary/RIB, auto-generated matricule, search/filter/pagination, CSV export |
| 4 | Départements | CRUD with unique codes, delete blocked while employees are attached |
| 5 | Postes | CRUD scoped to a department, optional occupancy cap |
| 6 | Gestion des congés | Request/approve/reject workflow, working-days calculation, balance tracking, role-scoped visibility |
| 7 | Attestations PDF | 5 certificate types generated on demand from a frozen data snapshot — never a stale stored file |
| 8 | Périodes d'essai | Auto-created per employee on hire, validate/extend/refuse workflow, progress tracking |
| 9 | Alertes & notifications | Per-recipient notification center (bell + history), event-driven for leaves and new hires |
| 10 | Design responsive & accessibilité | Mobile-first navigation, confirmation modals, toasts, keyboard-accessible controls |
| 11 | Paramètres | Admin configuration screens — entreprise, congés, utilisateurs |
| 12 | Assistant intelligent | AI-assisted CV import, drafting, and dashboard summaries behind a privacy filter, usage quotas, and an audit log |

**Bonus — predictive attrition model**: a local scikit-learn model (trained
offline, see `ml/`) estimates an employee's attrition risk. It runs entirely
in-process, so no employee data ever leaves the server for this feature.

See `## What's not built yet` below for the parts intentionally left out of
this scope.

## AI, privacy and safety

The Assistant module (Module 12) is off by default and admin-activated. A
few guardrails are worth calling out:

- **Human in the loop** — the assistant only ever *suggests* (a pre-filled
  form, a draft, a dashboard comment); nothing is saved without a human
  reviewing and confirming it.
- **Privacy filter** — a dedicated outbound-payload filter
  (`app/core/ai_privacy.py`) strips sensitive fields (salary, RIB, CNSS,
  CIN, birth date, emergency contact, internal notes) before anything is
  sent to the AI provider.
- **Audit log** — every AI call is logged (author/function/timestamp) —
  never the prompt or response content.
- **Quotas** — configurable per-user daily and global monthly limits.
- **Swappable provider** — the AI client is dependency-injected
  (`app.core.dependencies.get_ai_client`), so the test suite runs entirely
  against a fake client; no test ever calls a real AI API.

## Tech stack

- **Backend**: FastAPI, Pydantic v2, Jinja2, Uvicorn
- **Data**: Firebase Firestore (emulator for local dev, real project as an
  opt-in path)
- **Security**: JWT (python-jose), bcrypt, Fernet field-level encryption
- **AI / ML**: LLM-backed assistant (configurable provider) for CV
  extraction, drafting and summaries; scikit-learn for the attrition model
- **PDF**: WeasyPrint (HTML/CSS → PDF certificates)
- **Infra**: Docker Compose, Firebase Emulator Suite
- **Testing**: pytest (160+ tests against the Firestore emulator)
- **Lint**: ruff

## Architecture

```
routers/  →  services/  →  repositories/  →  Firestore
```

A strict one-way dependency: each layer only knows the layer immediately
below it, which keeps every layer independently testable (services are
tested against fake repositories, no network calls).

## Prerequisites

- Docker + Docker Compose
- (optional, for running outside Docker) [uv](https://docs.astral.sh/uv/)
  and Python 3.12

## Getting started

```powershell
Copy-Item .env.example .env
docker compose up --build
```

- App: http://localhost:8000
- Firestore/Auth/Storage emulator UI: http://localhost:4000

Create the first admin user plus reference data (leave types, fixed
holidays) — idempotent, safe to re-run:

```powershell
docker compose exec app uv run python -m scripts.seed
```

Then open http://localhost:8000/login and sign in with `SEED_ADMIN_EMAIL` /
`SEED_ADMIN_PASSWORD` from `.env` (defaults in `.env.example`).

To enable the AI assistant module, set `ANTHROPIC_API_KEY` in `.env` to your
own key for the configured provider, `docker compose up -d --force-recreate`,
then turn it on via `/settings/ai`. Everything else runs fully offline
against the local emulator.

## Running against real Firestore

A second, opt-in path (`docker-compose.prod.yml`) runs the app against a
real Firestore project instead of the emulator. It never activates by
accident — it's a separate compose file with its own project name
(`hr-management-prod`) and its own env file (`.env.prod`), both gitignored.

Requires a Firebase service-account key (Firebase console → Project
settings → Service accounts → Generate new private key) saved as
`secrets/firebase-service-account.json` (gitignored — never commit it), and
an `.env.prod` with fresh `JWT_SECRET_KEY`/`FERNET_KEY` values — don't reuse
`.env.example`'s dev-only defaults (see the comments in `.env.prod` for the
one-liners that generate them).

```powershell
docker compose -f docker-compose.prod.yml up --build
docker compose -f docker-compose.prod.yml exec app python -m scripts.seed
```

## Running outside Docker

Point at an emulator started separately
(`docker compose up firebase-emulators`), then:

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

## Project layout

```
app/
  core/          # settings, JWT/bcrypt, Fernet crypto, Firestore client, auth dependency, HTTP helpers
  models.py      # Pydantic document/request shapes — no business logic
  repositories/  # Firestore access only
  services/      # business rules
  routers/       # HTTP translation only
  templates/     # Jinja2, Bootstrap 5 (CDN)
ml/              # attrition model training/evaluation, CV-extraction evaluation harness
scripts/seed.py  # creates the first admin user + reference data
tests/           # pytest against the Firestore emulator
```

`firestore.rules`, `storage.rules`, and `firestore.indexes.json` hold the
database security and indexing config, versioned alongside the app.

> **Note**: `docker-compose.yml`'s `env_file: .env` and the
> `firestore.indexes.json` bind-mount are only read when a container is
> *created* — after editing either file, use
> `docker compose up -d --force-recreate` (a plain `restart` isn't enough).

## What's not built yet

- The Contracts screens, and Paramètres' Alertes/Sécurité sub-screens
- Firebase Storage (employee photo upload, the Documents tab, certificate
  logo/signature/cachet images, and the raw CV file from the Assistant's
  import flow)
- Scheduled/background tasks — monthly leave-balance accrual, the
  dashboard's monthly-trend charts, and 5 of the notification categories
  (contracts expiring, internships ending, trial-period reminders,
  birthdays, missing documents)
- Bilingual OCR for scanned/image CVs (text-based PDF/DOCX only)
- A calendar view for congés, and Arabic/RTL support

See the cahier des charges' "Points laissés ouverts" for open questions the
client still needs to resolve (target scale, Arabic/RTL scope, Contracts
module screens).
