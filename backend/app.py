import os, io, re, json, uuid, shutil, hashlib, sqlite3, secrets, datetime as dt
from pathlib import Path
from functools import wraps
import numpy as np, pandas as pd, joblib
from flask import Flask, request, jsonify, g, send_file
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
import ml

BASE = Path(__file__).resolve().parent.parent
# Data lives OUTSIDE the code folder (your home directory) so re-unzipping a new version never loses history.
if os.environ.get("STORAGE_DIR"): STORE = Path(os.environ["STORAGE_DIR"])
else:
    STORE = Path.home() / ".perovskite_screening"
    if not (STORE / "app.db").exists() and (BASE / "storage" / "app.db").exists():   # one-time migration of an older ./storage folder
        shutil.copytree(BASE / "storage", STORE, dirs_exist_ok=True)
for d in ("uploads", "models"): (STORE / d).mkdir(parents=True, exist_ok=True)
DB = STORE / "app.db"; KEYFILE = STORE / "secret.key"
if not KEYFILE.exists(): KEYFILE.write_text(secrets.token_hex(32))
SER = URLSafeTimedSerializer(os.environ.get("SECRET_KEY", KEYFILE.read_text()))
SHARED_HASH = generate_password_hash(os.environ.get("APP_SHARED_PASSWORD", "NGIT"))
ALLOWED = {".csv", ".xlsx", ".xls"}; SUMMARY_VER = 3

app = Flask(__name__, static_folder=str(BASE / "frontend"), static_url_path="")
app.config["MAX_CONTENT_LENGTH"] = 15 * 1024 * 1024

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, roll_number TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, created_at TEXT);
CREATE TABLE IF NOT EXISTS datasets(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), filename TEXT, stored_path TEXT,
 upload_date TEXT, row_count INT, column_count INT, target_column TEXT, formula_column TEXT, feature_list TEXT,
 analysis_json TEXT, train_json TEXT, summary_json TEXT, status TEXT DEFAULT 'uploaded', content_hash TEXT);
CREATE TABLE IF NOT EXISTS models(id INTEGER PRIMARY KEY, dataset_id INT NOT NULL REFERENCES datasets(id) ON DELETE CASCADE, model_type TEXT, is_primary INT,
 training_date TEXT, R2 REAL, MAE REAL, RMSE REAL, model_path TEXT, scaler_path TEXT, params_json TEXT);
CREATE TABLE IF NOT EXISTS screening_results(id INTEGER PRIMARY KEY, dataset_id INT NOT NULL REFERENCES datasets(id) ON DELETE CASCADE, row_index INT, formula TEXT,
 predicted_log_kstar REAL, predicted_kstar REAL, mahalanobis_distance REAL, applicability_domain TEXT, ad_result TEXT, ehull REAL, ehull_result TEXT,
 cost REAL, cost_result TEXT, orr_value REAL, orr_result TEXT, final_result TEXT, failure_reason TEXT, detail_json TEXT);
CREATE TABLE IF NOT EXISTS export_history(id INTEGER PRIMARY KEY, dataset_id INT, user_id INT, kind TEXT, created_at TEXT);
CREATE INDEX IF NOT EXISTS ix_sr ON screening_results(dataset_id);
"""
def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB); g.db.row_factory = sqlite3.Row; g.db.execute("PRAGMA foreign_keys=ON")
    return g.db
@app.teardown_appcontext
def _close(_):
    d = g.pop("db", None)
    if d: d.close()
with sqlite3.connect(DB) as _c:
    _c.executescript(SCHEMA)
    for tbl, cols in (("screening_results", (("rank", "INT"), ("score", "REAL"), ("tier", "TEXT"))), ("datasets", (("content_hash", "TEXT"),))):
        have = {r[1] for r in _c.execute(f"PRAGMA table_info({tbl})")}
        for col, typ in cols:
            if col not in have: _c.execute(f"ALTER TABLE {tbl} ADD COLUMN {col} {typ}")

def now(): return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
def err(msg, code=400, **kw): return jsonify({"error": msg, **kw}), code
def jd(x): return json.dumps(x, default=lambda o: o.item() if hasattr(o, "item") else str(o))
def dpath(r): return STORE / "uploads" / str(r["user_id"]) / Path(r["stored_path"]).name   # resolved from our own storage dir (portable)

def fkey(s):
    """Canonical formula key: 'La0.6Sr0.4Co1O3' == 'La0.6Sr0.4CoO3'."""
    t = re.sub(r"\s+", "", str(s))
    if t and re.fullmatch(r"(?:[A-Z][a-z]?\d*\.?\d*)+", t):
        acc = {}
        for el, n in re.findall(r"([A-Z][a-z]?)(\d*\.?\d*)", t): acc[el] = acc.get(el, 0) + (float(n) if n else 1.0)
        return "".join(f"{k}{round(v, 4):g}" for k, v in sorted(acc.items()))
    return t.lower()

def auth(fn):
    @wraps(fn)
    def w(*a, **k):
        h = request.headers.get("Authorization", "")
        try: g.uid = SER.loads(h.replace("Bearer ", "", 1), max_age=7 * 86400)["uid"]
        except (BadSignature, SignatureExpired, KeyError): return err("Please log in again.", 401)
        u = db().execute("SELECT roll_number FROM users WHERE id=?", (g.uid,)).fetchone()
        if not u: return err("Unknown user.", 401)
        g.roll = u["roll_number"]; return fn(*a, **k)
    return w
def own(did):
    r = db().execute("SELECT * FROM datasets WHERE id=? AND user_id=?", (did, g.uid)).fetchone()   # ownership check on every dataset request
    if not r: raise LookupError
    return r
@app.errorhandler(LookupError)
def _nf(_): return err("Dataset not found.", 404)
@app.errorhandler(413)
def _big(_): return err("File too large (max 15 MB).", 413)
@app.errorhandler(Exception)
def _any(e):
    if hasattr(e, "code") and isinstance(e.code, int): return err(getattr(e, "description", str(e)), e.code)
    app.logger.exception(e); return err(f"Server error: {e}", 500)

def read_file(path):
    p = str(path)
    if p.lower().endswith(".csv"): raw = pd.read_csv(p)
    else:
        sheets = pd.read_excel(p, sheet_name=None); raw = max(sheets.values(), key=lambda d: d.size) if sheets else pd.DataFrame()
    return ml.load_df(raw)
def chash(df): return hashlib.sha256(df.to_csv(index=False).encode()).hexdigest()
def labels(an): return {e["column"]: e["label"] for e in an["descriptors"] if e["column"]}

def drop_dataset(r):
    dpath(r).unlink(missing_ok=True); shutil.rmtree(STORE / "models" / str(r["id"]), ignore_errors=True)
    db().execute("DELETE FROM datasets WHERE id=?", (r["id"],))

def dedupe_user():
    """Make sure each distinct dataset appears once in the history (keeps the screened / newest copy)."""
    c = db(); groups = {}
    for r in c.execute("SELECT * FROM datasets WHERE user_id=? ORDER BY id", (g.uid,)).fetchall():
        h = r["content_hash"]
        if not h:
            try: h = chash(read_file(dpath(r))[0]); c.execute("UPDATE datasets SET content_hash=? WHERE id=?", (h, r["id"]))
            except Exception: continue
        groups.setdefault(h, []).append(r)
    for rs in groups.values():
        if len(rs) > 1:
            keep = max(rs, key=lambda r: (r["status"] == "screened", r["id"]))
            for r in rs:
                if r["id"] != keep["id"]: drop_dataset(r)
    c.commit()

# ---------------- auth ----------------
@app.post("/api/login")
def login():
    b = request.get_json(silent=True) or {}
    roll = str(b.get("roll_number", "")).strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{6,15}", roll): return err("Enter a valid roll number (6-15 letters/digits, e.g. 23CSE001).")
    if not check_password_hash(SHARED_HASH, str(b.get("password", ""))): return err("Invalid roll number or password.", 401)
    c = db(); u = c.execute("SELECT * FROM users WHERE roll_number=?", (roll,)).fetchone()
    if not u:
        c.execute("INSERT INTO users(roll_number,password_hash,created_at) VALUES(?,?,?)", (roll, generate_password_hash(str(b["password"])), now())); c.commit()
        u = c.execute("SELECT * FROM users WHERE roll_number=?", (roll,)).fetchone()
    return jsonify({"token": SER.dumps({"uid": u["id"]}), "roll_number": roll})

# ---------------- ranking ----------------
def rank_db(did):
    c = db(); rows = c.execute("SELECT id,mahalanobis_distance,ehull,predicted_log_kstar,detail_json FROM screening_results WHERE dataset_id=?", (did,)).fetchall(); out = []
    for r in rows:
        det = json.loads(r["detail_json"]); t = det["thresholds"]
        sc, parts, tier = ml.closeness(r["mahalanobis_distance"], t["ad"], r["ehull"], t["ehull"], r["predicted_log_kstar"], t["orr"])
        det["shortfalls"] = parts; out.append((sc, -r["predicted_log_kstar"], r["id"], tier, jd(det)))
    out.sort()
    c.executemany("UPDATE screening_results SET score=?, rank=?, tier=?, detail_json=? WHERE id=?", [(o[0], i + 1, o[3], o[4], o[2]) for i, o in enumerate(out)])
    row = c.execute("SELECT summary_json FROM datasets WHERE id=?", (did,)).fetchone()
    if row and row["summary_json"]:
        sm = json.loads(row["summary_json"]); sm.update({f"tier_{k}": sum(1 for o in out if o[3] == k) for k in ("green", "orange", "red")})
        sm["tiers"] = {"green": ml.TIER_GREEN, "red": ml.TIER_RED}; c.execute("UPDATE datasets SET summary_json=? WHERE id=?", (jd(sm), did))
    c.commit()

def do_screen(r):
    did = r["id"]; tj = json.loads(r["train_json"]); mp = tj["mapping"]
    df, _ = read_file(dpath(r)); bundle = joblib.load(STORE / "models" / str(did) / "svr_pipeline.joblib")
    rows = ml.screen(df, mp, bundle, labels(json.loads(r["analysis_json"])))
    seen, uniq = set(), []
    for x in rows:                                    # same formula is never counted twice
        k = fkey(x["formula"])
        if k not in seen: seen.add(k); uniq.append(x)
    dup = len(rows) - len(uniq); rows = uniq
    c = db(); c.execute("DELETE FROM screening_results WHERE dataset_id=?", (did,))
    c.executemany("INSERT INTO screening_results(dataset_id,row_index,formula,predicted_log_kstar,predicted_kstar,mahalanobis_distance,applicability_domain,ad_result,ehull,ehull_result,orr_value,orr_result,final_result,failure_reason,detail_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [(did, x["row_index"], x["formula"], x["pred_log"], x["pred_k"], x["dist"], x["ad"], x["ad_result"], x["ehull"], x["ehull_result"], x["orr_value"], x["orr_result"], x["final"], x["reason"], jd(x["detail"])) for x in rows])
    cnt = lambda k, v: sum(1 for x in rows if x[k] == v)
    s = {"v": SUMMARY_VER, "total": len(rows), "PASS": cnt("final", "PASS"), "FAIL": cnt("final", "FAIL"), "INCOMPLETE": cnt("final", "INCOMPLETE"),
         "inside_ad": cnt("ad", "INSIDE"), "outside_ad": cnt("ad", "OUTSIDE"), "duplicates_merged": dup,
         **{f"{k}_{v}": cnt(f"{k}_result", v.upper().replace("_", " ")) for k in ("ehull", "orr") for v in ("pass", "fail", "not_available")},
         "ehull_available": mp.get("ehull") is not None, "pass_pct": round(100 * cnt("final", "PASS") / max(len(rows), 1), 1),
         "limits": {"ehull": ml.EHULL_LIMIT, "orr": ml.ORR_LIMIT, "ad_quantile": ml.AD_QUANTILE}}
    c.execute("UPDATE datasets SET summary_json=?, status='screened' WHERE id=?", (jd(s), did)); c.commit(); rank_db(did)

def refresh_old(r):
    """Datasets screened by an older version (e.g. with cost) are silently re-screened from the saved model."""
    s = json.loads(r["summary_json"] or "{}")
    if r["status"] == "screened" and s.get("v") != SUMMARY_VER and (STORE / "models" / str(r["id"]) / "svr_pipeline.joblib").exists():
        try: do_screen(r); return own(r["id"])
        except Exception as e: app.logger.warning("re-screen failed: %s", e)
    return r

# ---------------- datasets ----------------
def ds_card(r):
    s = json.loads(r["summary_json"] or "{}")
    return {"id": r["id"], "filename": r["filename"], "upload_date": r["upload_date"], "row_count": s.get("total", r["row_count"]), "status": r["status"],
            "model": "SVR" if r["status"] == "screened" else None, "pass": s.get("PASS", 0), "fail": s.get("FAIL", 0)}

@app.get("/api/dashboard")
@auth
def dashboard():
    dedupe_user()
    for r in db().execute("SELECT * FROM datasets WHERE user_id=? ORDER BY id", (g.uid,)).fetchall(): refresh_old(r)
    rows = db().execute("SELECT * FROM datasets WHERE user_id=? ORDER BY id DESC", (g.uid,)).fetchall()
    uniq = {}
    for r in sorted(rows, key=lambda r: r["id"]):                   # totals: one entry per distinct formula (latest result wins)
        if r["status"] != "screened": continue
        for x in db().execute("SELECT formula,final_result FROM screening_results WHERE dataset_id=?", (r["id"],)): uniq[fkey(x["formula"])] = x["final_result"]
    vals = list(uniq.values())
    return jsonify({"roll_number": g.roll, "datasets": [ds_card(r) for r in rows],
        "totals": {"datasets": len(rows), "cathodes_screened": len(vals), "pass": vals.count("PASS"), "fail": vals.count("FAIL")}})

@app.post("/api/datasets")
@auth
def upload():
    f = request.files.get("file")
    if not f or not f.filename: return err("No file uploaded.")
    ext = Path(f.filename).suffix.lower()
    if ext not in ALLOWED: return err(f"Unsupported file type '{ext}'. Upload .csv, .xlsx or .xls.")
    d = STORE / "uploads" / str(g.uid); d.mkdir(exist_ok=True)
    path = d / f"{uuid.uuid4().hex[:10]}_{secure_filename(f.filename)}"; f.save(path)
    try: df, info = read_file(path)
    except Exception as e: path.unlink(missing_ok=True); return err(f"Could not read the file (invalid or corrupted): {e}")
    if df.empty or df.shape[1] < 2: path.unlink(missing_ok=True); return err("The dataset is empty or has fewer than 2 columns.")
    h = chash(df); dedupe_user()
    ex = db().execute("SELECT id FROM datasets WHERE user_id=? AND content_hash=?", (g.uid, h)).fetchone()
    if ex: path.unlink(missing_ok=True); return jsonify({"id": ex["id"], "duplicate": True})
    an = ml.analyze(df, info); m = an["mapping"]
    cur = db().execute("INSERT INTO datasets(user_id,filename,stored_path,upload_date,row_count,column_count,target_column,formula_column,feature_list,analysis_json,status,content_hash) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (g.uid, f.filename, str(path), now(), len(df), df.shape[1], m["target"], m["formula"], jd(m["features"]), jd(an), "uploaded", h))
    db().commit(); return jsonify({"id": cur.lastrowid, "duplicate": False})

@app.get("/api/datasets/<int:did>")
@auth
def get_ds(did):
    r = refresh_old(own(did))
    return jsonify({**ds_card(r), "analysis": json.loads(r["analysis_json"]), "train": json.loads(r["train_json"]) if r["train_json"] else None,
                    "summary": json.loads(r["summary_json"]) if r["summary_json"] else None})

@app.delete("/api/datasets/<int:did>")
@auth
def del_ds(did): drop_dataset(own(did)); db().commit(); return jsonify({"ok": True})

@app.post("/api/datasets/<int:did>/train")
@auth
def train(did):
    r = own(did); an = json.loads(r["analysis_json"]); b = request.get_json(silent=True) or {}
    mp = {**an["mapping"], **{k: v for k, v in (b.get("mapping") or {}).items() if v}}
    if not mp.get("formula"): return err("No chemical-formula column detected. Choose one in the column mapping.")
    if not mp.get("target"): return err("No log10(k*) target column detected. Choose one in the column mapping.")
    df, _ = read_file(dpath(r))
    if mp["target"] not in df.columns or mp["formula"] not in df.columns: return err("Selected columns do not exist in the dataset.")
    feats = [c for c in mp.get("features", []) if c in df.columns and c != mp["target"] and pd.api.types.is_numeric_dtype(df[c]) and not ml.is_const(df[c])]
    if len(feats) < 2: return err("Fewer than 2 usable numeric descriptor columns are available in this dataset - cannot train.")
    enh = [e["column"] for e in an["descriptors"] if e["usable"] and e["group"] == "enhanced"]
    try: res, bundle = ml.train_all(df, mp, feats, feats + [c for c in enh if c not in feats], labels(an))
    except ValueError as e: return err(str(e))
    except Exception as e: app.logger.exception(e); return err(f"Training failed: {e}", 500)
    mdir = STORE / "models" / str(did); mdir.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, mdir / "svr_pipeline.joblib"); joblib.dump(bundle["pipeline"].named_steps["sc"], mdir / "scaler.joblib")
    (mdir / "config.json").write_text(jd({"features": res["selected_features"], "all_candidate_features": feats, "mapping": mp, "preprocessing": "median imputer + StandardScaler inside Pipeline", "ad": res["ad"]}))
    res.update({"mapping": mp, "unavailable_descriptors": [{"key": e["key"], "label": e["label"], "reason": e["reason"]} for e in an["descriptors"] if not e["usable"]]})
    c = db(); c.execute("DELETE FROM models WHERE dataset_id=?", (did,)); c.execute("DELETE FROM screening_results WHERE dataset_id=?", (did,))
    for m in res["comparison"]:
        p = m["model"] == "SVR"
        c.execute("INSERT INTO models(dataset_id,model_type,is_primary,training_date,R2,MAE,RMSE,model_path,scaler_path,params_json) VALUES(?,?,?,?,?,?,?,?,?,?)",
                  (did, m["model"], int(p), now(), m["R2"], m["MAE"], m["RMSE"], str(mdir / "svr_pipeline.joblib") if p else None, str(mdir / "scaler.joblib") if p else None, jd(m["params"])))
    c.execute("UPDATE datasets SET train_json=?, target_column=?, formula_column=?, feature_list=?, status='trained', summary_json=NULL WHERE id=?", (jd(res), mp["target"], mp["formula"], jd(res["selected_features"]), did)); c.commit()
    return jsonify({"ok": True})

_BUNDLES = {}
def load_bundle(did):
    """The trained model + training data are saved to disk at training time; predictions always use that saved file."""
    p = STORE / "models" / str(did) / "svr_pipeline.joblib"
    if not p.exists(): return None
    k = (did, p.stat().st_mtime_ns)
    if k not in _BUNDLES:
        if len(_BUNDLES) >= 4: _BUNDLES.clear()
        _BUNDLES[k] = joblib.load(p)
    return _BUNDLES[k]

@app.post("/api/datasets/<int:did>/predict")
@auth
def predict(did):
    r = own(did)
    if not r["train_json"]: return err("Train the models first.")
    bundle = load_bundle(did)
    if bundle is None or "train_formulas" not in bundle: return err("The saved model is from an older version - please click 'Re-train & re-screen' once.")
    b = request.get_json(silent=True) or {}; vals = b.get("values") or {}; clean = {}
    for c in bundle["features"]:
        v = vals.get(c)
        if v is None or str(v).strip() == "": continue
        try: f = float(v)
        except Exception: return err(f"'{c}' must be a number.")
        if not np.isfinite(f): return err(f"'{c}' must be a finite number.")
        clean[c] = f
    if not clean: return err("Enter at least one descriptor value.")
    eh = b.get("ehull")
    if eh is None or str(eh).strip() == "": eh = None
    else:
        try: eh = float(eh)
        except Exception: return err("Ehull must be a number.")
        if not np.isfinite(eh): return err("Ehull must be a finite number.")
    try:
        x = ml.predict_single(bundle, clean, labels(json.loads(r["analysis_json"])), str(b.get("formula") or "").strip()[:60] or None, eh)
        cmp_ = ml.compare_with_training(bundle, clean)
    except Exception as e: app.logger.exception(e); return err(f"Prediction failed: {e}", 500)
    d = x["detail"]; drv = sorted(d["shap"], key=lambda s: -abs(s["value"]))[:5]
    return jsonify({"formula": x["formula"], "pred_log": x["pred_log"], "pred_k": x["pred_k"], "dist": x["dist"], "ad": x["ad"], "ad_result": x["ad_result"],
                    "ehull": x["ehull"], "ehull_result": x["ehull_result"], "orr_result": x["orr_result"], "final": x["final"], "fails": d["fails"],
                    "not_available": d["not_available"], "thresholds": d["thresholds"], "imputed": x["imputed"], "drivers": drv, "compare": cmp_,
                    "model": {"name": "SVR", "trained_on": len(bundle.get("train_index", []))}})

@app.post("/api/datasets/<int:did>/screen")
@auth
def screen(did):
    r = own(did)
    if not r["train_json"]: return err("Train the models first.")
    do_screen(r); return jsonify({"ok": True})

LIST_COLS = "id,rank,tier,formula,predicted_log_kstar,predicted_kstar,mahalanobis_distance,applicability_domain,ad_result,ehull,ehull_result,orr_result,final_result,failure_reason"
@app.get("/api/datasets/<int:did>/results")
@auth
def results(did):
    own(did); f = request.args.get("filter", "all"); q = request.args.get("q", "").strip().lower()
    cond = {"all": "1", "pass": "final_result='PASS'", "fail": "final_result='FAIL'", "outside_ad": "applicability_domain='OUTSIDE'", "failed_orr": "orr_result='FAIL'",
            "failed_ehull": "ehull_result='FAIL'", "tier_green": "tier='green'", "tier_orange": "tier='orange'", "tier_red": "tier='red'"}.get(f, "1")
    rows = db().execute(f"SELECT {LIST_COLS} FROM screening_results WHERE dataset_id=? AND {cond} AND lower(formula) LIKE ? ORDER BY rank", (did, f"%{q}%")).fetchall()
    return jsonify([dict(x) for x in rows])

@app.get("/api/datasets/<int:did>/results/<int:rid>")
@auth
def result_one(did, rid):
    own(did); x = db().execute("SELECT * FROM screening_results WHERE id=? AND dataset_id=?", (rid, did)).fetchone()
    if not x: return err("Cathode not found.", 404)
    d = dict(x); d["detail"] = json.loads(d.pop("detail_json")); return jsonify(d)

@app.get("/api/datasets/<int:did>/export/<kind>")
@auth
def export(did, kind):
    r = own(did)
    rows = db().execute("SELECT * FROM screening_results WHERE dataset_id=? ORDER BY rank", (did,)).fetchall()
    if not rows: return err("No screening results yet - run the screening first.")
    TN = {"green": "GREEN (near passing)", "orange": "ORANGE (intermediate)", "red": "RED (far from passing)"}; recs = []
    for x in rows:
        det = json.loads(x["detail_json"])
        recs.append({"Rank": x["rank"], "Closeness tier": TN[x["tier"]], **det["original"],
            "Predicted log10(k*)": x["predicted_log_kstar"], "Predicted k* (cm/s)": x["predicted_kstar"], "Mahalanobis distance": x["mahalanobis_distance"],
            "Applicability domain": x["applicability_domain"], "Ehull (meV/atom)": x["ehull"], "Ehull result": x["ehull_result"],
            "ORR activity (pred. log10 k*)": x["orr_value"], "ORR result (LSC benchmark -6.40)": x["orr_result"], "Final result": x["final_result"], "Failure reason / note": x["failure_reason"]})
    df = pd.DataFrame(recs); fr = df["Final result"]
    db().execute("INSERT INTO export_history(dataset_id,user_id,kind,created_at) VALUES(?,?,?,?)", (did, g.uid, kind, now())); db().commit()
    stem = Path(r["filename"]).stem
    if kind == "csv": return send_file(io.BytesIO(df.to_csv(index=False).encode()), "text/csv", as_attachment=True, download_name=f"{stem}_screening_results.csv")
    nfe = ("Not Fully Evaluated", df[fr == "INCOMPLETE"])
    sheets = {"all": [("Screening Results", df), ("PASS Cathodes", df[fr == "PASS"]), ("FAIL Cathodes", df[fr == "FAIL"])] + ([nfe] if len(nfe[1]) else []),
              "pass": [("PASS Cathodes", df[fr == "PASS"])] + ([nfe] if len(nfe[1]) else []), "fail": [("FAIL Cathodes", df[fr == "FAIL"])]}.get(kind)
    if sheets is None: return err("Unknown export type.")
    from openpyxl.styles import PatternFill
    fills = {"GREEN": "C6EFCE", "ORANGE": "FFE0B2", "RED": "F8C9C9"}; buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        for name, d in sheets:
            (d if len(d) else pd.DataFrame({"note": ["No cathodes in this category."]})).to_excel(w, sheet_name=name, index=False); ws = w.sheets[name]
            for col in ws.columns: ws.column_dimensions[col[0].column_letter].width = min(40, max(10, len(str(col[0].value)) + 2))
            ws.freeze_panes = "C2"
            if len(d):
                ti = list(d.columns).index("Closeness tier") + 1
                for rr in range(2, ws.max_row + 1):
                    f = fills.get(str(ws.cell(rr, ti).value).split()[0])
                    if f:
                        for cc in range(1, ws.max_column + 1): ws.cell(rr, cc).fill = PatternFill("solid", fgColor=f)
        pd.DataFrame({"Note": ["Rows are sorted by Rank (closest to passing first). Closeness = mean normalised shortfall over the evaluated criteria (applicability domain, Ehull, ORR); GREEN <= 0.10, RED > 0.50, ORANGE in between. This ranking is an addition to, not part of, the paper's PASS/FAIL rules.",
            "PASS = inside the applicability domain, Ehull <= 57 meV/atom and predicted log10(k*) >= -6.40 (the LSC benchmark used in the research paper). The paper's cost filter is not applied.",
            "Predictions come from an SVR trained on this same dataset (in-sample); treat them as screening indicators, not validated measurements."]}).to_excel(w, sheet_name="Notes", index=False)
    buf.seek(0)
    return send_file(buf, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", as_attachment=True, download_name=f"{stem}_{kind}_cathodes.xlsx")

@app.get("/")
def index(): return app.send_static_file("index.html")

if __name__ == "__main__":
    print("Data folder:", STORE)
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False, threaded=True)