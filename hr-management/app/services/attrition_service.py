"""Best-effort employee attrition-risk estimate.

Loads the scikit-learn pipeline trained offline by ml/train_attrition_model.py
(IBM HR Analytics Employee Attrition dataset) and scores one employee at a
time. This is a *local* model running in this process — unlike the AI
assistant (app/services/ai_service.py), no data ever leaves this server, so
app/core/ai_privacy.py's outbound-payload filter does not apply here; using
the employee's real salary as a model input is fine precisely because it
never crosses a network boundary.

Training/serving feature gap: the model is trained on the dataset's full,
literature-standard feature set (satisfaction scores, overtime, business
travel, tenure with current manager, etc.), because the evaluation numbers
in ml/artifacts/evaluation_report.md should be comparable to published
results for this exact dataset. This app's own Employee schema does not
track most of those signals today — only a handful of numeric/categorical
features map directly. Anything the app can't supply is imputed with the
training set's median (numeric) or mode (categorical), which is a standard,
explicitly-labelled degradation, not a silent one: the UI shows exactly how
many inputs were real versus defaulted, and the estimate is presented as
just that — an estimate, informational only, never an automated decision
about any employee.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import joblib
import pandas as pd

from app.models import EmployeeDocument

_MODEL_PATH = Path(__file__).resolve().parent.parent.parent / "ml" / "artifacts" / "attrition_model.joblib"

_load_lock = threading.Lock()
_bundle: dict | None = None
_load_attempted = False

# Best-effort mapping from this app's department names to the training
# dataset's fixed categories. Unmapped names (Finance, Commercial, …) fall
# through to the encoder's handle_unknown="ignore" — the feature then
# simply contributes no signal for that employee, rather than raising.
_DEPARTMENT_MAP = {
    "Ressources Humaines": "Human Resources",
    "Informatique": "Research & Development",
}

_RISK_THRESHOLDS = (
    (0.66, "Élevé"),
    (0.33, "Modéré"),
)


@dataclass
class AttritionRisk:
    available: bool
    probability: float | None = None
    label: str | None = None
    used_features: tuple[str, ...] = ()
    defaulted_count: int = 0
    total_features: int = 0


def _load_bundle() -> dict | None:
    global _bundle, _load_attempted
    if _bundle is not None or _load_attempted:
        return _bundle
    with _load_lock:
        if _bundle is not None or _load_attempted:
            return _bundle
        _load_attempted = True
        if _MODEL_PATH.exists():
            _bundle = joblib.load(_MODEL_PATH)
    return _bundle


def reset_model_cache() -> None:
    """Used by tests to force a reload against a different/missing path."""
    global _bundle, _load_attempted
    _bundle = None
    _load_attempted = False


def _risk_label(probability: float) -> str:
    for threshold, label in _RISK_THRESHOLDS:
        if probability >= threshold:
            return label
    return "Faible"


def _years_since(reference: datetime, now: datetime) -> float:
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    return max((now - reference).days / 365.25, 0.0)


def score_employee(employee: EmployeeDocument, gross_salary: float | None) -> AttritionRisk:
    bundle = _load_bundle()
    if bundle is None:
        return AttritionRisk(available=False)

    numeric_features: list[str] = bundle["numeric_features"]
    categorical_features: list[str] = bundle["categorical_features"]
    medians: dict = bundle["training_medians"]
    modes: dict = bundle["training_modes"]

    now = datetime.now(timezone.utc)
    age = _years_since(employee.birth_date, now)
    years_at_company = _years_since(employee.hire_date, now)

    known_numeric = {
        "Age": age,
        "YearsAtCompany": years_at_company,
        # No prior-employment history is tracked, so tenure here is used as
        # a floor for total working years — a documented approximation,
        # not a measured value.
        "TotalWorkingYears": years_at_company,
    }
    if gross_salary is not None:
        known_numeric["MonthlyIncome"] = gross_salary

    known_categorical = {}
    mapped_department = _DEPARTMENT_MAP.get(employee.department_name)
    if mapped_department:
        known_categorical["Department"] = mapped_department

    row: dict[str, float | str] = {}
    used_features: list[str] = []
    defaulted_count = 0
    for col in numeric_features:
        if col in known_numeric:
            row[col] = known_numeric[col]
            used_features.append(col)
        else:
            row[col] = medians[col]
            defaulted_count += 1
    for col in categorical_features:
        if col in known_categorical:
            row[col] = known_categorical[col]
            used_features.append(col)
        else:
            row[col] = modes[col]
            defaulted_count += 1

    frame = pd.DataFrame([row], columns=numeric_features + categorical_features)
    probability = float(bundle["pipeline"].predict_proba(frame)[0, 1])

    return AttritionRisk(
        available=True,
        probability=probability,
        label=_risk_label(probability),
        used_features=tuple(used_features),
        defaulted_count=defaulted_count,
        total_features=len(numeric_features) + len(categorical_features),
    )
