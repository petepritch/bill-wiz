import sys
import os

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
)

from parsers.xml_parser import parse_bill

import streamlit as st

st.title("Mama's Bill Wizard")

upload_file = st.file_uploader("Upload your CFDI file", type=["xml"])
if upload_file is not None:
    invoice_number, bill_df, bill_data = parse_bill(upload_file)
    st.write(f"Invoice Number: {invoice_number}")
    st.dataframe(bill_df)

    if st.button("Submit to QuickBooks"):
        st.success("Submitted!")
