import streamlit as st
import pandas as pd
from simple_salesforce import Salesforce
from io import BytesIO
import datetime

st.title("Same Store Data Loader")

# 1. User login
SF_UserName = st.text_input("🔄 Salesforce User Name")
SF_Password = st.text_input("🔄 Salesforce Password", type="password")

# 2. File upload
uploaded_file = st.file_uploader("Upload Excel file", type=["xlsx", "xls"])

# 3. Quarter selection
quarter_options = ["Q1", "Q2", "Q3", "Q4"]
selected_quarter = st.selectbox("Select Quarter", quarter_options)

def fetch_and_clean_results(sf, object_name, query):
    fetch_results = getattr(sf.bulk, object_name).query(query, lazy_operation=True)
    all_results = []

    for chunk in fetch_results:
        all_results.extend(chunk)  # chunk is a list of dicts

    # Remove 'attributes' keys
    def remove_attributes_keys(d):
        if isinstance(d, dict):
            return {k: remove_attributes_keys(v) for k, v in d.items() if k != "attributes"}
        elif isinstance(d, list):
            return [remove_attributes_keys(i) for i in d]
        else:
            return d

    cleaned_results = [remove_attributes_keys(r) for r in all_results]

    return cleaned_results


# Only run processing when user clicks the button
if st.button("Process Data"):
    if not SF_UserName or not SF_Password or not uploaded_file:
        st.error("Please provide username, password, and upload a file.")
    else:
        sf_secrets = st.secrets[f"salesforce_prod"]
        sf = Salesforce(
                username=SF_UserName,
                password=SF_Password,
                instance_url=sf_secrets["instance_url"],
                consumer_key=sf_secrets["consumer_key"],
                consumer_secret=sf_secrets["consumer_secret"]
            )
        st.success("✅ Successfully authenticated to PROD!")

        # Fetch Cost Center data
        Cost_Center_Id = pd.DataFrame(
            fetch_and_clean_results(sf, 'Cost_Center__c', "SELECT Id,Name FROM Cost_Center__c")
        )
        st.dataframe(Cost_Center_Id)
        Cost_Center_Id['Cost_Center_Value'] = Cost_Center_Id['Name'].astype(str).str[:10]

        # Read uploaded Excel
        Same_Store_data = pd.read_excel(uploaded_file, usecols=['Code', "SameStore'25Q4_Qtrly Name"])
        Same_Store_data = Same_Store_data.dropna(subset=["SameStore'25Q4_Qtrly Name"])

        # Standardize values
        Same_Store_data["SameStore'25Q4_Qtrly Name"] = Same_Store_data["SameStore'25Q4_Qtrly Name"].replace({
            "2024 - Acquisition": "Acquisition",
            "2025 - Acquisition": "Acquisition",
            "Non-SS": "Non Same Store",
            "Greenfield Excl": "Greenfield"
        })

        allowed_values = [
            "Same Store",
            "Acquisition",
            "Discontinued",
            "Expansion",
            "Greenfield",
            "Non Same Store",
            "Significant Event",
            "Sold",
            "Unconsolidated JV"
        ]

        Same_Store_data["SameStore'25Q4_Qtrly Name"] = Same_Store_data["SameStore'25Q4_Qtrly Name"].apply(
            lambda x: x if x in allowed_values else f"Bad Value: {x}"
        )

        Same_Store_data['Cost_Center_Value'] = Same_Store_data["Code"].astype(str).str[:10]
        Merged = Same_Store_data.merge(Cost_Center_Id, "left", left_on="Cost_Center_Value", right_on="Cost_Center_Value")

        Dataload = pd.DataFrame()
        Dataload['Cost_Center__r:Cost_Center__c:Production_Id__c'] = Merged['Id']
        Dataload['Reason_for_Same_Store_Status__c'] = Merged["SameStore'25Q4_Qtrly Name"]
        Dataload['Same_Store__c'] = Merged["SameStore'25Q4_Qtrly Name"] == "Same Store"

        # Calculate Start and End dates based on selected quarter
        year = datetime.date.today().year
        if selected_quarter == "Q1":
            start_date = f"{year}-01-01"
            end_date = f"{year}-03-31"
        elif selected_quarter == "Q2":
            start_date = f"{year}-04-01"
            end_date = f"{year}-06-30"
        elif selected_quarter == "Q3":
            start_date = f"{year}-07-01"
            end_date = f"{year}-09-30"
        elif selected_quarter == "Q4":
            start_date = f"{year}-10-01"
            end_date = f"{year}-12-31"

        Dataload['Start_Date__c'] = start_date
        Dataload['End_Date__c'] = end_date

        # Create in-memory Excel
        output = BytesIO()
        Dataload.to_excel(output, index=False)
        output.seek(0)

        # Provide download link
        st.download_button(
            label="Download Processed File",
            data=output,
            file_name="Same_Store_Dataload.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

        st.success("File processed successfully!")
