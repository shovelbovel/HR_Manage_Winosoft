"""Entraîne un modèle de prédiction du risque de départ (attrition).

Jeu de données : IBM HR Analytics Employee Attrition (1470 employés),
un jeu de données public de référence pour ce problème — utilisé ici
faute de données RH historiques réelles (confidentielles) en volume
suffisant pour entraîner un modèle honnête.

Usage (depuis la racine du projet) :
    docker compose exec app uv run python ml/train_attrition_model.py

Produit, dans ml/artifacts/ :
    attrition_model.joblib   — pipeline scikit-learn entraîné (le meilleur
                               des deux modèles comparés), plus les
                               statistiques d'imputation pour le service
                               d'inférence de l'application.
    evaluation_report.md     — comparaison chiffrée des modèles.
    roc_curve.png / confusion_matrix.png / feature_importance.png
"""

from __future__ import annotations

from pathlib import Path

import joblib
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    ConfusionMatrixDisplay,
    RocCurveDisplay,
    accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

ROOT = Path(__file__).resolve().parent
DATA_PATH = ROOT / "data" / "ibm_hr_attrition.csv"
ARTIFACTS_DIR = ROOT / "artifacts"
RANDOM_STATE = 42

# The full, standard feature set for this dataset (literature-comparable).
# Only a subset of these exist in the app's own Employee schema today —
# app/services/attrition_service.py documents and handles that gap at
# inference time; this script trains on the complete set on purpose, since
# the evaluation numbers below should be comparable to published results,
# not artificially limited to what one specific downstream app happens to
# track yet.
NUMERIC_FEATURES = [
    "Age",
    "DistanceFromHome",
    "Education",
    "EnvironmentSatisfaction",
    "JobInvolvement",
    "JobLevel",
    "JobSatisfaction",
    "MonthlyIncome",
    "NumCompaniesWorked",
    "PercentSalaryHike",
    "PerformanceRating",
    "RelationshipSatisfaction",
    "StockOptionLevel",
    "TotalWorkingYears",
    "TrainingTimesLastYear",
    "WorkLifeBalance",
    "YearsAtCompany",
    "YearsInCurrentRole",
    "YearsSinceLastPromotion",
    "YearsWithCurrManager",
]
CATEGORICAL_FEATURES = [
    "BusinessTravel",
    "Department",
    "EducationField",
    "Gender",
    "JobRole",
    "MaritalStatus",
    "OverTime",
]
ALL_FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES


def load_dataset() -> pd.DataFrame:
    df = pd.read_csv(DATA_PATH)
    df["Attrition"] = (df["Attrition"] == "Yes").astype(int)
    return df


def build_pipeline(estimator) -> Pipeline:
    preprocess = ColumnTransformer(
        [
            ("num", StandardScaler(), NUMERIC_FEATURES),
            ("cat", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL_FEATURES),
        ]
    )
    return Pipeline([("preprocess", preprocess), ("clf", estimator)])


def evaluate(name: str, pipeline: Pipeline, X_test, y_test) -> dict:
    y_pred = pipeline.predict(X_test)
    y_proba = pipeline.predict_proba(X_test)[:, 1]
    return {
        "name": name,
        "pipeline": pipeline,
        "accuracy": accuracy_score(y_test, y_pred),
        "f1_positive": f1_score(y_test, y_pred, pos_label=1),
        "roc_auc": roc_auc_score(y_test, y_proba),
        "report": classification_report(y_test, y_pred, target_names=["Reste", "Part"]),
        "confusion_matrix": confusion_matrix(y_test, y_pred),
        "y_test": y_test,
        "y_proba": y_proba,
    }


def main() -> None:
    ARTIFACTS_DIR.mkdir(exist_ok=True)
    df = load_dataset()
    X = df[ALL_FEATURES]
    y = df["Attrition"]
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=RANDOM_STATE, stratify=y
    )

    print(f"Jeu d'entraînement : {len(X_train)} lignes — Jeu de test : {len(X_test)} lignes")
    print(f"Taux d'attrition (ensemble complet) : {y.mean():.1%}")

    candidates = {
        "Régression logistique": LogisticRegression(
            max_iter=1000, class_weight="balanced", random_state=RANDOM_STATE
        ),
        "Forêt aléatoire": RandomForestClassifier(
            n_estimators=300, max_depth=8, class_weight="balanced", random_state=RANDOM_STATE
        ),
    }

    results = []
    for name, estimator in candidates.items():
        pipeline = build_pipeline(estimator)
        pipeline.fit(X_train, y_train)
        result = evaluate(name, pipeline, X_test, y_test)
        results.append(result)
        print(
            f"{name:24s} exactitude={result['accuracy']:.3f}  "
            f"F1(Part)={result['f1_positive']:.3f}  ROC-AUC={result['roc_auc']:.3f}"
        )

    best = max(results, key=lambda r: r["roc_auc"])
    print(f"\nMeilleur modèle retenu : {best['name']} (ROC-AUC = {best['roc_auc']:.3f})")

    # Bundle the fitted pipeline with the training-time imputation stats —
    # the serving code (app/services/attrition_service.py) needs both,
    # since our operational schema only supplies a subset of these
    # features and must fall back to sane defaults for the rest.
    joblib.dump(
        {
            "pipeline": best["pipeline"],
            "model_name": best["name"],
            "feature_columns": ALL_FEATURES,
            "numeric_features": NUMERIC_FEATURES,
            "categorical_features": CATEGORICAL_FEATURES,
            "training_medians": X_train[NUMERIC_FEATURES].median().to_dict(),
            "training_modes": {c: X_train[c].mode().iloc[0] for c in CATEGORICAL_FEATURES},
            "metrics": {
                "accuracy": best["accuracy"],
                "f1_positive": best["f1_positive"],
                "roc_auc": best["roc_auc"],
            },
        },
        ARTIFACTS_DIR / "attrition_model.joblib",
    )

    # --- Plots -------------------------------------------------------
    fig, ax = plt.subplots(figsize=(5, 5))
    for r in results:
        RocCurveDisplay.from_predictions(r["y_test"], r["y_proba"], name=r["name"], ax=ax)
    ax.plot([0, 1], [0, 1], linestyle="--", color="grey", label="Hasard")
    ax.set_title("Courbes ROC — comparaison des modèles")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(ARTIFACTS_DIR / "roc_curve.png", dpi=150)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(4.5, 4.5))
    ConfusionMatrixDisplay(best["confusion_matrix"], display_labels=["Reste", "Part"]).plot(
        ax=ax, cmap="Reds", colorbar=False
    )
    ax.set_title(f"Matrice de confusion — {best['name']}")
    fig.tight_layout()
    fig.savefig(ARTIFACTS_DIR / "confusion_matrix.png", dpi=150)
    plt.close(fig)

    # Feature importance: tree ensembles expose feature_importances_
    # directly; a linear model's standardized |coefficient| is the
    # equivalent interpretability signal (valid here specifically because
    # every numeric feature was scaled before fitting).
    clf = best["pipeline"].named_steps["clf"]
    feature_names = best["pipeline"].named_steps["preprocess"].get_feature_names_out()
    importance_kind = None
    if hasattr(clf, "feature_importances_"):
        importances = clf.feature_importances_
        importance_kind = "Importance (impureté)"
    elif hasattr(clf, "coef_"):
        importances = np.abs(clf.coef_[0])
        importance_kind = "Poids absolu (coefficient standardisé)"
    else:
        importances = None

    if importances is not None:
        order = np.argsort(importances)[-15:]
        fig, ax = plt.subplots(figsize=(9, 6.5))
        ax.barh(range(len(order)), importances[order], color="#8a1c2b")
        ax.set_yticks(range(len(order)))
        ax.set_yticklabels([feature_names[i] for i in order], fontsize=9)
        ax.set_xlabel(importance_kind)
        ax.set_title(f"Importance des variables — {best['name']} (15 principales)", fontsize=12)
        fig.tight_layout()
        fig.savefig(ARTIFACTS_DIR / "feature_importance.png", dpi=150)
        plt.close(fig)

    # --- Report --------------------------------------------------------
    lines = [
        "# Évaluation du modèle de risque d'attrition",
        "",
        f"Jeu de données : IBM HR Analytics Employee Attrition "
        f"({len(df)} employés, {y.mean():.1%} d'attrition observée).",
        f"Séparation train/test stratifiée : {len(X_train)} / {len(X_test)} "
        f"(graine aléatoire {RANDOM_STATE}).",
        "",
        "## Comparaison des modèles",
        "",
        "| Modèle | Exactitude | F1 (classe « Part ») | ROC-AUC |",
        "|---|---|---|---|",
    ]
    for r in results:
        marker = " **← retenu**" if r is best else ""
        lines.append(
            f"| {r['name']}{marker} | {r['accuracy']:.3f} | {r['f1_positive']:.3f} | {r['roc_auc']:.3f} |"
        )
    lines += [
        "",
        f"## Rapport détaillé — {best['name']}",
        "",
        "```",
        best["report"],
        "```",
    ]
    (ARTIFACTS_DIR / "evaluation_report.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"\nRapport écrit dans {ARTIFACTS_DIR / 'evaluation_report.md'}")
    print(f"Modèle écrit dans {ARTIFACTS_DIR / 'attrition_model.joblib'}")


if __name__ == "__main__":
    main()
