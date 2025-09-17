# PRC 027 — Teacher Assistants
# Purpose
#
# Fund Teacher Assistants (TAs) primarily for grades K–3 based on class counts derived from ADM and grade-specific allocation rules.
#
# Formula Components
# Grade Band	Class Size (students/class)	TA Allocation Rule
# K	                       21	      2 TAs per 3 classes
# Grades 1–2 (combined)    21	      1 TA per 2 classes
# Grade 3	               21	      1 TA per 3 classes
# #
#  Funding Factor: $48,030.97 per TA position


import io
import re
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

# ---------- Page ----------
st.set_page_config(page_title="PRC 027 — Teacher Assistants", layout="wide")
st.title("PRC 027 — Teacher Assistants (TA) Estimator")
st.caption(
    "Computes Teacher Assistant positions and funding from ADM. Rules: "
    "Class size = 21 students; K → 2 TAs per 3 classes; Grades 1–2 → 1 TA per 2 classes; Grade 3 → 1 TA per 3 classes."
)

# ---------- Sidebar: Parameters ----------
with st.sidebar:
    st.header("Assumptions & Parameters")
    class_size = st.number_input("Class size (students per class)", value=21.0, min_value=1.0, step=1.0)
    rounding_mode = st.radio("Class rounding", ["Ceiling (whole classes)", "Exact (allow decimals)"], index=0)
    funding_factor = st.number_input("Funding factor ($ per TA position)", value=48030.97, min_value=0.0, step=100.0, format="%.2f")
    st.divider()
    st.caption("Upload an ADM workbook or rely on a bundled default in **data/** (e.g., ADM2025.xlsx).")

# ---------- Input: upload or auto-pick default from ./data ----------
DATA_DIR = Path("data")

def pick_default_adm_file() -> Path | None:
    """
    Choose the best ADM workbook from ./data:
      1) Prefer files named like ADM2025.xlsx / ADM2024.xls (highest YEAR wins)
      2) Otherwise, any file with 'adm' in the name; pick most recently modified
    """
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

uploaded = st.file_uploader("Upload Excel (e.g., ADM2025.xlsx)", type=["xlsx", "xls"])
DEFAULT_FILE = pick_default_adm_file()

file_obj = uploaded
if file_obj is None and DEFAULT_FILE is not None:
    st.info(f"No file uploaded — using bundled default: **{DEFAULT_FILE.as_posix()}**")
    file_obj = DEFAULT_FILE.open("rb")

if file_obj is None:
    st.info("Upload your ADM workbook or place one in **data/** (e.g., ADM2025.xlsx).")
    st.stop()

# ---------- Helpers to read ADM ----------
def first_nonempty_sheet(xls: pd.ExcelFile) -> str:
    for s in xls.sheet_names:
        if "adm" in s.lower():
            return s
    return xls.sheet_names[0]

def read_adm_sheet(file) -> pd.DataFrame:
    xls = pd.ExcelFile(file)
    sheet = first_nonempty_sheet(xls)
    df = pd.read_excel(xls, sheet_name=sheet)

    # Expect: [code, district, K, 1, 2, 3, ...]
    cols = df.columns.tolist()
    if len(cols) >= 6:
        df = df.rename(columns={
            cols[0]: "LEA_Code",
            cols[1]: "District",
            cols[2]: "K",
            cols[3]: "G1",
            cols[4]: "G2",
            cols[5]: "G3",
        })
    # coerce numeric
    for c in ["K", "G1", "G2", "G3"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    # keep valid rows
    if "District" in df.columns:
        df = df[df["District"].notna()].copy()
    grade_cols = [c for c in ["K", "G1", "G2", "G3"] if c in df.columns]
    if grade_cols:
        df = df[df[grade_cols].notna().any(axis=1)].copy()
    return df

df = read_adm_sheet(file_obj)
if df.empty or "District" not in df.columns:
    st.error("Could not parse the expected columns (District, K, G1, G2, G3). Please check the template.")
    st.stop()

# ---------- Compute classes & TA positions ----------
def rooms(value: float) -> float:
    if pd.isna(value):
        return 0.0
    classes = value / class_size
    return float(np.ceil(classes)) if rounding_mode.startswith("Ceiling") else float(classes)

# Band 1–2 uses combined classes across both grades.
df["ADM_K"]   = df.get("K", 0).fillna(0)
df["ADM_1_2"] = df.get("G1", 0).fillna(0) + df.get("G2", 0).fillna(0)
df["ADM_3"]   = df.get("G3", 0).fillna(0)

df["Classes_K"]   = df["ADM_K"].apply(rooms)
df["Classes_1_2"] = df["ADM_1_2"].apply(rooms)
df["Classes_3"]   = df["ADM_3"].apply(rooms)

# TA rules
# K: 2 TAs per 3 classes → 2/3 per class
# 1–2: 1 TA per 2 classes → 1/2 per class
# 3: 1 TA per 3 classes → 1/3 per class
df["TA_K"]   = df["Classes_K"]   * (2.0 / 3.0)
df["TA_1_2"] = df["Classes_1_2"] * (1.0 / 2.0)
df["TA_3"]   = df["Classes_3"]   * (1.0 / 3.0)

df["TA_Total_Positions"] = df[["TA_K", "TA_1_2", "TA_3"]].sum(axis=1)

# Funding
df["TA_Funding_Factor"] = funding_factor
df["TA_Total_Funding"] = df["TA_Total_Positions"] * df["TA_Funding_Factor"]

# ---------- District summary ----------
st.subheader("District Summary")
districts = df["District"].astype(str).tolist()
default_idx = next((i for i, d in enumerate(districts) if "alamance" in d.lower()), 0)
pick = st.selectbox("Choose a district", options=districts, index=default_idx)

row = df[df["District"] == pick].iloc[0]

kpi = st.columns(5)
kpi[0].metric("ADM K", f"{int(row['ADM_K'])}")
kpi[1].metric("ADM 1–2", f"{int(row['ADM_1_2'])}")
kpi[2].metric("ADM 3", f"{int(row['ADM_3'])}")
kpi[3].metric("TA Positions (total)", f"{row['TA_Total_Positions']:.2f}")
kpi[4].metric("TA Funding (total)", f"${row['TA_Total_Funding']:,.2f}")

kpi2 = st.columns(3)
kpi2[0].metric("Classes K", f"{row['Classes_K']:.2f}")
kpi2[1].metric("Classes 1–2", f"{row['Classes_1_2']:.2f}")
kpi2[2].metric("Classes 3", f"{row['Classes_3']:.2f}")

with st.expander("Show computed table"):
    show_cols = [
        "LEA_Code", "District",
        "ADM_K", "ADM_1_2", "ADM_3",
        "Classes_K", "Classes_1_2", "Classes_3",
        "TA_K", "TA_1_2", "TA_3",
        "TA_Total_Positions", "TA_Funding_Factor", "TA_Total_Funding"
    ]
    # Include original grade columns for transparency if present
    for c in ["K", "G1", "G2", "G3"]:
        if c in df.columns and c not in show_cols:
            show_cols.insert(2, c)
    st.dataframe(df[show_cols], use_container_width=True, height=420)

# ---------- Download ----------
def to_excel_bytes(df_out: pd.DataFrame) -> bytes:
    with io.BytesIO() as buffer:
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            df_out.to_excel(writer, index=False, sheet_name="PRC027_TA_Results")
        return buffer.getvalue()

st.download_button(
    label="⬇️ Download TA Results (Excel)",
    data=to_excel_bytes(df),
    file_name="PRC027_TA_positions_funding.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)

st.success("TA positions and funding computed. Adjust parameters in the sidebar as needed, then download.")
