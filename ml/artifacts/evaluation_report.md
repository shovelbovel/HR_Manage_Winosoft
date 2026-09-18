# Évaluation du modèle de risque d'attrition

Jeu de données : IBM HR Analytics Employee Attrition (1470 employés, 16.1% d'attrition observée).
Séparation train/test stratifiée : 1176 / 294 (graine aléatoire 42).

## Comparaison des modèles

| Modèle | Exactitude | F1 (classe « Part ») | ROC-AUC |
|---|---|---|---|
| Régression logistique **← retenu** | 0.769 | 0.485 | 0.814 |
| Forêt aléatoire | 0.844 | 0.521 | 0.801 |

## Rapport détaillé — Régression logistique

```
              precision    recall  f1-score   support

       Reste       0.93      0.79      0.85       247
        Part       0.38      0.68      0.48        47

    accuracy                           0.77       294
   macro avg       0.65      0.73      0.67       294
weighted avg       0.84      0.77      0.79       294

```