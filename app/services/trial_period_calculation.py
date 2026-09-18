"""Trial-period initial-duration calculation — a pure function, no
Firestore access, same pattern as app.services.working_days. Cahier des
charges Module 8's duration table (page 23).
"""

from __future__ import annotations

from datetime import date, timedelta

from app.models import ContractCategory, ContractType

# Fixed day-counts rather than calendar-month arithmetic (avoids Jan 31 + 1
# month edge cases) — a precision the spec doesn't ask for.
_CDI_DURATION_DAYS = {
    ContractCategory.CADRE: 90,
    ContractCategory.EMPLOYEE: 45,  # "1,5 mois"
    ContractCategory.OUVRIER: 15,
}

_CDD_SHORT_CONTRACT_THRESHOLD_DAYS = 182  # "inférieur à 6 mois"
_CDD_SHORT_CONTRACT_CAP_DAYS = 14  # "plafonné à 2 semaines"
_CDD_LONG_CONTRACT_DAYS = 30  # "1 mois maximum"


class TrialPeriodOverrideRequiredError(Exception):
    """Raised if a STAGE trial period is computed without an override.
    Should be unreachable via the API — EmployeeCreateRequest already
    requires the override for STAGE — but this function doesn't trust that
    path alone.
    """


def calculate_initial_trial_end_date(
    *,
    contract_type: ContractType,
    contract_category: ContractCategory | None,
    start_date: date,
    contract_end_date: date | None,
    override: date | None,
) -> date:
    if contract_type == ContractType.STAGE:
        # "Selon convention" — no formula, per the cahier des charges.
        if override is None:
            raise TrialPeriodOverrideRequiredError()
        return override

    if contract_type == ContractType.CDI:
        if contract_category is None:
            raise ValueError("contract_category is required to compute a CDI trial period")
        return start_date + timedelta(days=_CDI_DURATION_DAYS[contract_category])

    # CDD
    if contract_end_date is None:
        raise ValueError("contract_end_date is required to compute a CDD trial period")
    contract_length_days = (contract_end_date - start_date).days
    if contract_length_days < _CDD_SHORT_CONTRACT_THRESHOLD_DAYS:
        weeks = contract_length_days // 7
        trial_days = min(weeks, _CDD_SHORT_CONTRACT_CAP_DAYS)
        return start_date + timedelta(days=trial_days)
    return start_date + timedelta(days=_CDD_LONG_CONTRACT_DAYS)
