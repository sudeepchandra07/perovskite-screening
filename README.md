# Perovskite Cathode Screening System (NGIT)
Dataset-based batch screening following *Deng et al., "Machine-Learning-Based Screening of Perovskite Cathodes for Low-Temperature SOFC Operation", Crystals 2026, 16, 68*.
Stack (all free): Python · Flask · scikit-learn · SQLite · vanilla HTML/CSS/JS.

## Run locally (free)
Windows: double-click `run.bat`  ·  Mac/Linux: `./run.sh`  → open http://localhost:5000
Login: any valid roll number (e.g. `23CSE001`, 6–15 letters/digits) + the shared password. A user is created on first login.

## Free hosting
* **PythonAnywhere (free)** – recommended: persistent disk, so SQLite DB, uploads and models survive. Upload the folder, create a Flask web app, point WSGI to `backend/wsgi.py`, `pip install -r requirements.txt`.
* **Render free web service** – works (`Procfile` included) but its free disk is **ephemeral**: data is lost on redeploy/restart. Use only for demos.
* Set `STORAGE_DIR` to change where `app.db`, `uploads/` and `models/` are kept; set `SECRET_KEY` / `APP_SHARED_PASSWORD` env vars for deployment.

## What it does
Upload CSV/XLSX → auto column detection (editable) → feature selection from the paper's descriptor list (unavailable ones are dropped, never invented) →
Pipeline(median imputer → StandardScaler → model) → 5-fold CV for MLP (Bayesian opt.), SVR/GBR/KNN/RF (GridSearchCV) → **SVR primary** →
predict log10(k*) and k*=10^x for every cathode → Mahalanobis AD (0.8 quantile of training distances) → Ehull ≤ 57 meV/atom → log10(k*) ≥ −6.40 (*LSC benchmark used in the research paper*) →
PASS / FAIL / NOT FULLY EVALUABLE → top-5 candidate cards, screening funnel, log10(k*)-vs-Ehull scatter plot, filters, details modal, Shapley feature contributions, Excel/CSV export. Everything is saved per roll number in SQLite + disk.

## Where your data is stored
In `~/.perovskite_screening` (Windows: `C:\Users\<you>\.perovskite_screening`), outside the code folder, so unzipping a new version never wipes your history. An older `pcs/storage` folder is copied there automatically on first start. Login is a per-tab session: the login page appears every time you open the app fresh.

## Honest limitations (please read)
* **Cost filter removed** from this version. The paper's cost step (Aladdin precursor prices) is not applied, so PASS = inside applicability domain + Ehull ≤ 57 + log10(k*) ≥ −6.40.
* **Not an exact reproduction**: the paper's Arrhenius-normalised dataset, Table S2 hyper-parameters, RFE feature selection and RF-generated enhanced descriptors are not available. Enhanced columns (Gap, TEC, O_pband …) feed only an interpretation-only SVR, never the screening. Ehull is taken from your column.
* Hyper-parameter grids are deliberately small so training finishes in about a minute; the MLP uses Bayesian optimisation only if `scikit-optimize` is installed (otherwise randomised search, labelled in the app).
* The AD threshold is the 0.8 quantile of the *training* distances, so ~20 % of your own cathodes are outside by construction.
* Predictions for uploaded rows come from a model trained on those rows (in-sample); the cross-validated value is shown in each cathode's details.
* Same formula (e.g. `La0.6Sr0.4CoO3` = `La0.6Sr0.4Co1O3`) is counted once; the same dataset uploaded twice is stored once.
* Column abbreviations (`Sa`, `Ionic`, `Ion`) follow the paper's Fig. 3 labels. Shapley values use a built-in Monte-Carlo estimator, not the `shap` package.
* Shared-password login (stored hashed, 7-day tokens, no rate limiting) – fine for a college project, not for the open internet.
