# PRC 0001 — Classroom Teachers
# Purpose
# Fund teacher positions based on student enrollment (ADM) using grade-specific
# staffing ratios, then convert positions to dollars.
# Grade-Band Ratios
# | Grade Band | Ratio (Students : Teacher) |
# | ---------- | -------------------------- |
# | K–3        | **1 : 18**                 |
# | 4–8        | **1 : 24**                 |
# | 9          | **1 : 26.5**               |
# | 10–12      | **1 : 29**                 |
# Inputs (per district/county)
# ADM by grade (K, 1, …, 12)
# Statewide average salary + benefits per teacher (e.g., $70,000)
# Optional add-ons:
# MSC (Math/Science/Computer) teachers (e.g., 1 per county @ $70,000 each)
# IFE (International Faculty Exchange) positions (e.g., $78,421 each)

import io
import math
import re
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

st.set_page_config(page_title="PRC 0001 — Classroom Teachers", layout="wide")

st.title("PRC 0001 — ADM → Teacher Positions & Funding")
st.caption("Upload an ADM workbook (e.g., ADM2024.xlsx) or place one in **data/**. "
           "App computes positions by grade-band ratios, then funding; optional MSC/IFE add-ons.")

# ─────────────────────────────────────────────────────────────
# Sidebar parameters
# ─────────────────────────────────────────────────────────────
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
    default_msc = st.checkbox("Apply 1 Math/Science/Computer (MSC) teacher to every district", value=True)
    default_ife = st.checkbox("Apply 1 IFE to every district", value=True)
    msc_rate = st.number_input("MSC Rate ($)", value=70000.0, min_value=0.0, step=1000.0, format="%.2f")
    ife_rate = st.number_input("IFE Rate ($)", value=78421.0, min_value=0.0, step=1000.0, format="%.2f")

# ─────────────────────────────────────────────────────────────
# File input: upload OR auto-pick best default from ./data
# ─────────────────────────────────────────────────────────────
DATA_DIR = Path("data")

def pick_default_adm_file() -> Path | None:
    """
    Pick best ADM workbook from ./data:
      1) Highest YEAR among files like ADM2025.xlsx / ADM2024.xls, else
      2) Most recently modified file containing 'adm' (case-insensitive).
    """
    if not DATA_DIR.exists():
        return None

    candidates = list(DATA_DIR.glob("ADM*.xls*"))
    if not candidates:
        candidates = [p for p in DATA_DIR.glob("*.xls*") if re.search(r"adm", p.name, re.I)]
    if not candidates:
        return None

    def score(p: Path):
        m = re.search(r"(20\d{2})", p.stem)  # e.g., ADM2025
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

# ─────────────────────────────────────────────────────────────
# Read & normalize ADM
# ─────────────────────────────────────────────────────────────
def first_nonempty_sheet(xls: pd.ExcelFile):
    for s in xls.sheet_names:
        if "adm" in s.lower():
            return s
    return xls.sheet_names[0]

def read_adm_sheet(file) -> pd.DataFrame:
    xls = pd.ExcelFile(file)
    sheet = first_nonempty_sheet(xls)
    df = pd.read_excel(xls, sheet_name=sheet)

    # Try mapping: [code, district, K, 1..12, TOTAL]
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

    # Coerce numeric
    grade_cols = ["K","G1","G2","G3","G4","G5","G6","G7","G8","G9","G10","G11","G12"]
    present_cols = [c for c in grade_cols if c in df.columns]
    for c in present_cols + (["TOTAL"] if "TOTAL" in df.columns else []):
        df[c] = pd.to_numeric(df[c], errors="coerce")

    # Keep valid rows
    if "District" in df.columns:
        df = df[df["District"].notna()].copy()
    if present_cols:
        df = df[df[present_cols].notna().any(axis=1)].copy()
    return df

df = read_adm_sheet(file_obj)
if df.empty or "District" not in df.columns:
    st.error("Could not parse the expected columns. Please check the template.")
    st.stop()

# ─────────────────────────────────────────────────────────────
# Compute positions & funding
# ─────────────────────────────────────────────────────────────
def compute_positions(df: pd.DataFrame) -> pd.DataFrame:
    df["ADM_K_3"] = df[["K","G1","G2","G3"]].sum(axis=1, min_count=1)
    df["ADM_4_8"] = df[["G4","G5","G6","G7","G8"]].sum(axis=1, min_count=1)
    df["ADM_9"] = df["G9"]
    df["ADM_10_12"] = df[["G10","G11","G12"]].sum(axis=1, min_count=1)

    df["Pos_K_3"] = df["ADM_K_3"] / ratio_k3
    df["Pos_4_8"] = df["ADM_4_8"] / ratio_4_8
    df["Pos_9"] = df["ADM_9"] / ratio_9
    df["Pos_10_12"] = df["ADM_10_12"] / ratio_10_12

    df["Total_Positions"] = df[["Pos_K_3","Pos_4_8","Pos_9","Pos_10_12"]].sum(axis=1)

    df["Comp_Per_Teacher"] = comp_per_teacher
    df["Total_Funding"] = df["Total_Positions"] * comp_per_teacher
    return df

def add_extras(df: pd.DataFrame) -> pd.DataFrame:
    if "MSC_Count" not in df.columns:
        df["MSC_Count"] = 0
    if "IFE_Count" not in df.columns:
        df["IFE_Count"] = 0
    if default_msc:
        df["MSC_Count"] = 1
    if default_ife:
        df["IFE_Count"] = 1
    df["MSC_Rate"] = msc_rate
    df["IFE_Rate"] = ife_rate
    df["MSC_Funding"] = df["MSC_Count"] * df["MSC_Rate"]
    df["IFE_Funding"] = df["IFE_Count"] * df["IFE_Rate"]
    df["Grand_Total_Funding"] = df["Total_Funding"] + df["MSC_Funding"] + df["IFE_Funding"]
    return df

df = compute_positions(df)
df = add_extras(df)

# ─────────────────────────────────────────────────────────────
# UI: per-district overrides & summary
# ─────────────────────────────────────────────────────────────
st.subheader("Per-district Overrides (optional)")
st.caption("Edit counts if a district should receive different MSC/IFE allocations. Rates come from the sidebar.")

edit_cols = ["LEA_Code","District","MSC_Count","IFE_Count"]
edited = st.data_editor(df[edit_cols], num_rows="fixed", use_container_width=True, key="editor_counts")

# Write back overrides
df = df.drop(columns=["MSC_Count","IFE_Count"]).merge(
    edited[["LEA_Code","District","MSC_Count","IFE_Count"]],
    on=["LEA_Code","District"],
    how="left"
)
# Recompute add-ons with edited counts
df["MSC_Rate"] = msc_rate
df["IFE_Rate"] = ife_rate
df["MSC_Funding"] = df["MSC_Count"] * df["MSC_Rate"]
df["IFE_Funding"] = df["IFE_Count"] * df["IFE_Rate"]
df["Grand_Total_Funding"] = df["Total_Funding"] + df["MSC_Funding"] + df["IFE_Funding"]

# District picker & KPIs
st.subheader("District Summary")
districts = df["District"].astype(str).tolist()
pick = st.selectbox("Choose a district", options=districts,
                    index=next((i for i,d in enumerate(districts) if "alamance" in d.lower()), 0))
row = df[df["District"] == pick].iloc[0]

kpi_cols = st.columns(5)
kpi_cols[0].metric("K–3 ADM", f"{int(row['ADM_K_3'])}")
kpi_cols[1].metric("4–8 ADM", f"{int(row['ADM_4_8'])}")
kpi_cols[2].metric("9 ADM", f"{int(row['ADM_9'])}")
kpi_cols[3].metric("10–12 ADM", f"{int(row['ADM_10_12'])}")
kpi_cols[4].metric("Total Positions", f"{row['Total_Positions']:.2f}")

kpi2 = st.columns(3)
kpi2[0].metric("Comp/Teacher", f"${row['Comp_Per_Teacher']:,.2f}")
kpi2[1].metric("Base Funding", f"${row['Total_Funding']:,.2f}")
kpi2[2].metric("Grand Total (with MSC & IFE)", f"${row['Grand_Total_Funding']:,.2f}")

with st.expander("Show computed columns table"):
    base_cols = ["LEA_Code","District","K","G1","G2","G3","G4","G5","G6","G7","G8","G9","G10","G11","G12","TOTAL",
                 "ADM_K_3","ADM_4_8","ADM_9","ADM_10_12",
                 "Pos_K_3","Pos_4_8","Pos_9","Pos_10_12","Total_Positions",
                 "Comp_Per_Teacher","Total_Funding",
                 "MSC_Count","MSC_Rate","MSC_Funding",
                 "IFE_Count","IFE_Rate","IFE_Funding",
                 "Grand_Total_Funding"]
    show_cols = [c for c in base_cols if c in df.columns]  # guard against missing columns
    st.dataframe(df[show_cols], use_container_width=True, height=400)

# ─────────────────────────────────────────────────────────────
# Download
# ─────────────────────────────────────────────────────────────
def to_excel_bytes(df_out: pd.DataFrame) -> bytes:
    with io.BytesIO() as buffer:
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            df_out.to_excel(writer, index=False, sheet_name="PRC0001_Results")
        return buffer.getvalue()

st.download_button(
    label="⬇️ Download results as Excel",
    data=to_excel_bytes(df),
    file_name="PRC0001_positions_funding_results.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)

st.success("Computed successfully. Adjust ratios & compensation in the sidebar, override MSC/IFE as needed, then download.")
