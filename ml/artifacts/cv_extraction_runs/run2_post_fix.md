# Évaluation de l'extraction de CV par l'assistant IA

16 CV de test, appels réels à l'API IA (claude-sonnet-5).

## Exactitude par champ

| Champ | Correct | Total | Exactitude |
|---|---|---|---|
| first_name | 16 | 16 | 100% |
| last_name | 16 | 16 | 100% |
| professional_email | 16 | 16 | 100% |
| phone | 16 | 16 | 100% |
| birth_date | 16 | 16 | 100% |
| suggested_contract_type | 14 | 16 | 88% |

**Exactitude globale (tous champs confondus) : 98%**

## Détail par CV

- `cdi_full_info` — tous les champs corrects
- `stage_fin_etudes` — tous les champs corrects
- `cdd_explicite` — tous les champs corrects
- `sans_telephone` — tous les champs corrects
- `sans_date_naissance` — tous les champs corrects
- `type_contrat_ambigu` — tous les champs corrects
- `stage_phrasing_alternative` — tous les champs corrects
- `cdi_cadre_confirme` — tous les champs corrects
- `email_format_inhabituel` — tous les champs corrects
- `cdi_mi_carriere` — tous les champs corrects
- `cv_minimal` — tous les champs corrects
- `caracteres_accentues` — écart(s) : suggested_contract_type (attendu 'CDI', obtenu 'STAGE')
- `telephone_format_inhabituel` — tous les champs corrects
- `entete_cv_decoratif` — tous les champs corrects
- `cv_bilingue` — tous les champs corrects
- `signal_contrat_contradictoire` — écart(s) : suggested_contract_type (attendu None, obtenu 'CDD')