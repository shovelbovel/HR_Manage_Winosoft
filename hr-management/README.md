# HR Management — backend

FastAPI + Firebase Firestore backend for the WinoSoft HR Management app
(cahier des charges v3.0), built on the layered architecture the spec
mandates (`routers/ → services/ → repositories/ → models.py`).

Implemented so far:
- **Module 1 — Authentification**: login, JWT access/refresh tokens, lockout
  after 5 failed attempts, role-based post-login redirect (Admin/Manager →
  `/dashboard`, Employé → `/home`).
- **Module 4 — Départements**: CRUD, immutable unique code, blocked delete
  while it has employees.
- **Module 5 — Postes**: CRUD scoped to a department, optional
  `max_occupants` cap (enforced at employee assignment), blocked delete
  while occupied.
- **Module 3 — Gestion du personnel**: employee CRUD with CIN/phone/RIB/
  minimum-age validation, Fernet-encrypted salary and RIB (decrypted only
  for the admin-facing HTML fiche, never in JSON/list/CSV responses),
  matricule auto-generation (`EMP-YYYY-NNNN`), search + department/status/
  contract-type filters + cursor pagination, CSV export (salary/RIB
  excluded), deactivate/activate (soft status, never hard-deleted). Photo
  upload and the Documents tab are deferred (need Firebase Storage) — the
  fiche has an inert placeholder tab for it.
- **Module 6 — Gestion des congés**: request/approve/reject workflow with a
  jours-ouvrés calculation (weekends + seeded fixed holidays excluded),
  balance tracking (`leave_balances`, deterministic id, `remaining` computed
  at read time), overlap and insufficient-balance checks, and the first use
  of role-scoped authorization — a `MANAGER` only sees/decides their own
  department's requests, an `EMPLOYEE` only their own, both enforced via
  `ResourceOutOfScopeError` → 404 (never 403, so an out-of-scope request
  doesn't confirm the resource exists). `leave_types`/`holidays` are
  seed-only reference data in this pass (no admin CRUD yet); no calendar
  view; no monthly balance accrual (needs a scheduler, not built); no
  employee self-service account creation UI (link a login to an employee
  directly via `UsersRepository`, same technique the tests use).
- **Module 8 — Périodes d'essai**: auto-created for every employee at
  creation time (CDI duration by category — Cadre/Employé/Ouvrier;
  CDD duration from contract length, capped at 2 weeks; Stage requires an
  explicit `trial_end_date_override` since it has no formula), validate/
  extend/refuse workflow with a mandatory motif on all three actions,
  server-computed progress bar, one CDI-only renewal. Validating flips the
  employee's own status `trial → active`. Trial period creation is a
  sequential follow-up write after the employee doc, not a single Firestore
  transaction — see the code comment in `employees_service.py` for why.
- **Module 2 — Tableau de bord**: role-scoped dashboard (Admin: global,
  Manager: own department only, restricted via `require_role(ADMIN, MANAGER)`)
  with KPI cards (`employees_active`/`interns`/`leaves_pending` counters,
  `departments_active` for Admin only), alert lists (contracts expiring in
  30 days, trial periods and internships ending in 15 days, birthdays and
  new hires this month) and two Chart.js charts (department distribution,
  contract-type distribution) from a bounded read (capped at 250 employees).
  Employé gets a separate, deliberately minimal `/home` page instead (own
  leave balance + recent requests + a "Nouvelle demande" link) — not a
  cut-down dashboard. Both routes content-negotiate JSON/HTML like every
  other module. The two 12-month trend charts ("Évolution des effectifs",
  "Absentéisme mensuel") are deferred — the spec requires them to be backed
  by monthly pre-computed aggregates via a scheduled task, which doesn't
  exist yet (same Cloud Functions/Scheduler gap as Modules 6/8's other
  deferred pieces); building them without that job would mean recomputing
  on every page load, the exact thing the spec says not to do.
- **Module 9 — Alertes & Notifications**: a centralized, per-recipient
  notification center (bell icon + unread badge + a 10-item dropdown on
  every page, plus a full `/notifications` history page), all self-scoped
  to the caller's own inbox. 3 of the spec's 8 categories are event-driven
  and wired up: a submitted leave notifies the department's manager(s) +
  admins, a leave decision notifies the requesting employee, and a new hire
  notifies the department's manager(s) + admins. The other 5 categories
  (contracts expiring, internships ending, trial-period J-15/J-7,
  birthdays, missing documents) need a scheduled task to materialize —
  same Cloud Functions/Scheduler gap as above; their data is already live
  on the Module 2 dashboard's alert cards, just not yet persisted as
  individually read/unread-trackable notifications.
- **Module 7 — Attestations PDF**: 5 certificate types (travail, stage,
  congé, salaire, fin de contrat) generated via WeasyPrint from HTML/CSS
  templates, with a sequential `ATT-AAAA-XXXX` number (transactional, same
  mechanism as the employee matricule) and role/type-gated access (salaire
  and fin de contrat are admin-only). Rather than persisting a PDF file to
  Firebase Storage, each certificate stores a frozen `data_snapshot` (JSON)
  in Firestore and the PDF is **regenerated on demand** on every
  authenticated, scope-checked download — verified to survive a later edit
  to the underlying employee record (the exact "instantané fidèle" recette
  criterion). This also sidesteps a real limitation: the Storage
  *emulator* doesn't reliably support `generate_signed_url`. Logo/
  signature/cachet images are deferred (same Storage gap as employee
  photos). Pulled forward a thin slice of Module 11 as a prerequisite —
  `settings/company` (raison sociale/adresse/ICE/RC/IF), admin-only,
  feeding the PDF header — the same way Postes was pulled forward for
  Employees. Also first-time infrastructure: `weasyprint` plus its native
  Pango/cairo/gdk-pixbuf OS libraries, now installed via `apt-get` in both
  Dockerfile stages; `pydyf` is pinned below 0.12 (a real weasyprint/pydyf
  API-compatibility break discovered while getting this module's tests
  green, not a hypothetical one — see the comment in `pyproject.toml`).
- **Module 11 — Paramètres** (partial: Entreprise, Congés, Utilisateurs):
  admin-only config screens under `/settings/*`. **Utilisateurs** closes a
  gap present since Module 6 — every manager/employee-linked login account
  had to be created by calling `UsersRepository` directly (tests and
  manual verification still document this as the fallback for anything
  this screen doesn't cover); now there's a real admin UI: create by role
  (with role-specific required fields — a Manager needs a
  `department_id`), reset a user's password directly (no email step —
  that still needs an email provider, same as the self-service reset
  flow), activate/deactivate. Building this surfaced and fixed a real bug
  in `UsersRepository.set_active`: deactivating a user releases its email's
  uniqueness lock (intentional, so the email can be reused), but
  reactivating never re-acquired it, so a reactivated account's own email
  could no longer resolve to it at login — invisible until this module
  added the first UI path that both deactivates *and* reactivates the same
  account. **Congés** adds real CRUD for `leave_types`/`holidays`
  (previously seed-only, both docstrings literally said "Module 11 will
  add this later"). Doing this properly also meant fixing a second latent
  gap: `HolidayDocument` had no `year` field and
  `working_days_between` only ever matched *recurring* holidays — so
  admin-entered non-recurring (religious) holidays are now actually
  excluded from the jours-ouvrés calculation, not just stored inertly.
  **Alertes and Sécurité sub-screens are still deferred** — Alertes is
  mostly config for the same 5 scheduler-dependent notification categories
  already deferred in Module 9; Sécurité is already env-var-driven
  (`app/core/config.py`), which already satisfies the spec's "variables de
  configuration centralisées, surchargeables par l'environnement"
  requirement, and making it admin-editable at runtime would be a real
  architecture change for a "Basse" priority module. **Assistant**
  (`/settings/ai`) now exists as part of Module 12, below.
- **Module 12 — Assistant intelligent**: CV import (extracts and
  pre-fills the employee creation form), assisted drafting (job
  descriptions/letters/notes/attestation messages), and a dashboard
  summary — all on the configured AI API. Off by default, admin-activated via
  `/settings/ai` with configurable daily-per-user/monthly-global quotas
  (own `_counters` keys, reusing `increment_counter`/`get_counter_value`);
  every call logged to a scoped `ai_audit_log` collection
  (author/function/timestamp — never the prompt or response content, per
  spec). A dedicated `app/core/ai_privacy.py` filter runs on every
  outbound payload, denylisting salary/RIB/CNSS/CIN/birth-date/emergency-
  contact/internal-notes fields; the dashboard summary payload only ever
  contains counts and department labels (never an `EmployeeDocument`),
  so there's no employee name to leak in the first place. CV import
  supports PDF/DOCX text extraction only — bilingual OCR for scanned
  images is a materially bigger dependency (Tesseract + language packs)
  deferred as disproportionate for this pass; the extracted *file* itself
  isn't persisted either (needs the Documents tab, deferred since Module
  3). The AI client is dependency-injected
  (`app.core.dependencies.get_ai_client`), so the test suite runs entirely
  against a fake client — no test ever calls the real AI API. A
  provider failure or timeout always surfaces as a 503 with a fallback
  message, never a raw error. **Live end-to-end verification against the
  real AI API still needs an `ANTHROPIC_API_KEY` supplied by the
  operator** — set it in `.env`, `docker compose up -d --force-recreate`,
  then enable the module via `/settings/ai`.
- **Module 10 — Design responsive & UX**: a cross-cutting pass over every
  existing page rather than a new module of routes, closing out the
  12-module scope. The navbar markup (`navbar-expand` with no breakpoint,
  no toggler) never collapsed on mobile — duplicated verbatim across all 28
  content templates, so it's now a single `{% call navbar(...) %}` Jinja
  macro (`app/templates/_navbar.html`) with a real hamburger
  toggle/collapse at the `lg` breakpoint; every page was migrated onto it.
  Added shared, reusable primitives rather than one-off page fixes: a
  confirmation modal (`<form data-confirm="…">`, wired in `app.js`) in
  front of every destructive/consequential action (deactivate employee/
  user, delete department/position/holiday, reject a leave, reset a
  password); an ephemeral toast system (`app/core/http.py::flash_redirect`
  + `data-flash` on `<body>` + `showToast()` in `app.js`) for one-shot
  success/warning confirmations after a redirect, replacing nothing (the
  static `alert-danger` validation banners stay, since a toast that
  vanishes on its own is wrong for an error the user still needs to fix);
  a generic loading-spinner-on-submit for regular form posts, skipped
  automatically for pages managing their own submit state (e.g. the CV
  import page's fetch-based upload) via an `event.defaultPrevented` check.
  Breadcrumbs were added to every content page that didn't already have
  one (the three root pages — `/login`, `/dashboard`, `/home` — correctly
  have none). Accessibility: `for`/`id` pairing added to ~60 previously
  unassociated `<label>`/input pairs across every create/edit form and
  filter bar; a `:focus-visible` outline and a `prefers-reduced-motion`
  media query in `app.css`; `<tr onclick="…">` list rows (keyboard-
  unreachable before this) now get `tabindex`, `role="link"`, and an
  Enter/Space handler via a generic `app.js` pass, rather than rewriting
  every list page to use real `<a>` rows. Audited every page against the
  spec's "max 3 primary actions per screen" — already true everywhere (1–2
  `btn-primary` per page), no changes needed there. **Deliberately
  unchanged**: the top navbar stays a navbar, not a sidebar — the spec's
  "barre latérale" requirement is treated as "primary navigation must
  collapse on mobile," which it now does, rather than a full nav
  architecture rewrite this late; there's still no calendar widget for
  congés (never built in Module 6, out of scope here too).

Firebase connectivity is **emulator-only** by default (`docker compose up`,
below) — no real Firebase project or credentials are needed for that. A real
Firestore project (`pfa-winosoft`) is also wired up as an opt-in second path;
see "Running against real Firestore" below.

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

Create the first admin user plus reference data (leave types, fixed
holidays) — idempotent, safe to re-run:

```powershell
docker compose exec app uv run python -m scripts.seed
```

Then open http://localhost:8000/login and sign in with `SEED_ADMIN_EMAIL` /
`SEED_ADMIN_PASSWORD` from `.env` (defaults in `.env.example`).

## Running against real Firestore

A second, opt-in path (`docker-compose.prod.yml`) runs the app against a
real Firestore project instead of the emulator — never activates by
accident, since it's a separate compose file with its own project name
(`hr-management-prod`) and its own env file (`.env.prod`), both gitignored.

Requires a Firebase service-account key (Firebase console → Project
settings → Service accounts → Generate new private key) saved as
`secrets/firebase-service-account.json` (gitignored — never commit it), and
an `.env.prod` with real `JWT_SECRET_KEY`/`FERNET_KEY` values (generate
fresh ones, don't reuse `.env.example`'s dev-only defaults — see the
comments in `.env.prod` for the one-liners that generate them).

```powershell
docker compose -f docker-compose.prod.yml up --build
docker compose -f docker-compose.prod.yml exec app python -m scripts.seed
```

`app/core/firestore_client.py` decides emulator-vs-real purely on whether
`FIRESTORE_EMULATOR_HOST` is set in the environment — `docker-compose.prod.yml`
deliberately never sets it, and passes `GOOGLE_APPLICATION_CREDENTIALS`
instead, which `google.auth.default()` picks up automatically. No code
branch needed changing to support this.

`firestore.rules` isn't deployed to the real project by this setup — the
app only ever talks to Firestore through this service account (Admin SDK
semantics), which security rules don't govern in the first place; rules
only matter once/if a client-side Firestore SDK is added directly to a
browser or mobile client, which this app doesn't do.

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
  core/          # settings, JWT/bcrypt, Fernet crypto, Firestore client, auth dependency, HTTP helpers
  models.py      # Pydantic document/request shapes — no business logic
  repositories/  # Firestore access only — _uniques/_counters/search_tokens/pagination helpers
  services/      # business rules (auth, department/position/employee counters & capacity)
  routers/       # HTTP translation only
  templates/     # Jinja2, Bootstrap 5 (CDN)
scripts/seed.py  # creates the first admin user
tests/           # pytest against the Firestore emulator
```

Note: `docker-compose.yml`'s `env_file: .env` and the `firestore.indexes.json`
bind-mount are both only read when a container is *created* — after editing
`.env` or `firestore.indexes.json`, use `docker compose up -d --force-recreate`
(a plain `restart` isn't enough for `.env` changes).

See `firestore.rules`, `storage.rules`, and `firestore.indexes.json` for the
(currently empty/deny-all) database security and indexing config, versioned
alongside the app per the spec.

## What's deliberately not here yet

The Contracts screens and Module 11's Alertes/Sécurité sub-screens; a real
Firebase project; Firebase Storage entirely (employee photo upload, the
Documents tab, certificate logo/signature/cachet images, and the raw CV
file from Module 12's import all deferred for it); bilingual OCR for
scanned/image CVs (Module 12 handles PDF/DOCX text extraction only); Cloud
Functions/scheduled tasks (so `status="expired"` transitions, monthly
leave-balance accrual, the dashboard's two monthly-aggregate trend charts,
and 5 of Module 9's 8 notification categories — contracts expiring,
internships ending, trial-period J-15/J-7, birthdays, missing documents —
are all manual/absent for now — see the code comments in
`employees_service.py`/`leaves_service.py`/`trial_periods_service.py`/`dashboard_service.py`/`notifications_service.py`);
calendar view for congés; Arabic/RTL; Module 11's admin UI for
creating manager/employee-linked login accounts (tests and manual
verification use `UsersRepository` directly in the meantime). See the
cahier des charges' "Points laissés ouverts" for open questions the client
still needs to resolve (target scale, Arabic/RTL scope, Contracts module
screens).
