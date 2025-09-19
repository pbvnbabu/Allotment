# PRC0001_secure_lea_admin.py
import io
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import streamlit as st
import altair as alt

# ───────────────────────── Page ─────────────────────────
st.set_page_config(page_title="PRC 0001 — Classroom Teachers (LEA-scoped + Admin)", layout="wide")
st.title("PRC 0001 — ADM → Teacher Positions & Funding (LEA-scoped + Admin)")
st.caption(
    "Access is restricted via **data/access_control.csv|xlsx** (email → LEA/District + optional role=admin). "
    "MSC/IFE per-LEA overrides come from **data/msc_ife_allocations.csv|xlsx**; admins can persist edits."
)

DATA_DIR = Path("data")

# ───────────────────────── Robust file readers ─────────────────────────
def read_table_auto(path: Path) -> pd.DataFrame:
    """Read CSV or Excel with resilient encoding handling."""
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    suf = path.suffix.lower()
    if suf in {".xlsx", ".xls"}:
        df = pd.read_excel(path, dtype=str)
        return df.applymap(lambda x: x.strip() if isinstance(x, str) else x)
    last_err = None
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin1"):
        try:
            df = pd.read_csv(path, dtype=str, sep=None, engine="python", encoding=enc)
            return df.applymap(lambda x: x.strip() if isinstance(x, str) else x)
        except UnicodeDecodeError as e:
            last_err = e
    # Fallback
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

# ───────────────────────── ADM input helpers ─────────────────────────
def pick_default_adm_file() -> Optional[Path]:
    """Pick best ADM workbook from ./data by year in filename or latest modified."""
    if not DATA_DIR.exists():
        return None
    candidates = list(DATA_DIR.glob("ADM*.xls*"))
    if not candidates:
        candidates = [p for p in DATA_DIR.glob("*.xls*") if re.search(r"adm", p.name, re.I)]
    if not candidates:
        return None
    def score(p: Path):
        m = re.search(r"(20\d{2})", p.stem)
        yr = int(m.group(1)) if m else 0
        return (yr, p.stat().st_mtime)
    return max(candidates, key=score)

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
    present_cols = [c for c in grade_cols if c in df.columns]
    for c in present_cols + (["TOTAL"] if "TOTAL" in df.columns else []):
        df[c] = pd.to_numeric(df[c], errors="coerce")

    if "LEA_Code" in df.columns:
        df["LEA_Code"] = df["LEA_Code"].astype(str).str.strip()
    if "District" in df.columns:
        df["District"] = df["District"].astype(str).str.strip()

    if "District" in df.columns:
        df = df[df["District"].notna()].copy()
    if present_cols:
        df = df[df[present_cols].notna().any(axis=1)].copy()
    return df

def detect_viewer_email() -> Optional[str]:
    try:
        return getattr(st.experimental_user, "email", None)  # Streamlit Cloud may provide it
    except Exception:
        return None

# ───────────────────────── Core computations ─────────────────────────
def compute_positions(df: pd.DataFrame,
                      ratio_k3: float,
                      ratio_4_8: float,
                      ratio_9: float,
                      ratio_10_12: float,
                      comp_per_teacher: float) -> pd.DataFrame:
    df["ADM_K_3"]    = df[["K","G1","G2","G3"]].sum(axis=1, min_count=1)
    df["ADM_4_8"]    = df[["G4","G5","G6","G7","G8"]].sum(axis=1, min_count=1)
    df["ADM_9"]      = df["G9"]
    df["ADM_10_12"]  = df[["G10","G11","G12"]].sum(axis=1, min_count=1)

    df["Pos_K_3"]    = df["ADM_K_3"]   / ratio_k3
    df["Pos_4_8"]    = df["ADM_4_8"]   / ratio_4_8
    df["Pos_9"]      = df["ADM_9"]     / ratio_9
    df["Pos_10_12"]  = df["ADM_10_12"] / ratio_10_12

    df["Total_Positions"]   = df[["Pos_K_3","Pos_4_8","Pos_9","Pos_10_12"]].sum(axis=1)
    df["Comp_Per_Teacher"]  = comp_per_teacher
    df["Total_Funding"]     = df["Total_Positions"] * df["Comp_Per_Teacher"]

    # for charts
    df["Fund_K_3"]    = df["Pos_K_3"]    * df["Comp_Per_Teacher"]
    df["Fund_4_8"]    = df["Pos_4_8"]    * df["Comp_Per_Teacher"]
    df["Fund_9"]      = df["Pos_9"]      * df["Comp_Per_Teacher"]
    df["Fund_10_12"]  = df["Pos_10_12"]  * df["Comp_Per_Teacher"]
    return df

# ───────────────────────── Sidebar ─────────────────────────
with st.sidebar:
    st.header("Assumptions & Parameters")
    ratio_k3 = st.number_input("K–3 ratio (students per teacher)", value=18.0, min_value=1.0, step=0.5)
    ratio_4_8 = st.number_input("4–8 ratio", value=24.0, min_value=1.0, step=0.5)
    ratio_9 = st.number_input("9 ratio", value=26.5, min_value=1.0, step=0.5)
    ratio_10_12 = st.number_input("10–12 ratio", value=29.0, min_value=1.0, step=0.5)
    st.divider()
    salary = st.number_input("Average Salary ($)", value=55000.0, min_value=0.0, step=1000.0, format="%.2f")
    benefits = st.number_input("Average Benefits ($)", value=15000.0, min_value=0.0, step=1000.0, format="%.2f")
    comp_per_teacher = salary + benefits
    st.metric("Total Compensation / Teacher", f"${comp_per_teacher:,.2f}")
    st.divider()
    msc_rate = st.number_input("MSC Rate ($)", value=70000.0, min_value=0.0, step=1000.0, format="%.2f")
    ife_rate = st.number_input("IFE Rate ($)", value=78421.0, min_value=0.0, step=1000.0, format="%.2f")

# ───────────────────────── ADM input ─────────────────────────
uploaded = st.file_uploader("Upload Excel (e.g., ADM2025.xlsx)", type=["xlsx", "xls"])
DEFAULT_FILE = pick_default_adm_file()
file_obj = uploaded
if file_obj is None and DEFAULT_FILE is not None:
    st.info(f"No file uploaded — using bundled default: **{DEFAULT_FILE.as_posix()}**")
    file_obj = DEFAULT_FILE.open("rb")
if file_obj is None:
    st.info("Upload your ADM workbook or place one in **data/** (e.g., ADM2025.xlsx).")
    st.stop()

df_all = read_adm_sheet(file_obj)
if df_all.empty or "District" not in df_all.columns:
    st.error("Could not parse the expected columns from the ADM workbook.")
    st.stop()

# ───────────────────────── Access control + roles ─────────────────────────
ACCESS_FILE = (DATA_DIR / "access_control.xlsx") if (DATA_DIR / "access_control.xlsx").exists() else (DATA_DIR / "access_control.csv")
if not ACCESS_FILE.exists():
    st.error("Access file missing: **data/access_control.csv|xlsx**. Needs `email` + (`LEA_Code` or `District`), optional `role`.")
    st.stop()

acc_raw = read_table_auto(ACCESS_FILE)
acc = normalize_columns(
    acc_raw,
    mapping={"email": "email", "lea_code": "LEA_Code", "district": "District", "role": "role"}
)

# validate
if "email" not in acc.columns or (("LEA_Code" not in acc.columns) and ("District" not in acc.columns)):
    st.error("`access_control` must include `email` and either `LEA_Code` or `District`. Optional `role` for admin.")
    st.stop()

# determine viewer & role
with st.sidebar:
    default_email = (detect_viewer_email() or "").strip().lower()
    viewer_email = st.text_input(
        "Your email (for LEA scoping)",
        value=default_email,
        placeholder="name@lea.k12.nc.us",
        help="Used to scope data and determine admin permissions."
    ).strip().lower()

if not viewer_email:
    st.warning("Enter your email to view your LEA data.")
    st.stop()

acc["email"] = acc["email"].astype(str).str.strip().str.lower()
if viewer_email not in set(acc["email"].tolist()):
    st.error("Your email is not on the access list. Add it to **data/access_control.csv|xlsx**.")
    st.stop()

user_rows = acc[acc["email"] == viewer_email].copy()
user_roles = set(user_rows.get("role", pd.Series(dtype=str)).astype(str).str.lower().str.strip())
is_admin = any(r in {"admin", "owner", "editor", "super", "administrator"} for r in user_roles)

allowed_lea_codes = set(user_rows["LEA_Code"].dropna().astype(str).str.strip()) if "LEA_Code" in user_rows.columns else set()
allowed_districts = set(user_rows["District"].dropna().astype(str).str.strip()) if "District" in user_rows.columns else set()

# scope selector for admins
if is_admin:
    st.sidebar.success("You are signed in as **ADMIN**.")
    scope = st.sidebar.radio("Scope", ["All LEAs", "Only my LEA(s)"], index=0)
else:
    scope = "Only my LEA(s)"

# apply scope
if scope == "All LEAs" and is_admin:
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

# ───────────────────────── Compute base ─────────────────────────
df_scope = compute_positions(df_scope, ratio_k3, ratio_4_8, ratio_9, ratio_10_12, comp_per_teacher)

# ───────────────────────── Load allocations & merge ─────────────────────────
ALLOC_XLSX = DATA_DIR / "msc_ife_allocations.xlsx"
ALLOC_CSV  = DATA_DIR / "msc_ife_allocations.csv"
ALLOC_FILE = ALLOC_XLSX if ALLOC_XLSX.exists() else (ALLOC_CSV if ALLOC_CSV.exists() else None)

existing_alloc = None
if ALLOC_FILE:
    raw = read_table_auto(ALLOC_FILE)
    existing_alloc = normalize_columns(
        raw,
        mapping={"lea_code":"LEA_Code","district":"District","msc_count":"MSC_Count","ife_count":"IFE_Count"}
    )
    for c in ("MSC_Count", "IFE_Count"):
        if c in existing_alloc.columns:
            existing_alloc[c] = pd.to_numeric(existing_alloc[c], errors="coerce")

# default counts before merge
df_scope["MSC_Count"] = 0.0
df_scope["IFE_Count"] = 0.0

# prefer merge on LEA_Code else District
if existing_alloc is not None:
    if "LEA_Code" in existing_alloc.columns and "LEA_Code" in df_scope.columns:
        df_scope = df_scope.merge(existing_alloc[["LEA_Code","MSC_Count","IFE_Count"]], on="LEA_Code", how="left", suffixes=("","_old"))
    elif "District" in existing_alloc.columns and "District" in df_scope.columns:
        df_scope = df_scope.merge(existing_alloc[["District","MSC_Count","IFE_Count"]], on="District", how="left", suffixes=("","_old"))

# fill numeric
df_scope["MSC_Count"] = pd.to_numeric(df_scope["MSC_Count"], errors="coerce").fillna(0.0)
df_scope["IFE_Count"] = pd.to_numeric(df_scope["IFE_Count"], errors="coerce").fillna(0.0)

# funding with add-ons
df_scope["MSC_Rate"] = msc_rate
df_scope["IFE_Rate"] = ife_rate
df_scope["MSC_Funding"] = df_scope["MSC_Count"] * df_scope["MSC_Rate"]
df_scope["IFE_Funding"] = df_scope["IFE_Count"] * df_scope["IFE_Rate"]
df_scope["Grand_Total_Funding"] = df_scope["Total_Funding"] + df_scope["MSC_Funding"] + df_scope["IFE_Funding"]

# ───────────────────────── Editor ─────────────────────────
st.subheader("Per-LEA MSC/IFE Overrides")
st.caption(("Admins can **edit & save** across all LEAs." if is_admin else
           "You can edit your LEA values for this session. Only admins can persist changes."))

edit_cols = [c for c in ["LEA_Code","District","MSC_Count","IFE_Count"] if c in df_scope.columns]
edited = st.data_editor(
    df_scope[edit_cols].copy(),
    num_rows="fixed",
    use_container_width=True,
    key="editor_counts"
)

# apply edited counts in-session
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

# ───────────────────────── Admin save ─────────────────────────
def persist_allocations(edited_df: pd.DataFrame, existing_path: Optional[Path]) -> tuple[Path, Optional[Path], int]:
    """
    Merge edited rows into existing allocations file (by LEA_Code or District).
    Returns (write_path, backup_path, rows_written)
    """
    # Determine key to use
    key = "LEA_Code" if "LEA_Code" in edited_df.columns else "District"

    # Build 'changes' (dedupe by key)
    changes = (
        edited_df[[key, "MSC_Count", "IFE_Count"]]
        .copy()
        .dropna(subset=[key])
    )
    # If an existing file exists, merge/update; else create fresh
    if existing_path and existing_path.exists():
        existing = read_table_auto(existing_path)
        existing = normalize_columns(existing, {"lea_code":"LEA_Code","district":"District",
                                               "msc_count":"MSC_Count","ife_count":"IFE_Count"})
        if key not in existing.columns:
            # Convert base if other key exists
            other_key = "District" if key == "LEA_Code" else "LEA_Code"
            if other_key in existing.columns and other_key in changes.columns:
                pass  # rare case; leaving as-is
        # outer merge then prefer 'changes' where notna
        merged = existing.merge(changes, on=key, how="outer", suffixes=("_old", ""))
        for c in ("MSC_Count", "IFE_Count"):
            if f"{c}_old" in merged.columns:
                merged[c] = np.where(merged[c].notna(), merged[c], merged[f"{c}_old"])
                merged = merged.drop(columns=[f"{c}_old"])
        out = merged[[col for col in [key, "MSC_Count", "IFE_Count"] if col in merged.columns]].copy()
    else:
        out = changes.copy()

    # Clean numeric + sort
    for c in ("MSC_Count", "IFE_Count"):
        out[c] = pd.to_numeric(out[c], errors="coerce").fillna(0.0)
    out = out.drop_duplicates(subset=[key]).sort_values(key)

    # Decide target path (.xlsx or .csv)
    if existing_path:
        target = existing_path
    else:
        # default to CSV if no prior file
        target = DATA_DIR / "msc_ife_allocations.csv"

    # Backup (if overwriting)
    backup = None
    if target.exists():
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = target.with_suffix(target.suffix + f".bak-{ts}")
        target.replace(backup)  # move to backup

    # Write new file
    if target.suffix.lower() in {".xlsx", ".xls"}:
        with pd.ExcelWriter(target, engine="openpyxl") as w:
            out.to_excel(w, index=False, sheet_name="MSC_IFE")
    else:
        out.to_csv(target, index=False, encoding="utf-8")

    return target, backup, len(out)

if is_admin:
    left, right = st.columns([1, 2])
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
        st.info("Tip: choose **Scope → All LEAs** to edit every district in one grid before saving.")
else:
    st.info("Edits are applied in this session only. Ask an admin to save persistent changes to `msc_ife_allocations`.")

# ───────────────────────── KPIs (district-level within scope) ─────────────────────────
st.subheader("District Summary")
districts = df_scope["District"].astype(str).tolist()
pick = st.selectbox("Choose a district", options=districts, index=0)
row = df_scope[df_scope["District"] == pick].iloc[0]

kpi_cols = st.columns(5)
kpi_cols[0].metric("K–3 ADM", f"{int(row['ADM_K_3'])}")
kpi_cols[1].metric("4–8 ADM", f"{int(row['ADM_4_8'])}")
kpi_cols[2].metric("9 ADM", f"{int(row['ADM_9'])}")
kpi_cols[3].metric("10–12 ADM", f"{int(row['ADM_10_12'])}")
kpi_cols[4].metric("Total Positions", f"{row['Total_Positions']:.2f}")

kpi2 = st.columns(4)
kpi2[0].metric("Comp/Teacher", f"${row['Comp_Per_Teacher']:,.2f}")
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
fund_df["pct"] = fund_df["Funding"] / max(float(row["Total_Funding"]), 1e-9)
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
                 "ADM_K_3","ADM_4_8","ADM_9","ADM_10_12",
                 "Pos_K_3","Pos_4_8","Pos_9","Pos_10_12","Total_Positions",
                 "Comp_Per_Teacher","Total_Funding",
                 "Fund_K_3","Fund_4_8","Fund_9","Fund_10_12",
                 "MSC_Count","MSC_Rate","MSC_Funding",
                 "IFE_Count","IFE_Rate","IFE_Funding",
                 "Grand_Total_Funding"]
    show_cols = [c for c in base_cols if c in df_scope.columns]
    st.dataframe(df_scope[show_cols], use_container_width=True, height=420)

def to_excel_bytes(df_out: pd.DataFrame) -> bytes:
    with io.BytesIO() as buffer:
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            df_out.to_excel(writer, index=False, sheet_name="PRC0001_Results")
        return buffer.getvalue()

st.download_button(
    label="⬇️ Download results as Excel (scoped)",
    data=to_excel_bytes(df_scope),
    file_name="PRC0001_positions_funding_results.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)

st.success(("Admin mode active. You can edit and save MSC/IFE for all LEAs." if is_admin
            else "LEA-scoped view. Ask an admin to persist MSC/IFE changes."))
