import pandas as pd

# File path
file_path = r"C:\tmp\Allotment\PRC0001\ADM2024.XLSX"

# Load the ADM data
df = pd.read_excel(file_path, sheet_name="FY24 Allotted ADM", skiprows=4)

# Define grade groups and ratios
grades_k3 = ['KIND', '1ST', '2ND', '3RD']
grades_4_8 = ['4TH', '5TH', '6TH', '7TH', '8TH']
grade_9 = ['9TH']
grades_10_12 = ['10TH', '11TH', '12TH']

ratios = {
    'K3': 18,
    '4_8': 24,
    '9': 26.5,
    '10_12': 29
}

# Compensation values
base_salary = 55000
benefits = 15000
base_total = base_salary + benefits
ife_total = 78421
msc_teacher_total = base_total

# Function to calculate funding
def calculate_funding(row):
    try:
        k3_adm = sum([row.get(grade, 0) for grade in grades_k3])
        g4_8_adm = sum([row.get(grade, 0) for grade in grades_4_8])
        g9_adm = row.get('9TH', 0)
        g10_12_adm = sum([row.get(grade, 0) for grade in grades_10_12])

        k3_positions = k3_adm / ratios['K3']
        g4_8_positions = g4_8_adm / ratios['4_8']
        g9_positions = g9_adm / ratios['9']
        g10_12_positions = g10_12_adm / ratios['10_12']

        total_positions = k3_positions + g4_8_positions + g9_positions + g10_12_positions
        base_funding = total_positions * base_total

        total_funding = base_funding + msc_teacher_total + ife_total
        return round(total_funding, 2)
    except:
        return None

# Apply the funding calculation
df['TotalFunding'] = df.apply(calculate_funding, axis=1)

# Save the updated file
output_path = r"C:\tmp\Allotment\PRC0001\ADM2024_with_TotalFunding.xlsx"
df.to_excel(output_path, index=False)

print("TotalFunding column added and file saved successfully.")
