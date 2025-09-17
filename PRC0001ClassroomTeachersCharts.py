import io
import math
import re
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st
import altair as alt  # NEW

st.set_page_config(page_title="PRC 0001 — Classroom Teachers", layout="wide")

st.title("PRC 0001 — ADM → Teacher Positions & Funding")
st.caption("Upload an ADM workbook (e.g., ADM2024.xlsx) or place one in **data/**. "
           "App computes positions by Grade-Band ratios, then funding; optional MSC/IFE add-ons.")

# ───────────────── Sidebar ─────────────────
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

# ───────────────── File input: upload OR auto-pick from ./data ─────────────────
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

# ───────────────── Read & normalize ADM ─────────────────
def first_nonempty_sheet(xls: pd.ExcelFile):
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

    if "District" in df.columns:
        df = df[df["District"].notna()].copy()
    if present_cols:
        df = df[df[present_cols].notna().any(axis=1)].copy()
    return df

df = read_adm_sheet(file_obj)
if df.empty or "District" not in df.columns:
    st.error("Could not parse the expected columns. Please check the template.")
    st.stop()

# ───────────────── Compute positions & funding ─────────────────
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
    df["Total_Funding"] = df["Total_Positions"] * df["Comp_Per_Teacher"]

    # Helpful Grade funding columns for charts
    df["Fund_K_3"] = df["Pos_K_3"] * df["Comp_Per_Teacher"]
    df["Fund_4_8"] = df["Pos_4_8"] * df["Comp_Per_Teacher"]
    df["Fund_9"] = df["Pos_9"] * df["Comp_Per_Teacher"]
    df["Fund_10_12"] = df["Pos_10_12"] * df["Comp_Per_Teacher"]
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

# ───────────────── Overrides & KPIs ─────────────────
st.subheader("Per-district Overrides (optional)")
st.caption("Edit counts if a district should receive different MSC/IFE allocations. Rates come from the sidebar.")

edit_cols = ["LEA_Code","District","MSC_Count","IFE_Count"]
edited = st.data_editor(df[edit_cols], num_rows="fixed", use_container_width=True, key="editor_counts")

df = df.drop(columns=["MSC_Count","IFE_Count"]).merge(
    edited[["LEA_Code","District","MSC_Count","IFE_Count"]],
    on=["LEA_Code","District"],
    how="left"
)

# Recompute add-ons after edits
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

# ───────────────── Charts ─────────────────
st.subheader("Charts")

# Per-district Grade dataframe
Grade_df = pd.DataFrame({
    "Grade": ["K–3", "4–8", "9", "10–12"],
    "ADM": [row["ADM_K_3"], row["ADM_4_8"], row["ADM_9"], row["ADM_10_12"]],
    "Positions": [row["Pos_K_3"], row["Pos_4_8"], row["Pos_9"], row["Pos_10_12"]],
    "Funding": [row["Fund_K_3"], row["Fund_4_8"], row["Fund_9"], row["Fund_10_12"]],
})

c1, c2 = st.columns(2)
with c1:
    st.caption(f"ADM by Grade — {row['District']}")
    chart_adm = alt.Chart(Grade_df).mark_bar().encode(
        x=alt.X("Grade:N", title="Grade"),
        y=alt.Y("ADM:Q", title="ADM"),
        tooltip=["Grade", alt.Tooltip("ADM:Q", format=",.0f")]
    ).properties(height=280)
    st.altair_chart(chart_adm, use_container_width=True)

with c2:
    st.caption(f"Positions by Grade — {row['District']}")
    chart_pos = alt.Chart(Grade_df).mark_bar().encode(
        x=alt.X("Grade:N", title="Grade"),
        y=alt.Y("Positions:Q", title="Teacher Positions"),
        tooltip=["Grade", alt.Tooltip("Positions:Q", format=",.2f")]
    ).properties(height=280)
    st.altair_chart(chart_pos, use_container_width=True)

# Donut: funding share by Grade
st.caption(f"Funding Share by Grade — {row['District']}")
fund_df = Grade_df.copy()
fund_df["pct"] = fund_df["Funding"] / max(float(row["Total_Funding"]), 1e-9)
donut = alt.Chart(fund_df).mark_arc(innerRadius=60).encode(
    theta=alt.Theta("Funding:Q"),
    color=alt.Color("Grade:N"),
    tooltip=[
        "Grade",
        alt.Tooltip("Funding:Q", title="Funding", format="$,.0f"),
        alt.Tooltip("pct:Q", title="Share", format=".1%")
    ]
).properties(height=300)
st.altair_chart(donut, use_container_width=True)

# Statewide Top-10 charts
st.subheader("Statewide Top-10")
metric_pick = st.selectbox("Rank by", options=["Total_Positions", "Grand_Total_Funding"], index=0)
top = df[["District", "Total_Positions", "Grand_Total_Funding"]].copy()
top = top.sort_values(metric_pick, ascending=False).head(10)
if metric_pick == "Total_Positions":
    bar = alt.Chart(top).mark_bar().encode(
        y=alt.Y("District:N", sort="-x", title=None),
        x=alt.X("Total_Positions:Q", title="Total Positions"),
        tooltip=["District", alt.Tooltip("Total_Positions:Q", format=",.2f")]
    ).properties(height=360)
else:
    bar = alt.Chart(top).mark_bar().encode(
        y=alt.Y("District:N", sort="-x", title=None),
        x=alt.X("Grand_Total_Funding:Q", title="Grand Total Funding", axis=alt.Axis(format="$,.0f")),
        tooltip=["District", alt.Tooltip("Grand_Total_Funding:Q", format="$,.0f")]
    ).properties(height=360)
st.altair_chart(bar, use_container_width=True)

# ───────────────── Table ─────────────────
with st.expander("Show computed columns table"):
    base_cols = ["LEA_Code","District","K","G1","G2","G3","G4","G5","G6","G7","G8","G9","G10","G11","G12","TOTAL",
                 "ADM_K_3","ADM_4_8","ADM_9","ADM_10_12",
                 "Pos_K_3","Pos_4_8","Pos_9","Pos_10_12","Total_Positions",
                 "Comp_Per_Teacher","Total_Funding",
                 "Fund_K_3","Fund_4_8","Fund_9","Fund_10_12",
                 "MSC_Count","MSC_Rate","MSC_Funding",
                 "IFE_Count","IFE_Rate","IFE_Funding",
                 "Grand_Total_Funding"]
    show_cols = [c for c in base_cols if c in df.columns]
    st.dataframe(df[show_cols], use_container_width=True, height=400)

# ───────────────── Download ─────────────────
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

st.success("Computed successfully. Use the charts to explore Grades and see statewide leaders.")
