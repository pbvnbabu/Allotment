# PRC 061 Formula Breakdown
# Base Funding
# # $31.51 per ADM (Average Daily Membership) for all students K–12
# #  PSAT Testing Supplement
# # $2.69 per ADM for students in grades 8 and 9 only

import io
import re
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

# ───────────────── Page ─────────────────
st.set_page_config(page_title="PRC Toolkit — ADM Funding Apps", layout="wide")
st.title("PRC Toolkit — ADM Funding Apps")
st.caption("Upload an ADM workbook or drop one in **data/** (e.g., ADM2025.xlsx). Use the tabs for PRC 027 and PRC 061.")


# ───────────────── Default file discovery ─────────────────
DATA_DIR = Path("data")

def pick_default_adm_file() -> Path | None:
    """
    Look for ADM workbooks in ./data and pick:
      1) Highest YEAR among files named like ADM2025.xlsx / ADM2024.xls, else
      2) Most recently modified file that contains 'adm' in the name.
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


# ───────────────── File input (single source for both tabs) ─────────────────
uploaded = st.file_uploader("Upload ADM workbook (xlsx/xls)", type=["xlsx", "xls"])
DEFAULT_FILE = pick_default_adm_file()

file_obj = uploaded
if file_obj is None and DEFAULT_FILE is not None:
    st.info(f"No upload detected — using bundled default: **{DEFAULT_FILE.as_posix()}**")
    file_obj = DEFAULT_FILE.open("rb")

if file_obj is None:
    st.info("Upload your ADM workbook or place one in **data/** (e.g., ADM2025.xlsx).")
    st.stop()


# ───────────────── Helpers to read ADM once ─────────────────
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
    # Try mapping: [code, district, K, 1..12, TOTAL]
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
            cols[15]: "TOTAL",
        })

    # Coerce numeric on grade columns that exist
    grade_cols = ["K","G1","G2","G3","G4","G5","G6","G7","G8","G9","G10","G11","G12"]
    for c in grade_cols + (["TOTAL"] if "TOTAL" in df.columns else []):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    # Keep valid districts with at least some grade data
    if "District" in df.columns:
        df = df[df["District"].notna()].copy()
    present = [c for c in grade_cols if c in df.columns]
    if present:
        df = df[df[present].notna().any(axis=1)].copy()
    return df

df_base = read_adm_sheet(file_obj)
if df_base.empty or "District" not in df_base.columns:
    st.error("Could not parse expected columns (District, grades K–12). Please check the template.")
    st.stop()


# ───────────────── Tabs ─────────────────
tab_ta, tab_psat = st.tabs(["PRC 027 — Teacher Assistants", "PRC 061 — Base + PSAT"])

# ============= PRC 027 — Teacher Assistants =============
with tab_ta:
    st.subheader("PRC 027 — Teacher Assistants (TA) Estimator")
    st.caption("Rules: Class size = 21. K → 2 TAs per 3 classes; Grades 1–2 → 1 TA per 2 classes; Grade 3 → 1 TA per 3 classes.")

    colA, colB, colC = st.columns([1,1,1])
    with colA:
        class_size = st.number_input("Class size (students per class)", value=21.0, min_value=1.0, step=1.0)
    with colB:
        rounding_mode = st.radio("Class rounding", ["Ceiling (whole classes)", "Exact (decimals)"], index=0, horizontal=True)
    with colC:
        funding_factor = st.number_input("Funding factor ($ per TA position)", value=48030.97, min_value=0.0, step=100.0, format="%.2f")

    def rooms(value: float) -> float:
        if pd.isna(value):
            return 0.0
        classes = value / class_size
        return float(np.ceil(classes)) if rounding_mode.startswith("Ceil") else float(classes)

    dfta = df_base.copy()
    dfta["ADM_K"]   = dfta.get("K", 0).fillna(0)
    dfta["ADM_1_2"] = dfta.get("G1", 0).fillna(0) + dfta.get("G2", 0).fillna(0)
    dfta["ADM_3"]   = dfta.get("G3", 0).fillna(0)

    dfta["Classes_K"]   = dfta["ADM_K"].apply(rooms)
    dfta["Classes_1_2"] = dfta["ADM_1_2"].apply(rooms)
    dfta["Classes_3"]   = dfta["ADM_3"].apply(rooms)

    # TA factors per class
    dfta["TA_K"]   = dfta["Classes_K"]   * (2.0/3.0)
    dfta["TA_1_2"] = dfta["Classes_1_2"] * (1.0/2.0)
    dfta["TA_3"]   = dfta["Classes_3"]   * (1.0/3.0)

    dfta["TA_Total_Positions"] = dfta[["TA_K","TA_1_2","TA_3"]].sum(axis=1)
    dfta["TA_Funding_Factor"] = funding_factor
    dfta["TA_Total_Funding"] = dfta["TA_Total_Positions"] * dfta["TA_Funding_Factor"]

    # District summary
    districts = dfta["District"].astype(str).tolist()
    default_idx = next((i for i, d in enumerate(districts) if "alamance" in d.lower()), 0)
    pick = st.selectbox("Choose a district", options=districts, index=default_idx, key="pick_ta")
    row = dfta[dfta["District"] == pick].iloc[0]

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("ADM K", f"{int(row['ADM_K'])}")
    k2.metric("ADM 1–2", f"{int(row['ADM_1_2'])}")
    k3.metric("ADM 3", f"{int(row['ADM_3'])}")
    k4.metric("TA Positions (total)", f"{row['TA_Total_Positions']:.2f}")
    k5.metric("TA Funding (total)", f"${row['TA_Total_Funding']:,.2f}")

    with st.expander("Show computed table (PRC 027)"):
        show_cols = [
            "LEA_Code","District",
            "ADM_K","ADM_1_2","ADM_3",
            "Classes_K","Classes_1_2","Classes_3",
            "TA_K","TA_1_2","TA_3",
            "TA_Total_Positions","TA_Funding_Factor","TA_Total_Funding"
        ]
        # Add original grades for transparency if present
        for c in ["K","G1","G2","G3"]:
            if c in dfta.columns and c not in show_cols:
                show_cols.insert(2, c)
        st.dataframe(dfta[show_cols], use_container_width=True, height=420)

    # Download
    def to_excel_bytes(df_out: pd.DataFrame, sheet="PRC027_TA_Results") -> bytes:
        with io.BytesIO() as buffer:
            with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
                df_out.to_excel(writer, index=False, sheet_name=sheet)
            return buffer.getvalue()

    st.download_button(
        "⬇️ Download PRC 027 Results (Excel)",
        data=to_excel_bytes(dfta),
        file_name="PRC027_TA_positions_funding.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True
    )

# ============= PRC 061 — Base + PSAT =============
with tab_psat:
    st.subheader("PRC 061 — Base Funding + PSAT Supplement")
    st.caption("Base: $ per ADM K–12; PSAT Supplement: $ per ADM for grades 8 & 9 only.")

    c1, c2 = st.columns([1,1])
    with c1:
        base_per_adm = st.number_input("Base $ per ADM (K–12)", value=31.51, min_value=0.0, step=0.25, format="%.2f", key="base_per_adm_psat")
    with c2:
        psat_per_adm = st.number_input("PSAT $ per ADM (grades 8 & 9)", value=2.69, min_value=0.0, step=0.25, format="%.2f", key="psat_per_adm_psat")

    dfp = df_base.copy()
    grades = [c for c in ["K","G1","G2","G3","G4","G5","G6","G7","G8","G9","G10","G11","G12"] if c in dfp.columns]
    dfp["ADM_Total_K12"] = dfp[grades].sum(axis=1, min_count=1)

    dfp["ADM_PSAT_Eligible"] = dfp.get("G8", 0).fillna(0) + dfp.get("G9", 0).fillna(0)

    dfp["Base_per_ADM"] = float(base_per_adm)
    dfp["PSAT_per_ADM"] = float(psat_per_adm)

    dfp["Base_Funding"] = dfp["ADM_Total_K12"] * dfp["Base_per_ADM"]
    dfp["PSAT_Supplement"] = dfp["ADM_PSAT_Eligible"] * dfp["PSAT_per_ADM"]
    dfp["Total_Funding"] = dfp["Base_Funding"] + dfp["PSAT_Supplement"]

    districts2 = dfp["District"].astype(str).tolist()
    default_idx2 = next((i for i, d in enumerate(districts2) if "alamance" in d.lower()), 0)
    pick2 = st.selectbox("Choose a district", options=districts2, index=default_idx2, key="pick_psat")
    row2 = dfp[dfp["District"] == pick2].iloc[0]

    p1, p2, p3, p4, p5 = st.columns(5)
    p1.metric("ADM (K–12)", f"{int(row2['ADM_Total_K12'])}")
    p2.metric("ADM (Grades 8–9)", f"{int(row2['ADM_PSAT_Eligible'])}")
    p3.metric("Base $/ADM", f"${row2['Base_per_ADM']:,.2f}")
    p4.metric("PSAT $/ADM", f"${row2['PSAT_per_ADM']:,.2f}")
    p5.metric("Total Funding", f"${row2['Total_Funding']:,.2f}")

    with st.expander("Show computed table (PRC 061)"):
        show_cols = (
            ["LEA_Code","District"]
            + [c for c in ["K","G1","G2","G3","G4","G5","G6","G7","G8","G9","G10","G11","G12","TOTAL"] if c in dfp.columns]
            + ["ADM_Total_K12","ADM_PSAT_Eligible",
               "Base_per_ADM","Base_Funding","PSAT_per_ADM","PSAT_Supplement","Total_Funding"]
        )
        st.dataframe(dfp[show_cols], use_container_width=True, height=420)

    # Download
    def to_excel_bytes(df_out: pd.DataFrame, sheet="PRC061_Results") -> bytes:
        with io.BytesIO() as buffer:
            with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
                df_out.to_excel(writer, index=False, sheet_name=sheet)
            return buffer.getvalue()

    st.download_button(
        "⬇️ Download PRC 061 Results (Excel)",
        data=to_excel_bytes(dfp),
        file_name="PRC061_base_psat_results.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True
    )
