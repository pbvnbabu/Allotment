# PRC0001_secure_scoped.py  (TOP FILTER BAR VERSION)
import io
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import streamlit as st
import altair as alt

# ───────────────────────── Config ─────────────────────────
st.set_page_config(page_title="PRC 0001 — Classroom Teachers (Scoped)", layout="wide")
st.title("PRC 0001 — ADM → Teacher Positions & Funding (Scoped by LEA + Admin)")
st.caption(
    "Access via **data/access_control.csv|xlsx** (email → LEA/District + optional role=admin). "
    "MSC/IFE per-LEA overrides in **data/msc_ife_allocations.csv|xlsx**. "
    "Edits to ratios/salary/benefits are isolated to your current user + county."
)

# Hide sidebar and style a sticky top filter bar
st.markdown("""
<style>
[data-testid="stSidebar"] { display: none; }
main .block-container { padding-top: 0.5rem; max-width: 1400px; }
.filter-bar {
  position: sticky; top: 0; z-index: 999;
  background: white; padding: 0.75rem 0.75rem 0.35rem 0.75rem;
  border-bottom: 1px solid #eee;
}
</style>
""", unsafe_allow_html=True)

DATA_DIR = Path("data")

# --- Year-driven selection (upload kept but hidden) ---
YEARS_AVAILABLE = list(range(2025, 2020 - 1, -1))  # 2025..2020
DEFAULT_YEAR = 2025
SHOW_UPLOAD = False  # keep uploader code present, but hidden in UI

def find_adm_for_year(year: int) -> Path | None:
    """Prefer ADM{YEAR}.xlsx/xls in ./data. Fallback: any file with YEAR and 'adm'."""
    for ext in ("xlsx", "xls"):
        p = DATA_DIR / f"ADM{year}.{ext}"
        if p.exists():
            return p
    cands = [p for p in DATA_DIR.glob(f"*{year}*.xls*") if re.search(r"adm", p.name, re.I)]
    if cands:
        cands.sort(key=lambda p: (p.suffix.lower() != ".xlsx", len(p.name)))
        return cands[0]
    return None

# Defaults used when a new scope (user + county) is detected
DEFAULTS = {
    "ratio_k3": 18.0,
    "ratio_4_8": 24.0,
    "ratio_9": 26.5,
    "ratio_10_12": 29.0,
    "salary": 55000.0,
    "benefits": 15000.0,
}

# ───────────────────────── Utilities ─────────────────────────
def safe_rerun():
    if hasattr(st, "rerun"):
        st.rerun()
    elif hasattr(st, "experimental_rerun"):
        st.experimental_rerun()
    else:
        st.stop()

def request_reset_current_county():
    st.session_state["__do_reset__"] = True

def read_table_auto(path: Path) -> pd.DataFrame:
    """Read CSV/Excel with resilient encoding."""
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    suf = path.suffix.lower()
    if suf in {".xlsx", ".xls"}:
        df = pd.read_excel(path, dtype=str)
        return df.applymap(lambda x: x.strip() if isinstance(x, str) else x)
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin1"):
        try:
            df = pd.read_csv(path, dtype=str, sep=None, engine="python", encoding=enc)
            return df.applymap(lambda x: x.strip() if isinstance(x, str) else x)
        except UnicodeDecodeError:
            pass
    df = pd.read_csv(path, dtype=str, sep=None, engine="python", encoding="latin1", on_bad_lines="skip")
    return df.applymap(lambda x: x.strip() if isinstance(x, str) else x)

def normalize_columns(df: pd.DataFrame, mapping: dict[str, str]) -> pd.DataFrame:
    """Case/space-insensitive rename to canonical names."""
    canon = {c: c for c in df.columns}
    lower_map = {k.lower(): v for k, v in mapping.items()}
    for c in df.columns:
        key = c.strip().lower()
        if key in lower_map:
            canon[c] = lower_map[key]
    return df.rename(columns=canon)

def first_nonempty_sheet(xls: pd.ExcelFile) -> str:
    for s in xls.sheet_names:
        if "adm" in s.lower():
            return s
    return xls.sheet_names[0]

def read_adm_sheet(file) -> pd.DataFrame:
    xls = pd.ExcelFile(file)
    sheet = first_nonempty_sheet(xls)
    df = pd.read_excel(xls, sheet_name=sheet)
    cols = df.columns.tolist()
    if len(cols) >= 16:
        df = df.rename(columns={
            cols[0]: "LEA_Code",
            cols[1]: "District",
            cols[2]: "K",
            cols[3]: "G1",
            cols[4]: "G2",
            cols[5]: "G3",
            cols[6]: "G4",
            cols[7]: "G5",
            cols[8]: "G6",
            cols[9]: "G7",
            cols[10]: "G8",
            cols[11]: "G9",
            cols[12]: "G10",
            cols[13]: "G11",
            cols[14]: "G12",
            cols[15]: "TOTAL"
        })
    grade_cols = ["K","G1","G2","G3","G4","G5","G6","G7","G8","G9","G10","G11","G12"]
    present = [c for c in grade_cols if c in df.columns]
    for c in present + (["TOTAL"] if "TOTAL" in df.columns else []):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    if "LEA_Code" in df.columns:
        df["LEA_Code"] = df["LEA_Code"].astype(str).str.strip()
    if "District" in df.columns:
        df["District"] = df["District"].astype(str).str.strip()
    if "District" in df.columns:
        df = df[df["District"].notna()].copy()
    if present:
        df = df[df[present].notna().any(axis=1)].copy()
    return df

def detect_viewer_email() -> Optional[str]:
    try:
        return getattr(st.user, "email", None)  # Streamlit Cloud may populate this
    except Exception:
        return None

def build_scope_key(viewer_email: str, lea_code: Optional[str], district: Optional[str]) -> str:
    email = (viewer_email or "").strip().lower()
    lc = (lea_code or "").strip()
    d  = (district or "").strip()
    return f"{email}|LEA:{lc}|DIST:{d}"

def reset_defaults_if_scope_changed(scope_key: str):
    if st.session_state.get("__scope_key") != scope_key:
        for name, val in DEFAULTS.items():
            st.session_state[name] = val
        st.session_state["__scope_key"] = scope_key

# ───────────────────────── Row 1: Year + Email (top filter bar) ─────────────────────────
st.markdown('<div class="filter-bar">', unsafe_allow_html=True)
r1c1, r1c2 = st.columns([1, 2], vertical_alignment="center")

with r1c1:
    year = st.selectbox("ADM Year", YEARS_AVAILABLE, index=YEARS_AVAILABLE.index(DEFAULT_YEAR), key="year")

with r1c2:
    default_email = (detect_viewer_email() or st.session_state.get("__last_viewer_email","")).strip().lower()
    viewer_email = st.text_input(
        "Your email (for LEA scoping)",
        value=default_email,
        placeholder="name@lea.k12.nc.us",
        help="Used to scope data and determine admin permissions."
    ).strip().lower()

# If the email changed, reset district selection
prev_email = st.session_state.get("__last_viewer_email")
if prev_email != viewer_email:
    st.session_state.pop("sel_district", None)
    st.session_state["__last_viewer_email"] = viewer_email
st.markdown('</div>', unsafe_allow_html=True)

# ───────────────────────── Load ADM (year-driven; uploader hidden) ─────────────────────────
uploaded = None
if SHOW_UPLOAD:
    uploaded = st.file_uploader("Upload ADM workbook (e.g., ADM2025.xlsx)", type=["xlsx", "xls"])

if uploaded is not None:
    st.info("Using uploaded workbook (overrides year selection).")
    file_obj = uploaded
else:
    sel_path = find_adm_for_year(year)
    if sel_path is None:
        available = sorted([p.name for p in DATA_DIR.glob("*.xls*")])
        st.error(
            f"No ADM workbook found for **{year}** in `data/`.\n\n"
            f"Expected **ADM{year}.xlsx** or **ADM{year}.xls**.\n\n"
            f"Found files:\n- " + ("\n- ".join(available) if available else "(none)")
        )
        st.stop()
    st.info(f"Using **{sel_path.name}** for year **{year}**.")
    file_obj = sel_path.open("rb")

df_all = read_adm_sheet(file_obj)
if df_all.empty or "District" not in df_all.columns:
    st.error("Could not parse the expected columns from the ADM workbook.")
    st.stop()

# ───────────────────────── Access control & role ─────────────────────────
ACCESS_FILE = (DATA_DIR / "access_control.xlsx") if (DATA_DIR / "access_control.xlsx").exists() else (DATA_DIR / "access_control.csv")
if not ACCESS_FILE.exists():
    st.error("Access file missing: **data/access_control.csv|xlsx**. Needs `email` + (`LEA_Code` or `District`), optional `role`.")
    st.stop()

acc_raw = read_table_auto(ACCESS_FILE)
acc = normalize_columns(
    acc_raw,
    mapping={"email":"email", "lea_code":"LEA_Code", "district":"District", "role":"role"}
)

if not viewer_email:
    st.warning("Enter your email to view your LEA data.")
    st.stop()

acc["email"] = acc["email"].astype(str).str.strip().str.lower()
if "email" not in acc.columns or (("LEA_Code" not in acc.columns) and ("District" not in acc.columns)):
    st.error("`access_control` must include `email` and either `LEA_Code` or `District`. Optional `role` for admin.")
    st.stop()
if viewer_email not in set(acc["email"].tolist()):
    st.error("Your email is not on the access list. Ask an admin to add it to **data/access_control.csv|xlsx**.")
    st.stop()

user_rows = acc[acc["email"] == viewer_email].copy()
user_roles = set(user_rows.get("role", pd.Series(dtype=str)).astype(str).str.lower().str.strip())

# ---- ADMIN detection (strict) ----
ADMIN_EMAILS = {
    "Testjohndoe@gmail.com",  # adjust as needed
}
role_is_admin = "admin" in user_roles
is_admin = (viewer_email in ADMIN_EMAILS) or role_is_admin

allowed_lea_codes = set(user_rows.get("LEA_Code", pd.Series(dtype=str)).dropna().astype(str).str.strip())
allowed_districts = set(user_rows.get("District", pd.Series(dtype=str)).dropna().astype(str).str.strip())

# ───────────────────────── Row 1b: Scope (admins only) ─────────────────────────
st.markdown('<div class="filter-bar">', unsafe_allow_html=True)
if is_admin:
    sc1, sc2 = st.columns([1.2, 3])
    with sc1:
        st.success("ADMIN")
    with sc2:
        scope_mode = st.radio("Scope", ["All LEAs", "Only my LEA(s)"], index=0, horizontal=True, key="scope_mode")
else:
    scope_mode = "Only my LEA(s)"
    st.info("Scope: Only my LEA(s)")
st.markdown('</div>', unsafe_allow_html=True)

# ───────────────────────── Apply scope ─────────────────────────
if scope_mode == "All LEAs" and is_admin:
    df_scope = df_all.copy()
else:
    df_scope = df_all.copy()
    if allowed_lea_codes:
        df_scope = df_scope[df_scope["LEA_Code"].astype(str).isin(allowed_lea_codes)]
    if allowed_districts:
        df_scope = df_scope[df_scope["District"].astype(str).isin(allowed_districts)]
    if df_scope.empty:
        st.error("No rows match your LEA access.")
        st.stop()

# Determine selected district & keep selection valid
districts = df_scope["District"].astype(str).tolist()
if not districts:
    st.error("No rows match your LEA access.")
    st.stop()
if st.session_state.get("sel_district") not in districts:
    st.session_state["sel_district"] = districts[0]
selected_district = st.session_state["sel_district"]

# Resolve selected LEA code for scope key
try:
    selected_lea_code = (
        df_scope.loc[df_scope["District"] == selected_district, "LEA_Code"].astype(str).iloc[0]
        if "LEA_Code" in df_scope.columns else None
    )
except Exception:
    selected_lea_code = None

# Build scope key (user + county) and reset defaults if changed
scope_key = build_scope_key(viewer_email, selected_lea_code, selected_district)
reset_defaults_if_scope_changed(scope_key)

# Handle "Reset to defaults (this county only)" BEFORE rendering widgets
if st.session_state.get("__do_reset__"):
    for k, v in DEFAULTS.items():
        st.session_state[k] = v
    st.session_state["__do_reset__"] = False
    safe_rerun()

# ───────────────────────── Row 2: Ratios ─────────────────────────
st.markdown('<div class="filter-bar">', unsafe_allow_html=True)
c2a, c2b, c2c, c2d = st.columns(4)
with c2a:
    ratio_k3 = st.number_input("K–3 ratio", min_value=1.0, step=0.5,
                               key="ratio_k3", value=st.session_state.get("ratio_k3", DEFAULTS["ratio_k3"]))
with c2b:
    ratio_4_8 = st.number_input("4–8 ratio", min_value=1.0, step=0.5,
                                key="ratio_4_8", value=st.session_state.get("ratio_4_8", DEFAULTS["ratio_4_8"]))
with c2c:
    ratio_9 = st.number_input("9 ratio", min_value=1.0, step=0.5,
                              key="ratio_9", value=st.session_state.get("ratio_9", DEFAULTS["ratio_9"]))
with c2d:
    ratio_10_12 = st.number_input("10–12 ratio", min_value=1.0, step=0.5,
                                  key="ratio_10_12", value=st.session_state.get("ratio_10_12", DEFAULTS["ratio_10_12"]))
st.markdown('</div>', unsafe_allow_html=True)

# ───────────────────────── Row 3: Compensation ─────────────────────────
st.markdown('<div class="filter-bar">', unsafe_allow_html=True)
c3a, c3b, c3c = st.columns([1,1,1])
with c3a:
    salary = st.number_input("Average Salary ($)", min_value=0.0, step=1000.0, format="%.2f",
                             key="salary", value=st.session_state.get("salary", DEFAULTS["salary"]))
with c3b:
    benefits = st.number_input("Average Benefits ($)", min_value=0.0, step=1000.0, format="%.2f",
                               key="benefits", value=st.session_state.get("benefits", DEFAULTS["benefits"]))
with c3c:
    comp_per_teacher_sel = salary + benefits
    st.metric("Comp / Teacher", f"${comp_per_teacher_sel:,.2f}")
st.markdown('</div>', unsafe_allow_html=True)

# ───────────────────────── Row 4: MSC/IFE rates + Reset ─────────────────────────
st.markdown('<div class="filter-bar">', unsafe_allow_html=True)
c4a, c4b, c4c = st.columns([1,1,1])
with c4a:
    msc_rate = st.number_input("MSC Rate ($)", value=70000.0, min_value=0.0, step=1000.0, format="%.2f")
with c4b:
    ife_rate = st.number_input("IFE Rate ($)", value=78421.0, min_value=0.0, step=1000.0, format="%.2f")
with c4c:
    st.button("↩︎ Reset to defaults (this county only)",
              key="reset2_button_county_only",
              on_click=request_reset_current_county,
              use_container_width=True)
st.markdown('</div>', unsafe_allow_html=True)

# ───────────────────────── Compute positions (row-wise params) ─────────────────────────
df_scope = df_scope.copy()
df_scope["ratio_k3_used"]    = DEFAULTS["ratio_k3"]
df_scope["ratio_4_8_used"]   = DEFAULTS["ratio_4_8"]
df_scope["ratio_9_used"]     = DEFAULTS["ratio_9"]
df_scope["ratio_10_12_used"] = DEFAULTS["ratio_10_12"]
df_scope["comp_used"]        = DEFAULTS["salary"] + DEFAULTS["benefits"]

mask_selected = df_scope["District"].astype(str).eq(selected_district)
df_scope.loc[mask_selected, "ratio_k3_used"]    = ratio_k3
df_scope.loc[mask_selected, "ratio_4_8_used"]   = ratio_4_8
df_scope.loc[mask_selected, "ratio_9_used"]     = ratio_9
df_scope.loc[mask_selected, "ratio_10_12_used"] = ratio_10_12
df_scope.loc[mask_selected, "comp_used"]        = comp_per_teacher_sel

# Aggregate ADMs
df_scope["ADM_K_3"]   = df_scope[["K","G1","G2","G3"]].sum(axis=1, min_count=1)
df_scope["ADM_4_8"]   = df_scope[["G4","G5","G6","G7","G8"]].sum(axis=1, min_count=1)
df_scope["ADM_9"]     = df_scope["G9"]
df_scope["ADM_10_12"] = df_scope[["G10","G11","G12"]].sum(axis=1, min_count=1)

# Positions (per-row ratios)
df_scope["Pos_K_3"]    = df_scope["ADM_K_3"]   / df_scope["ratio_k3_used"]
df_scope["Pos_4_8"]    = df_scope["ADM_4_8"]   / df_scope["ratio_4_8_used"]
df_scope["Pos_9"]      = df_scope["ADM_9"]     / df_scope["ratio_9_used"]
df_scope["Pos_10_12"]  = df_scope["ADM_10_12"] / df_scope["ratio_10_12_used"]
df_scope["Total_Positions"] = df_scope[["Pos_K_3","Pos_4_8","Pos_9","Pos_10_12"]].sum(axis=1)

# Funding
df_scope["Total_Funding"] = df_scope["Total_Positions"] * df_scope["comp_used"]
df_scope["Fund_K_3"]    = df_scope["Pos_K_3"]    * df_scope["comp_used"]
df_scope["Fund_4_8"]    = df_scope["Pos_4_8"]    * df_scope["comp_used"]
df_scope["Fund_9"]      = df_scope["Pos_9"]      * df_scope["comp_used"]
df_scope["Fund_10_12"]  = df_scope["Pos_10_12"]  * df_scope["comp_used"]

# ───────────────────────── Load MSC/IFE and merge ─────────────────────────
ALLOC_XLSX = DATA_DIR / "msc_ife_allocations.xlsx"
ALLOC_CSV  = DATA_DIR / "msc_ife_allocations.csv"
ALLOC_FILE = ALLOC_XLSX if ALLOC_XLSX.exists() else (ALLOC_CSV if ALLOC_CSV.exists() else None)

existing_alloc = None
if ALLOC_FILE:
    raw = read_table_auto(ALLOC_FILE)
    existing_alloc = normalize_columns(
        raw, {"lea_code":"LEA_Code","district":"District","msc_count":"MSC_Count","ife_count":"IFE_Count"}
    )
    for k in ("LEA_Code", "District"):
        if k in existing_alloc.columns:
            existing_alloc[k] = existing_alloc[k].astype(str).str.strip()
    for c in ("MSC_Count", "IFE_Count"):
        if c in existing_alloc.columns:
            existing_alloc[c] = pd.to_numeric(existing_alloc[c], errors="coerce")

# default zeros before merge
df_scope["MSC_Count"] = 0.0
df_scope["IFE_Count"] = 0.0

matched_rows = 0
if existing_alloc is not None and not existing_alloc.empty:
    if "LEA_Code" in existing_alloc.columns and "LEA_Code" in df_scope.columns:
        df_scope["LEA_Code"] = df_scope["LEA_Code"].astype(str).str.strip()
        df_scope = df_scope.merge(
            existing_alloc[["LEA_Code","MSC_Count","IFE_Count"]],
            on="LEA_Code", how="left", suffixes=("","_old")
        )
        matched_rows = df_scope["MSC_Count_old"].notna().sum() if "MSC_Count_old" in df_scope.columns else 0
    elif "District" in existing_alloc.columns and "District" in df_scope.columns:
        df_scope["District"] = df_scope["District"].astype(str).str.strip()
        df_scope = df_scope.merge(
            existing_alloc[["District","MSC_Count","IFE_Count"]],
            on="District", how="left", suffixes=("","_old")
        )
        matched_rows = df_scope["MSC_Count_old"].notna().sum() if "MSC_Count_old" in df_scope.columns else 0
else:
    st.info("No MSC/IFE allocation file found (data/msc_ife_allocations.csv|xlsx). All MSC/IFE default to 0.")

# Coalesce from *_old into main columns
for c in ("MSC_Count", "IFE_Count"):
    old = f"{c}_old"
    if old in df_scope.columns:
        df_scope[c] = np.where(df_scope[old].notna(), df_scope[old], df_scope[c])
        df_scope.drop(columns=[old], inplace=True)

# Ensure numeric after coalescing
df_scope["MSC_Count"] = pd.to_numeric(df_scope["MSC_Count"], errors="coerce").fillna(0.0)
df_scope["IFE_Count"] = pd.to_numeric(df_scope["IFE_Count"], errors="coerce").fillna(0.0)

# Apply rates captured in top bar
df_scope["MSC_Rate"] = msc_rate
df_scope["IFE_Rate"] = ife_rate
df_scope["MSC_Funding"] = df_scope["MSC_Count"] * df_scope["MSC_Rate"]
df_scope["IFE_Funding"] = df_scope["IFE_Count"] * df_scope["IFE_Rate"]
df_scope["Grand_Total_Funding"] = df_scope["Total_Funding"] + df_scope["MSC_Funding"] + df_scope["IFE_Funding"]

st.caption(f"MSC/IFE allocations matched for **{matched_rows}** row(s).")

# ───────────────────────── Persist helper (define BEFORE use) ─────────────────────────
def persist_allocations(edited_df: pd.DataFrame, existing_path: Optional[Path]) -> tuple[Path, Optional[Path], int]:
    key = "LEA_Code" if "LEA_Code" in edited_df.columns else "District"
    changes = (
        edited_df[[key, "MSC_Count", "IFE_Count"]]
        .copy()
        .dropna(subset=[key])
    )

    if existing_path and existing_path.exists():
        existing = read_table_auto(existing_path)
        existing = normalize_columns(existing, {
            "lea_code":"LEA_Code","district":"District","msc_count":"MSC_Count","ife_count":"IFE_Count"
        })
        merged = existing.merge(changes, on=key, how="outer", suffixes=("_old",""))
        for c in ("MSC_Count","IFE_Count"):
            if f"{c}_old" in merged.columns:
                merged[c] = np.where(merged[c].notna(), merged[c], merged[f"{c}_old"])
                merged.drop(columns=[f"{c}_old"], inplace=True)
        out = merged[[key,"MSC_Count","IFE_Count"]].copy()
    else:
        out = changes.copy()

    for c in ("MSC_Count","IFE_Count"):
        out[c] = pd.to_numeric(out[c], errors="coerce").fillna(0.0)
    out = out.drop_duplicates(subset=[key]).sort_values(key)

    target = existing_path if (existing_path is not None) else (DATA_DIR / "msc_ife_allocations.csv")

    backup = None
    if target.exists():
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = target.with_suffix(target.suffix + f".bak-{ts}")
        target.replace(backup)

    if target.suffix.lower() in {".xlsx",".xls"}:
        with pd.ExcelWriter(target, engine="openpyxl") as w:
            out.to_excel(w, index=False, sheet_name="MSC_IFE")
    else:
        out.to_csv(target, index=False, encoding="utf-8")

    return target, backup, len(out)

# ───────────────────────── MSC/IFE editor & persist ─────────────────────────
st.subheader("Per-LEA MSC/IFE Overrides")
st.caption("Admins can edit & save permanently. Others can edit for this session only.")

edit_cols = [c for c in ["LEA_Code","District","MSC_Count","IFE_Count"] if c in df_scope.columns]
edited = st.data_editor(
    df_scope[edit_cols].copy(),
    num_rows="fixed",
    use_container_width=True,
    key="editor_counts"
)

# Re-merge edited values back in, then recompute funding
join_keys = [c for c in ["LEA_Code","District"] if c in df_scope.columns]
df_scope = df_scope.drop(columns=["MSC_Count","IFE_Count"]).merge(
    edited[[*join_keys,"MSC_Count","IFE_Count"]],
    on=join_keys, how="left"
)
df_scope["MSC_Count"] = pd.to_numeric(df_scope["MSC_Count"], errors="coerce").fillna(0.0)
df_scope["IFE_Count"] = pd.to_numeric(df_scope["IFE_Count"], errors="coerce").fillna(0.0)
df_scope["MSC_Funding"] = df_scope["MSC_Count"] * df_scope["MSC_Rate"]
df_scope["IFE_Funding"] = df_scope["IFE_Count"] * df_scope["IFE_Rate"]
df_scope["Grand_Total_Funding"] = df_scope["Total_Funding"] + df_scope["MSC_Funding"] + df_scope["IFE_Funding"]

if is_admin:
    left, right = st.columns([1,2])
    with left:
        if st.button("💾 Save MSC/IFE to data/msc_ife_allocations.*", type="primary", use_container_width=True):
            try:
                write_path, backup_path, n = persist_allocations(edited, ALLOC_FILE)
                if backup_path:
                    st.success(f"Saved {n} rows to **{write_path.as_posix()}** (backup: {backup_path.name}).")
                else:
                    st.success(f"Saved {n} rows to **{write_path.as_posix()}**.")
            except Exception as e:
                st.error(f"Save failed: {e}")
    with right:
        st.info("Tip: in admin mode you can scope to **All LEAs**, edit many rows, then save.")

# ───────────────────────── District Summary (robust) ─────────────────────────
st.subheader("District Summary")
st.caption("Select the district. Top-bar parameters apply **only** to this district for your current session.")

current = st.session_state["sel_district"]
idx = next((i for i, d in enumerate(districts) if d == current), 0)

pick = st.selectbox(
    "Choose a district",
    options=districts,
    index=idx,
    key="sel_district",
)
if pick != selected_district and hasattr(st, "rerun"):
    st.rerun()

row = df_scope[df_scope["District"] == st.session_state["sel_district"]].iloc[0]

kpi_cols = st.columns(5)
kpi_cols[0].metric("K–3 ADM", f"{int(row['ADM_K_3'])}")
kpi_cols[1].metric("4–8 ADM", f"{int(row['ADM_4_8'])}")
kpi_cols[2].metric("9 ADM", f"{int(row['ADM_9'])}")
kpi_cols[3].metric("10–12 ADM", f"{int(row['ADM_10_12'])}")
kpi_cols[4].metric("Total Positions", f"{row['Total_Positions']:.2f}")

kpi2 = st.columns(4)
kpi2[0].metric("Comp/Teacher (used)", f"${row['comp_used']:,.2f}")
kpi2[1].metric("Base Funding", f"${row['Total_Funding']:,.2f}")
kpi2[2].metric("MSC + IFE", f"${(row['MSC_Funding'] + row['IFE_Funding']):,.2f}")
kpi2[3].metric("Grand Total", f"${row['Grand_Total_Funding']:,.2f}")

# ───────────────────────── Charts ─────────────────────────
st.subheader("Charts")
grade_df = pd.DataFrame({
    "Grade": ["K–3", "4–8", "9", "10–12"],
    "ADM": [row["ADM_K_3"], row["ADM_4_8"], row["ADM_9"], row["ADM_10_12"]],
    "Positions": [row["Pos_K_3"], row["Pos_4_8"], row["Pos_9"], row["Pos_10_12"]],
    "Funding": [row["Fund_K_3"], row["Fund_4_8"], row["Fund_9"], row["Fund_10_12"]],
})

c1, c2 = st.columns(2)
with c1:
    st.caption(f"ADM by Grade — {row['District']}")
    st.altair_chart(
        alt.Chart(grade_df).mark_bar().encode(
            x=alt.X("Grade:N", title="Grade"),
            y=alt.Y("ADM:Q", title="ADM"),
            tooltip=["Grade", alt.Tooltip("ADM:Q", format=",.0f")]
        ).properties(height=280),
        use_container_width=True
    )
with c2:
    st.caption(f"Positions by Grade — {row['District']}")
    st.altair_chart(
        alt.Chart(grade_df).mark_bar().encode(
            x=alt.X("Grade:N", title="Grade"),
            y=alt.Y("Positions:Q", title="Teacher Positions"),
            tooltip=["Grade", alt.Tooltip("Positions:Q", format=",.2f")]
        ).properties(height=280),
        use_container_width=True
    )

st.caption(f"Funding Share by Grade — {row['District']}")
fund_df = grade_df.copy()
fund_df["pct"] = fund_df["Funding"] / max(float(row["Fund_K_3"] + row["Fund_4_8"] + row["Fund_9"] + row["Fund_10_12"]), 1e-9)
st.altair_chart(
    alt.Chart(fund_df).mark_arc(innerRadius=60).encode(
        theta=alt.Theta("Funding:Q"),
        color=alt.Color("Grade:N"),
        tooltip=[
            "Grade",
            alt.Tooltip("Funding:Q", title="Funding", format="$,.0f"),
            alt.Tooltip("pct:Q", title="Share", format=".1%")
        ]
    ).properties(height=300),
    use_container_width=True
)

# ───────────────────────── Table & download ─────────────────────────
with st.expander("Show computed columns table (scoped)"):
    base_cols = ["LEA_Code","District","K","G1","G2","G3","G4","G5","G6","G7","G8","G9","G10","G11","G12","TOTAL",
                 "ratio_k3_used","ratio_4_8_used","ratio_9_used","ratio_10_12_used","comp_used",
                 "ADM_K_3","ADM_4_8","ADM_9","ADM_10_12",
                 "Pos_K_3","Pos_4_8","Pos_9","Pos_10_12","Total_Positions",
                 "Total_Funding",
                 "Fund_K_3","Fund_4_8","Fund_9","Fund_10_12",
                 "MSC_Count","MSC_Rate","MSC_Funding",
                 "IFE_Count","IFE_Rate","IFE_Funding",
                 "Grand_Total_Funding"]
    show_cols = [c for c in base_cols if c in df_scope.columns]
    st.dataframe(df_scope[show_cols], use_container_width=True, height=420)

def to_excel_bytes(df_out: pd.DataFrame) -> bytes:
    with io.BytesIO() as buffer:
        with pd.ExcelWriter(buffer, engine="openpyxl") as w:
            df_out.to_excel(w, index=False, sheet_name="PRC0001_Results")
        return buffer.getvalue()

st.download_button(
    label="⬇️ Download results as Excel (scoped)",
    data=to_excel_bytes(df_scope),
    file_name="PRC0001_positions_funding_results.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)

st.success("Ready. Your parameter changes are isolated to your user + selected county.")
