"""Measures the CV-extraction assistant's real accuracy against a hand-
labeled test set, instead of trusting "it looked right when I tried it".

Calls the REAL AI API (via the app's own AIService, unmodified) — this
is a live evaluation, not a unit test: it costs real API calls and needs
ANTHROPIC_API_KEY set, so it deliberately lives outside the pytest suite
(which only ever uses a FakeAIClient — see tests/test_ai.py) and is run by
hand.

Usage (with ANTHROPIC_API_KEY already set in .env):
    docker compose exec app uv run python ml/evaluate_cv_extraction.py

Produces ml/artifacts/cv_extraction_evaluation.md — per-field accuracy and
a per-fixture pass/fail breakdown.

Only the contact fields and the suggested contract type are scored here:
the department/position suggestion depends on whichever organisation data
happens to exist in the Firestore project this is run against, so it has
no fixed ground truth to compare against in a fixture file like this one.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

from docx import Document

from app.core.ai_client import AIClient
from app.core.config import get_settings
from app.core.firestore_client import get_firestore_client
from app.repositories.ai_audit_log_repository import AIAuditLogRepository
from app.repositories.departments_repository import DepartmentsRepository
from app.repositories.positions_repository import PositionsRepository
from app.repositories.settings_repository import SettingsRepository
from app.services.ai_service import AIService

ROOT = Path(__file__).resolve().parent
FIXTURES_PATH = ROOT / "fixtures" / "cv_eval_set.json"
ARTIFACTS_DIR = ROOT / "artifacts"

_DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

_SCORED_FIELDS = [
    "first_name",
    "last_name",
    "professional_email",
    "phone",
    "birth_date",
    "suggested_contract_type",
]


def _cv_text_to_docx_bytes(text: str) -> bytes:
    document = Document()
    for line in text.split("\n"):
        document.add_paragraph(line)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _normalize(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip().lower()
    return str(value).lower()


def main() -> None:
    settings = get_settings()
    if not settings.anthropic_api_key:
        raise SystemExit(
            "ANTHROPIC_API_KEY n'est pas configurée — impossible d'évaluer contre l'API réelle."
        )

    db = get_firestore_client()
    settings_repository = SettingsRepository(db)
    # This script deliberately (re)activates the module with a generous
    # quota for the duration of the run — it's a one-off, hand-run
    # evaluation script, not something that executes unattended.
    settings_repository.set_ai(enabled=True, daily_quota_per_user=100, monthly_quota_global=1000)

    ai_client = AIClient(settings.anthropic_api_key, settings.anthropic_model)
    service = AIService(
        ai_client,
        AIAuditLogRepository(db),
        settings_repository,
        DepartmentsRepository(db),
        PositionsRepository(db),
        db,
    )

    fixtures = json.loads(FIXTURES_PATH.read_text(encoding="utf-8"))
    field_correct = dict.fromkeys(_SCORED_FIELDS, 0)
    rows = []

    for fixture in fixtures:
        file_bytes = _cv_text_to_docx_bytes(fixture["cv_text"])
        try:
            extracted = service.extract_cv("ml-eval-script", file_bytes, _DOCX_CONTENT_TYPE)
        except Exception as exc:  # noqa: BLE001 — record and keep going
            print(f"[{fixture['id']}] ÉCHEC D'APPEL : {exc}")
            rows.append({"id": fixture["id"], "error": str(exc)})
            continue

        extracted_dict = extracted.model_dump(mode="json")
        ground_truth = fixture["ground_truth"]
        field_results = {}
        for field in _SCORED_FIELDS:
            correct = _normalize(extracted_dict.get(field)) == _normalize(ground_truth.get(field))
            field_results[field] = correct
            if correct:
                field_correct[field] += 1
        rows.append({"id": fixture["id"], "fields": field_results, "extracted": extracted_dict, "ground_truth": ground_truth})
        status = "OK" if all(field_results.values()) else "ÉCARTS"
        print(f"[{fixture['id']}] {status}")

    n = len(fixtures)
    lines = [
        "# Évaluation de l'extraction de CV par l'assistant IA",
        "",
        f"{n} CV de test, appels réels à l'API IA ({settings.anthropic_model}).",
        "",
        "## Exactitude par champ",
        "",
        "| Champ | Correct | Total | Exactitude |",
        "|---|---|---|---|",
    ]
    for field in _SCORED_FIELDS:
        lines.append(f"| {field} | {field_correct[field]} | {n} | {field_correct[field] / n:.0%} |")

    overall = sum(field_correct.values()) / (n * len(_SCORED_FIELDS))
    lines += ["", f"**Exactitude globale (tous champs confondus) : {overall:.0%}**", "", "## Détail par CV", ""]
    for row in rows:
        if "error" in row:
            lines.append(f"- `{row['id']}` — échec d'appel : {row['error']}")
            continue
        failed = [f for f, ok in row["fields"].items() if not ok]
        if not failed:
            lines.append(f"- `{row['id']}` — tous les champs corrects")
        else:
            details = ", ".join(
                f"{f} (attendu {row['ground_truth'].get(f)!r}, obtenu {row['extracted'].get(f)!r})"
                for f in failed
            )
            lines.append(f"- `{row['id']}` — écart(s) : {details}")

    ARTIFACTS_DIR.mkdir(exist_ok=True)
    (ARTIFACTS_DIR / "cv_extraction_evaluation.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"\nExactitude globale : {overall:.0%}")
    print(f"Rapport écrit dans {ARTIFACTS_DIR / 'cv_extraction_evaluation.md'}")


if __name__ == "__main__":
    main()
