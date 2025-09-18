import streamlit as st
import pandas as pd
from simple_salesforce import Salesforce
from io import BytesIO
import re
import time

st.title("Same Store Data Loader")

# --- INIT SESSION STATE ---
if "sf" not in st.session_state:
    st.session_state.sf = None
if "uploaded_file" not in st.session_state:
    st.session_state.uploaded_file = None
if "selected_col" not in st.session_state:
    st.session_state.selected_col = None
if "SF_UserName" not in st.session_state:
    st.session_state.SF_UserName = ""
if "SF_Password" not in st.session_state:
    st.session_state.SF_Password = ""

# 1. User login
SF_UserName = st.text_input(
    "🔄 Salesforce User Name", 
    value=st.session_state.SF_UserName, 
    key="SF_UserName"
)
SF_Password = st.text_input(
    "🔄 Salesforce Password", 
    value=st.session_state.SF_Password, 
    type="password", 
    key="SF_Password"
)

def login():
    try:
        sf_secrets = st.secrets["salesforce_prod"]
        st.session_state.sf = Salesforce(
            username=SF_UserName,
            password=SF_Password,
            instance_url=sf_secrets["instance_url"],
            consumer_key=sf_secrets["consumer_key"],
            consumer_secret=sf_secrets["consumer_secret"]
        )
        st.success("✅ Successfully authenticated to PROD!")
    except Exception as e:
        st.error(f"❌ Authentication failed: {e}")

st.button("🔐 Login", on_click=login)

# 2. File upload
if st.session_state.sf:
    st.session_state.uploaded_file = st.file_uploader("Upload Excel file", type=["xlsx", "xls"])

# 3. Process uploaded file
if st.session_state.uploaded_file:
    df = pd.read_excel(st.session_state.uploaded_file)

    pattern = r"^SameStore'(\d{2}Q\d)_Qtrly Name"
    matching_columns = [col for col in df.columns if re.match(pattern, col)]

    if not matching_columns:
        st.error("No columns found matching the pattern SameStore'YYYYQ#_Qtrly Name")
    else:
        matching_columns = sorted(matching_columns, reverse=True)
        st.session_state.selected_col = st.selectbox("Select Same Store column", matching_columns)

        match = re.match(pattern, st.session_state.selected_col)
        year_quarter = match.group(1)
        year = "20" + year_quarter[:2]
        quarter = f"Q{year_quarter[3]}"
        st.write(f"Selected | Year: {year}, Quarter: {quarter}")

        if st.button("Process Data"):
            st.info("🔄 Processing started...")

            def fetch_and_clean_results(sf, object_name, query):
                fetch_results = getattr(sf.bulk, object_name).query(query, lazy_operation=True)
                all_results = []
                for chunk in fetch_results:
                    all_results.extend(chunk)

                def remove_attributes_keys(d):
                    if isinstance(d, dict):
                        return {k: remove_attributes_keys(v) for k, v in d.items() if k != "attributes"}
                    elif isinstance(d, list):
                        return [remove_attributes_keys(i) for i in d]
                    else:
                        return d
                return [remove_attributes_keys(r) for r in all_results]

            # Fetch Cost Center data
            Cost_Center_Id = pd.DataFrame(
                fetch_and_clean_results(st.session_state.sf, 'Cost_Center__c', "SELECT Id,Name FROM Cost_Center__c")
            )
            Cost_Center_Id['Cost_Center_Value'] = Cost_Center_Id['Name'].astype(str).str[:10]

            # Read uploaded Excel
            Same_Store_data = pd.read_excel(st.session_state.uploaded_file, usecols=['Code', st.session_state.selected_col])
            Same_Store_data = Same_Store_data.dropna(subset=[st.session_state.selected_col])

            # Standardize values
            Same_Store_data[st.session_state.selected_col] = Same_Store_data[st.session_state.selected_col].replace({
                "2024 - Acquisition": "Acquisition",
                "2025 - Acquisition": "Acquisition",
                "Non-SS": "Non Same Store",
                "Greenfield Excl": "Greenfield"
            })

            allowed_values = [
                "Same Store", "Acquisition", "Discontinued", "Expansion",
                "Greenfield", "Non Same Store", "Significant Event",
                "Sold", "Unconsolidated JV"
            ]
            Same_Store_data[st.session_state.selected_col] = Same_Store_data[st.session_state.selected_col].apply(
                lambda x: x if x in allowed_values else f"Bad Value: {x}"
            )

            Same_Store_data['Cost_Center_Value'] = Same_Store_data["Code"].astype(str).str[:10]
            Merged = Same_Store_data.merge(Cost_Center_Id, "left", left_on="Cost_Center_Value", right_on="Cost_Center_Value")

            Dataload = pd.DataFrame()
            Dataload['Cost_Center__r:Cost_Center__c:Production_Id__c'] = Merged['Id']
            Dataload['Reason_for_Same_Store_Status__c'] = Merged[st.session_state.selected_col]
            Dataload['Same_Store__c'] = Merged[st.session_state.selected_col] == "Same Store"

            # Quarter → Start/End
            if quarter == "Q1":
                start_date, end_date = f"{year}-01-01", f"{year}-03-31"
            elif quarter == "Q2":
                start_date, end_date = f"{year}-04-01", f"{year}-06-30"
            elif quarter == "Q3":
                start_date, end_date = f"{year}-07-01", f"{year}-09-30"
            elif quarter == "Q4":
                start_date, end_date = f"{year}-10-01", f"{year}-12-31"

            Dataload['Start_Date__c'] = start_date
            Dataload['End_Date__c'] = end_date

            # Create in-memory Excel
            output = BytesIO()
            Dataload.to_excel(output, index=False)
            output.seek(0)

            st.success("File processed successfully!")    
            # Download button with auto-reset
            st.download_button(
                label="Download Processed File",
                data=output,
                file_name="Same_Store_Dataload.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
