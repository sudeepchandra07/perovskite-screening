"""ML core: column detection, preprocessing, model comparison, SVR primary model,
Mahalanobis applicability domain, Shapley explanations and paper-based screening.
Nothing here invents data: missing descriptors / screening columns are reported, never filled."""
import os, re, warnings, contextlib
import numpy as np, pandas as pd
from sklearn.base import clone
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.impute import SimpleImputer
from sklearn.svm import SVR
from sklearn.neural_network import MLPRegressor
from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
from sklearn.neighbors import KNeighborsRegressor
from sklearn.model_selection import GroupKFold, GroupShuffleSplit, GridSearchCV, RandomizedSearchCV
from sklearn.inspection import permutation_importance
from sklearn.metrics import r2_score, mean_absolute_error, mean_squared_error

warnings.filterwarnings("ignore")
EHULL_LIMIT = 57.0      # meV/atom, LSC value used in the paper
ORR_LIMIT = -6.40       # log10(k*) of LSC, "LSC benchmark used in the research paper"
ORR_SCALE = 1.0         # app-defined: 1 log10 unit of k* shortfall counts as 100% (≈ CV MAE); NOT from the paper
GREEN_MAX, RED_MIN = 0.5, 1.5   # app-defined tier cut-offs on the closeness score
AD_QUANTILE = 0.8       # paper: empirical quantile threshold 0.8


def norm(s): return re.sub(r"[^a-z0-9]", "", str(s).lower())

# key, group, label (paper wording; A/B abbreviations follow paper Fig. 3 naming), aliases (normalised)
DESC = [
 ("Ion_A", "basic", "Valence-electron ionization energy, A-site", ["iona"]),
 ("Ion_B", "basic", "Valence-electron ionization energy, B-site", ["ionb"]),
 ("EN_A", "basic", "Site-averaged electronegativity, A-site", ["ena"]),
 ("EN_B", "basic", "Site-averaged electronegativity, B-site", ["enb"]),
 ("R_A", "basic", "Shannon ionic radius, A-site", ["ra"]),
 ("R_B", "basic", "Shannon ionic radius, B-site", ["rb"]),
 ("Sa_A", "basic", "Ionic Lewis acidity, A-site", ["saa"]),
 ("Sa_B", "basic", "Ionic Lewis acidity, B-site", ["sab"]),
 ("Delec_B", "basic", "B-site d-electron count", ["delecb"]),
 ("t", "basic", "Goldschmidt tolerance factor", ["t", "tolerancefactor"]),
 ("Ionic_A", "basic", "Ionicity index, A-site", ["ionica"]),
 ("Ionic_B", "basic", "Ionicity index, B-site", ["ionicb"]),
 ("Avg_Ionic_Character", "basic", "Average ionic character (ionicity)", ["avgioniccharacter"]),
 ("SmithAcid_A", "basic", "Smith acidity, A-site", ["smithacida"]),
 ("SmithAcid_B", "basic", "Smith acidity, B-site", ["smithacidb"]),
 ("1000/T", "temperature", "Inverse absolute temperature (1000/T)", ["1000t", "invt", "inverset"]),
 ("Gap", "enhanced", "Band gap", ["gap", "bandgap"]),
 ("Oxide_vacancy", "enhanced", "Oxygen-vacancy formation energy", ["oxidevacancy", "ovacancy"]),
 ("E_above_hull", "enhanced", "Ehull (energy above hull)", ["eabovehull", "ehull", "energyabovehull"]),
 ("TEC", "enhanced", "Thermal expansion coefficient (TEC)", ["tec"]),
 ("Work_Function", "enhanced", "Work function", ["workfunction"]),
 ("Log_dieletric", "enhanced", "Log dielectric constant", ["logdieletric", "logdielectric"]),
 ("O_pband", "enhanced", "O p-band center", ["opband", "opbandcenter"]),
]
FORMULA_AL = ["materialcomposition", "formula", "chemicalformula", "composition", "cathode", "material", "compound", "name", "id"]
TARGET_AL = ["logkstar", "logk", "log10kstar", "log10k"]
RAWK_AL = ["kstar", "k"]
EHULL_AL = ["eabovehull", "ehull", "energyabovehull"]
TEMP_AL = ["temperature", "temp", "tc", "tk", "tcelsius"]


def load_df(raw):
    """Clean uploaded frame. Returns (df, info). Coerces numeric-looking columns, drops empty/duplicate rows."""
    info = {"raw_rows": len(raw), "invalid": {}, "empty_dropped": 0, "dup_dropped": 0}
    df = raw.copy()
    df.columns = [str(c).strip() for c in df.columns]
    df = df.dropna(how="all")
    info["empty_dropped"] = info["raw_rows"] - len(df)
    for c in df.columns:
        if df[c].dtype == object:
            num = pd.to_numeric(df[c], errors="coerce")
            if num.notna().sum() >= 0.5 * df[c].notna().sum() and num.notna().sum() > 0:
                bad = int((df[c].notna() & num.isna()).sum())
                if bad: info["invalid"][c] = bad
                df[c] = num
    info["dup_dropped"] = int(df.duplicated().sum())
    df = df.drop_duplicates().reset_index(drop=True)
    return df, info


def is_const(s):
    """True for constant or numerically constant columns (e.g. 1000/T identical for every row up to float noise)."""
    v = pd.to_numeric(s, errors="coerce").dropna()
    return len(v) == 0 or float(v.max() - v.min()) <= 1e-6 * max(1.0, float(abs(v).max()))


def _find(cols, aliases):
    for c in cols:
        if norm(c) in aliases: return c
    return None


def analyze(df, info):
    cols = list(df.columns)
    num_cols = [c for c in cols if pd.api.types.is_numeric_dtype(df[c])]
    formula = _find(cols, FORMULA_AL)
    if formula is None:
        obj = [c for c in cols if c not in num_cols]
        formula = max(obj, key=lambda c: df[c].nunique(), default=None)
    target = _find(num_cols, TARGET_AL)
    target_note = None
    if target is None:
        rk = _find(num_cols, RAWK_AL)
        if rk is not None and (df[rk].dropna() > 0).all():
            target, target_note = rk, "Raw k* column detected: log10 will be applied."
    desc, used_cols = [], set()
    for key, grp, label, al in DESC:
        col = _find(cols, al + [norm(key)])
        e = {"key": key, "group": grp, "label": label, "column": col, "present": col is not None, "usable": False, "reason": "Not in dataset"}
        if col is not None:
            used_cols.add(col)
            s = df[col]
            if col not in num_cols: e["reason"] = "Non-numeric"
            elif s.notna().mean() < 0.5: e["reason"] = ">50% missing"
            elif is_const(s): e["reason"] = "Constant value (no information)"
            else: e["usable"], e["reason"] = True, "OK"
        desc.append(e)
    miss = {c: int(df[c].isna().sum()) for c in cols if df[c].isna().any()}
    return {
        "columns": cols, "rows": len(df), "n_columns": len(cols), "missing": miss,
        "duplicates_removed": info["dup_dropped"], "empty_rows_removed": info["empty_dropped"],
        "invalid_numeric": info["invalid"], "target_note": target_note,
        "mapping": {"formula": formula, "target": target, "ehull": _find(num_cols, EHULL_AL),
                    "temperature": _find(num_cols, TEMP_AL) or _find(num_cols, ["1000t"]),
                    "features": [e["column"] for e in desc if e["usable"] and e["group"] != "enhanced"]},
        "descriptors": desc,
        "screening_availability": {"ehull": _find(num_cols, EHULL_AL) is not None},
    }


def target_series(df, mp):
    y = pd.to_numeric(df[mp["target"]], errors="coerce")
    if norm(mp["target"]) in RAWK_AL: y = np.log10(y.where(y > 0))
    return y


def pipe(est): return Pipeline([("imp", SimpleImputer(strategy="median")), ("sc", StandardScaler()), ("m", est)])


def _specs():
    return {
     "MLP": (MLPRegressor(hidden_layer_sizes=(32,), max_iter=300, random_state=42), None, "bayes"),
     "SVR": (SVR(cache_size=100), {"m__C": [0.1, 1, 10, 100], "m__gamma": ["scale", 0.01, 0.05, 0.1], "m__epsilon": [0.01, 0.1, 0.3]}, "grid"),
     "GBR": (GradientBoostingRegressor(random_state=42), {"m__n_estimators": [100], "m__learning_rate": [0.05, 0.1], "m__max_depth": [2, 3]}, "grid"),
     "KNN": (KNeighborsRegressor(), {"m__n_neighbors": [2, 3, 5, 7], "m__weights": ["uniform", "distance"]}, "grid"),
     "RF": (RandomForestRegressor(random_state=42, n_jobs=1), {"m__n_estimators": [100], "m__max_depth": [None, 6], "m__min_samples_leaf": [1]}, "grid"),
    }


# ======================================================================================================
#  NEW: grouped validation helpers
#  Each composition appears several times (different temperatures -> different 1000/T), so EVERY split and
#  EVERY cross-validation below is grouped by the composition column: all rows of one composition are always
#  on the same side. Random row-wise splitting is never used.
# ======================================================================================================
N_JOBS = 1
N_FOLDS = 5              # grouped CV folds
TEST_SIZE = 0.40         # 60 : 40 grouped train / test split
SPLIT_SEED = 42
RED_THRESHOLD = 0.95     # |r| above which two descriptors count as redundant
PERM_REPEATS = 20        # permutation-importance repeats
BIG_ROWS = 1500          # above this many TRAINING rows the slow steps use cheaper (still grouped) settings
ELIM_ROWS = 1200         # max rows used by the backward elimination (whole compositions are sampled)
SVR_GRID_SMALL = {"m__C": [1, 10, 100], "m__gamma": ["scale", 0.05], "m__epsilon": [0.1]}
KEEP_ALWAYS = ["1000t", "invt", "inverset"]   # normalised names of the 1000/T column: never removed


def _par():
    """Run the scikit-learn searches on all CPU cores (threads – works the same on Windows and Linux)."""
    try:
        try: from joblib import parallel_config as _pc
        except ImportError: from joblib import parallel_backend as _pc
        return _pc(backend="threading", n_jobs=N_JOBS)
    except Exception:
        return contextlib.nullcontext()


def _pmap(fn, items):
    """Evaluate fn on every item in parallel threads (falls back to a plain loop if joblib is unavailable)."""
    try:
        from joblib import Parallel, delayed
        return Parallel(n_jobs=N_JOBS, prefer="threads")(delayed(fn)(i) for i in items)
    except Exception:
        return [fn(i) for i in items]


def _search(name, est, grid, kind, cv):
    """Hyper-parameter search. cv is a GroupKFold; the composition groups are passed to fit() so folds never split a composition."""
    p = pipe(est); X, y, g = _search.data
    if kind == "bayes":
        try:
            from skopt import BayesSearchCV
            from skopt.space import Real
            s = BayesSearchCV(p, {"m__alpha": Real(1e-5, 1e-1, prior="log-uniform"), "m__learning_rate_init": Real(1e-4, 1e-2, prior="log-uniform")},
                              n_iter=4, cv=cv, scoring="r2", random_state=42, n_jobs=1)
            s.fit(X, y, groups=g); return s, "Bayesian optimisation (scikit-optimize)"
        except Exception:
            from scipy.stats import loguniform
            s = RandomizedSearchCV(p, {"m__alpha": loguniform(1e-5, 1e-1), "m__learning_rate_init": loguniform(1e-4, 1e-2)},
                                   n_iter=4, cv=cv, scoring=SCORING, refit="r2", random_state=42)
            s.fit(X, y, groups=g); return s, "Randomised search (fallback: scikit-optimize unavailable)"
    s = GridSearchCV(p, grid, cv=cv, scoring=SCORING, refit="r2")
    s.fit(X, y, groups=g); return s, "GridSearchCV"


SCORING = {"r2": "r2", "mae": "neg_mean_absolute_error", "rmse": "neg_root_mean_squared_error"}


def _search_metrics(s):
    """Grouped-CV R2/MAE/RMSE of the best candidate, read from the search itself (no second CV pass)."""
    cr = getattr(s, "cv_results_", {}); i = s.best_index_
    if "mean_test_mae" not in cr: return None
    return {"R2": float(cr["mean_test_r2"][i]), "R2_std": float(cr["std_test_r2"][i]), "MAE": float(-cr["mean_test_mae"][i]), "MAE_std": float(cr["std_test_mae"][i]),
            "RMSE": float(-cr["mean_test_rmse"][i]), "RMSE_std": float(cr["std_test_rmse"][i])}


def _cv_eval(best, X, y, cv, groups):
    """Grouped cross-validation of a fitted pipeline (imputer + scaler + model are re-fitted inside every fold)."""
    oof = np.zeros(len(y)); r2, mae, rmse = [], [], []
    for tr, te in cv.split(X, y, groups):
        m = clone(best).fit(X.iloc[tr], y[tr]); p = m.predict(X.iloc[te]); oof[te] = p
        r2.append(r2_score(y[te], p)); mae.append(mean_absolute_error(y[te], p)); rmse.append(mean_squared_error(y[te], p) ** 0.5)
    return oof, {"R2": float(np.mean(r2)), "R2_std": float(np.std(r2)), "MAE": float(np.mean(mae)), "MAE_std": float(np.std(mae)),
                 "RMSE": float(np.mean(rmse)), "RMSE_std": float(np.std(rmse))}


def shapley(model, X, bg, T=8, seed=0):
    """Monte-Carlo permutation Shapley values (interventional, background = training rows).
    All coalitions are built and scored in a few large batches (imputer/scaler are element-wise, so substituting
    features in the transformed space gives exactly the same predictions as substituting before the pipeline)."""
    rng = np.random.default_rng(seed); n, p = X.shape
    pre, est = model[:-1], model[-1]
    Xv = np.asarray(pre.transform(X), dtype=float); Bv = np.asarray(pre.transform(bg), dtype=float)
    phi = np.zeros((n, p)); rows = max(1, 60000 // (T * (p + 1)))
    for a in range(0, n, rows):
        b = min(n, a + rows); m = b - a
        start = Bv[rng.integers(len(Bv), size=(m, T))]
        perm = rng.random((m, T, p)).argsort(-1); rank = perm.argsort(-1)
        k = np.arange(p + 1)[None, None, :, None]
        H = np.where(rank[:, :, None, :] < k, Xv[a:b][:, None, None, :], start[:, :, None, :])
        pr = est.predict(H.reshape(-1, p)).reshape(m, T, p + 1)
        ph = np.zeros((m, T, p)); np.put_along_axis(ph, perm, np.diff(pr, axis=2), axis=2)
        phi[a:b] = ph.sum(1) / T
    return phi, float(est.predict(Bv).mean())


def global_shap(model, X, label_map):
    phi, base = shapley(model, X, X, T=8)
    out = []
    for j, c in enumerate(X.columns):
        v = X[c].values; sd = np.std(v)
        corr = float(np.corrcoef(v, phi[:, j])[0, 1]) if sd > 0 and np.std(phi[:, j]) > 0 else 0.0
        out.append({"feature": c, "label": label_map.get(c, c), "mean_abs": float(np.abs(phi[:, j]).mean()), "mean_signed": float(phi[:, j].mean()),
                    "corr_with_value": corr, "direction": "positive (higher value → higher log k*)" if corr > 0.1 else "negative (higher value → lower log k*)" if corr < -0.1 else "mixed / weak"})
    return sorted(out, key=lambda r: -r["mean_abs"]), base


def _holdout(model, X, y):
    """R2 / MAE / RMSE of a fitted model on some data."""
    p = model.predict(X)
    return {"R2": float(r2_score(y, p)), "MAE": float(mean_absolute_error(y, p)), "RMSE": float(mean_squared_error(y, p) ** 0.5)}


def _relations(X_tr, y_tr, target_name="log10(k*)"):
    """Pearson correlation and covariance matrices of the training descriptors + the target."""
    t = X_tr.copy(); t[target_name] = y_tr
    clean = lambda m: [[(round(float(v), 4) if np.isfinite(v) else None) for v in row] for row in m.values]
    return {"names": list(t.columns), "target": target_name, "n": int(len(t)), "corr": clean(t.corr()), "cov": clean(t.cov())}


# ======================================================================================================
#  NEW: feature selection (all on the TRAINING part only; the test part is never touched)
# ======================================================================================================
def _grouped_cv(X, y, cols, splits, params):
    """Grouped CV of an SVR on the columns `cols`. NEW (1): the StandardScaler (and imputer) live INSIDE the Pipeline,
    so they are re-fitted on the training folds only in every fold -> no leakage from the validation fold."""
    r2s, rms = [], []
    for tr, va in splits:
        m = pipe(SVR(**params)).fit(X.iloc[tr][cols], y[tr]); p = m.predict(X.iloc[va][cols])
        rms.append(float(np.sqrt(np.mean((y[va] - p) ** 2)))); r2s.append(float(r2_score(y[va], p)))
    se = float(np.std(rms, ddof=1) / np.sqrt(len(rms))) if len(rms) > 1 else 0.0
    return {"cv_r2": float(np.mean(r2s)), "cv_rmse": float(np.mean(rms)), "cv_rmse_se": se}


def remove_redundant(X, y, keep):
    """NEW (2): drop one descriptor of every pair with |Pearson r| > 0.95 – the one with the LOWER |Spearman| correlation to the target.
    The 1000/T column is never dropped."""
    cols = list(X.columns); corr = X.corr().abs().fillna(0.0); ys = pd.Series(y, index=X.index)
    sp = {}
    for c in cols:
        v = X[c].corr(ys, method="spearman"); sp[c] = float(abs(v)) if np.isfinite(v) else 0.0
    pairs = sorted(((float(corr.loc[a, b]), a, b) for i, a in enumerate(cols) for b in cols[i + 1:] if corr.loc[a, b] > RED_THRESHOLD), reverse=True)
    alive, dropped = set(cols), []
    for r, a, b in pairs:
        if a not in alive or b not in alive: continue
        if a in keep: drop, kept = b, a
        elif b in keep: drop, kept = a, b
        else: drop, kept = (a, b) if sp[a] < sp[b] else (b, a)
        alive.discard(drop)
        dropped.append({"dropped": drop, "kept": kept, "r": round(r, 4), "spearman_dropped": round(sp[drop], 4), "spearman_kept": round(sp[kept], 4)})
    return [c for c in cols if c in alive], dropped


def select_features(X_tr, y_tr, g_tr, keep, log=print):
    """Redundancy removal -> backward elimination with grouped 5-fold CV (RMSE) -> smallest set within 1 standard error of the best RMSE."""
    cols0 = list(X_tr.columns)
    X_all, y_all_, g_all = X_tr, y_tr, g_tr                      # kept for the final steps
    if len(X_tr) > ELIM_ROWS:                                      # large data: elimination on a random set of WHOLE compositions (final model still uses every row)
        ug = np.unique(g_tr); rng = np.random.default_rng(SPLIT_SEED); rng.shuffle(ug)
        cnt = pd.Series(g_tr).value_counts(); take, tot = [], 0
        for g_ in ug:
            if tot + cnt[g_] > ELIM_ROWS and take: break
            take.append(g_); tot += cnt[g_]
        m_ = np.isin(g_tr, take); X_tr, y_tr, g_tr = X_tr[m_], y_tr[m_], g_tr[m_]
        log(f"[feature selection] large dataset: elimination runs on {tot} rows ({len(take)} compositions); the final model uses all training rows")
    splits = list(GroupKFold(N_FOLDS).split(X_tr, y_tr, g_tr))
    # ---- NEW (2) redundant descriptors ----
    cols1, dropped = remove_redundant(X_tr, y_tr, keep)
    for d_ in dropped: log(f"[feature selection] dropped redundant '{d_['dropped']}' (|r| = {d_['r']:.3f} with '{d_['kept']}'; Spearman to target {d_['spearman_dropped']:.3f} vs {d_['spearman_kept']:.3f})")
    if not dropped: log("[feature selection] no descriptor pair with |r| > 0.95 – nothing dropped as redundant")
    # SVR used INSIDE the elimination: fixed C=10, epsilon=0.1, gamma="scale" (adapts to the number of features) – fast and the same for every candidate.
    # The final SVR is fully re-tuned (grouped grid search) on the selected features afterwards.
    params = {"C": 10, "epsilon": 0.1, "gamma": "scale", "cache_size": 100}
    # ---- NEW (3) backward elimination, grouped 5-fold CV, RMSE ----
    cur = list(cols1)
    hist = [{"n_features": len(cur), "removed": None, **_grouped_cv(X_tr, y_tr, cur, splits, params), "features": list(cur)}]
    while len([c for c in cur if c not in keep]) > 0 and len(cur) > 1:
        cands = [[x for x in cur if x != c] for c in cur if c not in keep]
        res = _pmap(lambda cs: (cs, _grouped_cv(X_tr, y_tr, cs, splits, params)), cands)
        cs, m = min(res, key=lambda t: t[1]["cv_rmse"])          # removal that gives the LOWEST RMSE
        removed = [c for c in cur if c not in cs][0]; cur = cs
        hist.append({"n_features": len(cur), "removed": removed, **m, "features": list(cur)})
        log(f"[feature selection] {len(cur):2d} features | removed {removed:<20s} | CV R2 {m['cv_r2']:.3f} | CV RMSE {m['cv_rmse']:.3f}")
    # ---- NEW (4) one-standard-error rule ----
    imin = min(range(len(hist)), key=lambda i: hist[i]["cv_rmse"]); limit = hist[imin]["cv_rmse"] + hist[imin]["cv_rmse_se"]
    chosen = min([h for h in hist if h["cv_rmse"] <= limit], key=lambda h: (h["n_features"], h["cv_rmse"]))
    selected = [c for c in cols0 if c in chosen["features"]]     # keep the original column order; 1000/T is always inside (never removed)
    full_splits = list(GroupKFold(N_FOLDS).split(X_all, y_all_, g_all))
    return {"elimination_rows": int(len(X_tr)), "candidates": cols0, "after_redundancy": cols1, "dropped_redundant": dropped, "svr_params": params, "history": hist,
            "min_rmse": hist[imin]["cv_rmse"], "min_rmse_se": hist[imin]["cv_rmse_se"], "rmse_limit": limit, "min_n_features": hist[imin]["n_features"],
            "selected": selected, "selected_n": len(selected)}, full_splits


def perm_importance(X_tr, y_tr, splits, cols, params):
    """NEW (5): permutation importance (20 repeats, neg-RMSE) on the HELD-OUT folds of the final feature set; averaged over folds."""
    imps = []
    for tr, va in splits:
        m = pipe(SVR(**params)).fit(X_tr.iloc[tr][cols], y_tr[tr])
        r = permutation_importance(m, X_tr.iloc[va][cols], y_tr[va], n_repeats=PERM_REPEATS, scoring="neg_root_mean_squared_error", random_state=42)
        imps.append(r.importances_mean)
    imps = np.array(imps)
    out = [{"feature": c, "importance": float(imps[:, j].mean()), "std": float(imps[:, j].std())} for j, c in enumerate(cols)]
    return sorted(out, key=lambda r: -r["importance"])


def train_all(df, mp, cols_primary, cols_enh, label_map, q=AD_QUANTILE):
    y_all = target_series(df, mp); keep_rows = y_all.notna()
    if keep_rows.sum() < 20: raise ValueError(f"Only {int(keep_rows.sum())} rows have a valid target – at least 20 are needed for a grouped 60:40 split with cross-validation.")
    d = df[keep_rows]; y = y_all[keep_rows].values
    # NEW: non-numeric columns (Material composition, A, B ...) are never features; the target is LogKstar
    non_numeric = [c for c in d.columns if not pd.api.types.is_numeric_dtype(d[c])]
    feats = [c for c in cols_primary if pd.api.types.is_numeric_dtype(d[c])]
    Xall = d[feats]
    # NEW: groups = composition column (rows of one composition = one group)
    fcol = mp.get("formula")
    groups = d[fcol].astype(str).values if fcol in d.columns else np.arange(len(d))
    n_groups = int(len(set(groups)))
    if n_groups < 8: raise ValueError(f"Only {n_groups} distinct compositions – at least 8 are needed for a grouped 60:40 split with 5-fold grouped CV.")
    # NEW: grouped 60:40 split – a composition is either completely in training or completely in testing
    tr_i, te_i = next(GroupShuffleSplit(n_splits=1, test_size=TEST_SIZE, random_state=SPLIT_SEED).split(Xall, y, groups))
    tr_i, te_i = np.sort(tr_i), np.sort(te_i)
    if len(set(groups[tr_i])) < N_FOLDS: raise ValueError(f"Only {len(set(groups[tr_i]))} compositions fall in the training part – at least {N_FOLDS} are needed for grouped 5-fold CV.")
    Xa_tr, Xa_te, y_tr, y_te, g_tr = Xall.iloc[tr_i], Xall.iloc[te_i], y[tr_i], y[te_i], groups[tr_i]
    keep = [c for c in feats if norm(c) in KEEP_ALWAYS or (mp.get("temperature") == c)]      # NEW (6): 1000/T always stays
    # ---- NEW (2)-(4): feature selection on the training part ----
    fs, splits = select_features(Xa_tr, y_tr, g_tr, keep)
    selected_features = fs["selected"]                                                        # NEW (8): used by everything below
    print("Selected features:", selected_features, flush=True)
    X_tr, X_te = Xa_tr[selected_features], Xa_te[selected_features]
    gkf = GroupKFold(N_FOLDS)
    # ---- model comparison on the SELECTED features (grouped tuning, scaler inside the pipeline) ----
    _search.data = (X_tr, y_tr, g_tr)
    comp, best_models, svr_search = [], {}, None
    big = len(X_tr) > BIG_ROWS
    if big: print(f"[training] {len(X_tr)} training rows: using a smaller SVR grid to stay fast", flush=True)
    for name, (est, grid, kind) in _specs().items():
        if name == "SVR" and big: grid = SVR_GRID_SMALL
        with _par():
            s, method = _search(name, est, grid, kind, gkf)
        best = s.best_estimator_; cv = _search_metrics(s) or _cv_eval(best, X_tr, y_tr, gkf, g_tr)[1]
        trm, tem = _holdout(best, X_tr, y_tr), _holdout(best, X_te, y_te)
        params = {k.replace("m__", ""): (v if isinstance(v, (int, float, str, type(None))) else str(v)) for k, v in s.best_params_.items()}
        comp.append({"model": name, "search": method, "params": params, "R2": tem["R2"], "MAE": tem["MAE"], "RMSE": tem["RMSE"],       # test-set scores
                     "train_R2": trm["R2"], "train_MAE": trm["MAE"], "train_RMSE": trm["RMSE"],
                     "cv_R2": cv["R2"], "cv_R2_std": cv["R2_std"], "cv_MAE": cv["MAE"], "cv_RMSE": cv["RMSE"]})
        if name == "SVR":
    best_models[name] = best
        if name == "SVR": svr_search = s
    svr = best_models["SVR"]
    svr_params = {k.replace("m__", ""): v for k, v in svr_search.best_params_.items()}; svr_params["cache_size"] = 100
    # ---- NEW (5): permutation importance on held-out folds of the final set ----
    perm = perm_importance(X_tr, y_tr, splits, selected_features, svr_params)
    # ---- NEW (7): original model (all features) vs new model (selected features): grouped-CV and test-set scores ----
    new_cv = _grouped_cv(X_tr, y_tr, selected_features, splits, svr_params); new_te = _holdout(svr, X_te, y_te)
    _search.data = (Xa_tr, y_tr, g_tr)
    with _par():
        so, _ = _search("SVR", SVR(cache_size=100), SVR_GRID_SMALL if big else _specs()["SVR"][1], "grid", gkf)
    po = {k.replace("m__", ""): v for k, v in so.best_params_.items()}; po["cache_size"] = 100
    old_cv = _grouped_cv(Xa_tr, y_tr, feats, splits, po); old_te = _holdout(so.best_estimator_, Xa_te, y_te)
    versus = {"original": {"label": "Original model (all features)", "n_features": len(feats), "features": feats, "cv_r2": old_cv["cv_r2"], "cv_rmse": old_cv["cv_rmse"], "test_r2": old_te["R2"], "test_rmse": old_te["RMSE"], "params": {k: v for k, v in po.items() if k != "cache_size"}},
              "selected": {"label": "New model (selected features)", "n_features": len(selected_features), "features": selected_features, "cv_r2": new_cv["cv_r2"], "cv_rmse": new_cv["cv_rmse"], "test_r2": new_te["R2"], "test_rmse": new_te["RMSE"], "params": {k: v for k, v in svr_params.items() if k != "cache_size"}}}
    for k, v in versus.items(): print(f"[{v['label']}] {v['n_features']} features | grouped-CV R2 {v['cv_r2']:.3f} RMSE {v['cv_rmse']:.3f} | test R2 {v['test_r2']:.3f} RMSE {v['test_rmse']:.3f}", flush=True)
    # ---- applicability domain, SHAP, enhanced model: all on the selected features ----
    Xs = svr[:-1].transform(X_tr); mu = Xs.mean(0); VI = np.linalg.pinv(np.cov(Xs, rowvar=False).reshape(Xs.shape[1], Xs.shape[1]))
    dtr = np.sqrt(np.einsum("ij,jk,ik->i", Xs - mu, VI, Xs - mu)); thr = float(np.quantile(dtr, q))
    best_test = max(comp, key=lambda r: r["R2"])["model"]
    gs, base = global_shap(svr, X_tr, label_map)
    p_tr, p_te = svr.predict(X_tr), svr.predict(X_te)
    enh = None; extra = [c for c in cols_enh if c not in cols_primary]
    if extra:
        cols_e = selected_features + extra; Xe = d[cols_e]; Xe_tr, Xe_te = Xe.iloc[tr_i], Xe.iloc[te_i]
        se = clone(svr).fit(Xe_tr, y_tr)   # same tuned SVR settings (no second grid search -> faster)
        _, me = _cv_eval(se, Xe_tr, y_tr, gkf, g_tr); ge, _ = global_shap(se, Xe_tr, label_map)
        enh = {"features": cols_e, "cv": me, "test": _holdout(se, Xe_te, y_te), "shap": ge, "note": "Interpretation-only model (paper Sec. 4.1). NOT used for screening."}
    idx = d.index
    names = [str(v) for v in d[fcol].iloc[tr_i]] if fcol in d.columns else None
    stats = {c: {"min": _f(Xall[c].min()), "max": _f(Xall[c].max()), "median": _f(Xall[c].median())} for c in selected_features}
    # ---- everything needed to predict a single new cathode is saved with the model (only the SELECTED features) ----
    bundle = {"pipeline": svr, "features": selected_features, "mu": mu, "VI": VI, "threshold": thr, "quantile": q,
              "oof": {int(i): float(v) for i, v in zip(idx[te_i], p_te)},
              "train_index": [int(i) for i in idx[tr_i]], "test_index": [int(i) for i in idx[te_i]],
              "background": X_tr.reset_index(drop=True), "train_formulas": names, "train_y": [float(v) for v in y_tr], "feature_stats": stats}
    fs_out = {k: v for k, v in fs.items() if k != "svr_params"}
    fs_out.update({"non_numeric_dropped": non_numeric, "keep_always": keep, "permutation": perm, "versus": versus, "n_candidates": len(feats),
                   "svr_params_elimination": {k: v for k, v in fs["svr_params"].items() if k != "cache_size"}, "perm_repeats": PERM_REPEATS, "folds": N_FOLDS})
    result = {"comparison": comp, "primary": "SVR", "best_by_test_r2": best_test, "features": selected_features, "selected_features": selected_features,
              "n_train": int(len(tr_i)), "n_test": int(len(te_i)), "n_total": int(keep_rows.sum()), "n_groups": n_groups,
              "n_train_groups": int(len(set(g_tr))), "n_test_groups": int(len(set(groups[te_i]))),
              "n_dropped_no_target": int((~keep_rows).sum()), "ad": {"quantile": q, "threshold": thr, "n_train": int(len(dtr))},
              "parity": {"y": y_te.tolist(), "pred": p_te.tolist(), "y_train": y_tr.tolist(), "pred_train": p_tr.tolist()},
              "stats": _relations(Xa_tr, y_tr), "feature_stats": stats, "feature_selection": fs_out,
              "shap": gs, "shap_base": base, "enhanced": enh,
              "cv": "Grouped 60:40 split by composition (GroupShuffleSplit, seed 42): a composition is never in both parts. Feature selection and tuning use grouped 5-fold CV (GroupKFold) inside the 60% training part only; scores shown are on the unseen 40%."}
    return result, bundle


def _f(v):
    try:
        v = float(v); return None if np.isnan(v) or np.isinf(v) else v
    except Exception: return None


def screen(df, mp, bundle, label_map, ehull_limit=EHULL_LIMIT, orr_limit=ORR_LIMIT):
    pl, cols = bundle["pipeline"], bundle["features"]; X = df[cols]
    pred = pl.predict(X); Xs = pl[:-1].transform(X)
    dist = np.sqrt(np.einsum("ij,jk,ik->i", Xs - bundle["mu"], bundle["VI"], Xs - bundle["mu"])); thr = bundle["threshold"]
    phi, base = shapley(pl, X, bundle["background"], T=8)
    eh = df[mp["ehull"]] if mp.get("ehull") and mp["ehull"] in df.columns else None
    rows = []
    for i in range(len(df)):
        pl_k = float(pred[i]); inside = bool(dist[i] <= thr); fails, nas = [], []
        if not inside: fails.append(f"Outside applicability domain (Mahalanobis {dist[i]:.2f} > threshold {thr:.2f}); prediction is less reliable.")
        ev = _f(eh.iloc[i]) if eh is not None else None
        if ev is None: er = "NOT AVAILABLE"; nas.append("Ehull value not available - stability criterion not evaluated.")
        elif ev <= ehull_limit: er = "PASS"
        else: er = "FAIL"; fails.append(f"Ehull {ev:.1f} meV/atom exceeds the {ehull_limit:g} meV/atom limit (LSC value).")
        orr = "PASS" if pl_k >= orr_limit else "FAIL"
        if orr == "FAIL": fails.append(f"ORR activity criterion not satisfied: predicted log10(k*) {pl_k:.2f} < benchmark {orr_limit:.2f} (LSC benchmark used in the research paper).")
        final = "FAIL" if fails else ("INCOMPLETE" if nas else "PASS")
        rows.append({"row_index": i, "formula": str(df[mp["formula"]].iloc[i]) if mp.get("formula") else f"Row {i+1}",
            "pred_log": pl_k, "pred_k": float(10 ** pl_k), "dist": float(dist[i]), "ad": "INSIDE" if inside else "OUTSIDE", "ad_result": "PASS" if inside else "FAIL",
            "ehull": ev, "ehull_result": er, "orr_value": pl_k, "orr_result": orr, "final": final,
            "reason": " | ".join(fails) if fails else ("; ".join(nas) if nas else ""),
            "detail": {"original": {c: _f(v) if isinstance(v, (int, float, np.number)) else (None if pd.isna(v) else str(v)) for c, v in df.iloc[i].items()},
                       "features": {c: _f(X.iloc[i][c]) for c in cols},
                       "shap": [{"feature": c, "label": label_map.get(c, c), "value": float(phi[i, j])} for j, c in enumerate(cols)],
                       "shap_base": base, "cv_pred_log": bundle["oof"].get(i), "in_training": i not in bundle["oof"],
                       "thresholds": {"ad": thr, "ehull": ehull_limit, "orr": orr_limit}, "fails": fails, "not_available": nas}})
    return rows


# ---------------- closeness-to-passing ranking (dataset-independent) ----------------
# Each available criterion gives a normalised shortfall (0 = criterion satisfied):
#   AD   : (distance - threshold) / threshold          ORR : log10(k*) deficit below -6.40 (1.0 = one log unit)
#   Ehull: (Ehull - 57) / 57
# Score = MEAN shortfall over the criteria that could actually be evaluated (so datasets with
# fewer screening columns stay comparable). Fixed cut-offs, not data quantiles:
TIER_GREEN = 0.10   # score <= 0.10  -> "near passing"
TIER_RED = 0.50     # score  > 0.50  -> "far from passing"


def closeness(dist, thr, ehull, ehull_limit, pred, orr_limit=ORR_LIMIT):
    p = {"ad": max(0.0, (dist - thr) / thr) if thr else 0.0,
         "ehull": None if ehull is None else max(0.0, (ehull - ehull_limit) / ehull_limit),
         "orr": max(0.0, orr_limit - pred)}
    v = [x for x in p.values() if x is not None]
    s = float(sum(v) / len(v))
    return s, p, ("green" if s <= TIER_GREEN else "red" if s > TIER_RED else "orange")


def predict_single(bundle, values, label_map, formula=None, ehull=None, ehull_limit=EHULL_LIMIT, orr_limit=ORR_LIMIT):
    """Predict ONE new cathode with the saved model. Uses exactly the same code as the batch screening, so decisions always agree."""
    cols = bundle["features"]
    row = {c: (float(values[c]) if values.get(c) not in (None, "") else np.nan) for c in cols}
    df = pd.DataFrame([row]); df["_formula"] = formula or "New cathode"; df["_ehull"] = np.nan if ehull in (None, "") else float(ehull)
    r = screen(df, {"formula": "_formula", "ehull": "_ehull"}, bundle, label_map, ehull_limit, orr_limit)[0]
    r["imputed"] = [c for c in cols if np.isnan(row[c])]
    return r


def compare_with_training(bundle, values, k=3):
    """Compare ONE cathode with the saved training data: range check for every descriptor + the k most similar training cathodes."""
    cols, bg = bundle["features"], bundle["background"]
    row = pd.DataFrame([{c: (float(values[c]) if values.get(c) not in (None, "") else np.nan) for c in cols}])
    pre = bundle["pipeline"][:-1]
    A = np.asarray(pre.transform(bg), dtype=float); b = np.asarray(pre.transform(row), dtype=float)[0]
    dist = np.sqrt(((A - b) ** 2).sum(1)); order = np.argsort(dist)[:k]
    names, ys = bundle.get("train_formulas"), bundle.get("train_y")
    near = [{"formula": (names[i] if names else f"Training cathode {i + 1}"), "distance": float(dist[i]), "log_k": (float(ys[i]) if ys else None)} for i in order]
    ranges = []
    for c in cols:
        v = row[c].iloc[0]; lo, hi = float(bg[c].min()), float(bg[c].max())
        ranges.append({"feature": c, "value": None if np.isnan(v) else float(v), "min": lo, "max": hi, "inside": bool(np.isnan(v) or lo <= v <= hi)})
    return {"nearest": near, "ranges": ranges, "n_outside": sum(1 for r in ranges if not r["inside"]), "n_training": int(len(bg))}
