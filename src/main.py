"""
Mama's Bill Wizard - Main Application with Inventory Support

This Streamlit application helps upload and process CFDI XML files
and submit them to QuickBooks as bills with support for inventory items.
"""

import sys
import os
import streamlit as st
import pandas as pd
from datetime import datetime

# Add the src directory to the path
sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
)

# Import custom modules
from parsers.xml_parser import parse_bill
from qb.qb_auth import check_qb_connection
from qb.qb_api import get_vendors, get_accounts
from qb.qb_bill import get_all_items, create_bill

# Set page config
st.set_page_config(page_title="Mama's Bill Wizard", page_icon="📊", layout="wide")


def format_bill_data(invoice_number, bill_df):
    """Format bill dataframe into the structure expected by the bill builder"""
    line_items = []

    for _, row in bill_df.iterrows():
        # Extract SKU from the description if possible
        # Look for common SKU patterns like "SKU: ABC123" or "[ABC123]" or product codes
        description = row.get("Descripcion", "")
        sku = ""

        # Check if there's a NoIdentificacion field (common in CFDI for product code/SKU)
        if "NoIdentificacion" in row:
            sku = row["NoIdentificacion"]
        # Check for "SKU:" or "Código:" pattern
        elif "SKU:" in description:
            sku = description.split("SKU:")[1].split()[0].strip()
        elif "Codigo:" in description or "Código:" in description:
            sku_part = (
                description.split("Codigo:")[1]
                if "Codigo:" in description
                else description.split("Código:")[1]
            )
            sku = sku_part.split()[0].strip()
        # Check for square bracket pattern [ABC123]
        elif "[" in description and "]" in description:
            start = description.find("[") + 1
            end = description.find("]", start)
            if end > start:
                sku = description[start:end].strip()
        # Check for parentheses pattern (ABC123)
        elif "(" in description and ")" in description:
            start = description.find("(") + 1
            end = description.find(")", start)
            if end > start:
                potential_sku = description[start:end].strip()
                # Only use if it looks like a SKU (contains numbers or is short)
                if any(c.isdigit() for c in potential_sku) or len(potential_sku) < 10:
                    sku = potential_sku

        item = {
            "product": description,
            "sku": sku,
            "amount": float(row.get("Importe", 0)),
            "quantity": float(row.get("Cantidad", 1)),
        }
        line_items.append(item)

    return {"invoice_number": invoice_number, "line_items": line_items}


def main():
    """Main application function"""
    st.title("Mama's Bill Wizard")

    # Check QuickBooks connection first
    if not check_qb_connection():
        return

    # Main app functionality once authenticated
    # We'll use columns for layout
    col1, col2 = st.columns([1, 1])

    with col1:
        st.subheader("Upload CFDI")
        upload_file = st.file_uploader("Upload your CFDI file", type=["xml"])

        bill_data = None
        if upload_file is not None:
            try:
                invoice_number, bill_df, raw_bill_data = parse_bill(upload_file)

                # Format bill data for the bill builder
                bill_data = format_bill_data(invoice_number, bill_df)

                st.success(f"Successfully parsed invoice #{invoice_number}")
                st.dataframe(bill_df)
            except Exception as e:
                st.error(f"Error parsing XML file: {str(e)}")
                bill_df = None
                invoice_number = None

    with col2:
        st.subheader("QuickBooks Details")

        # Get vendor list
        vendors = get_vendors()

        if not vendors:
            st.warning("No vendors found in your QuickBooks account.")
        else:
            vendor_names = [name for name, _ in vendors]
            selected_vendor = st.selectbox("Select a Vendor", vendor_names)

            selected_vendor_id = next(
                (id for name, id in vendors if name == selected_vendor), None
            )

            # Bill options
            st.subheader("Bill Options")

            # Date selector
            bill_date = st.date_input("Bill Date", value=datetime.now())

            # Item/Expense toggle
            use_items = st.checkbox("Use Inventory Items (Recommended)", value=True)

            if use_items:
                st.info(
                    "The system will try to match product descriptions to inventory items in QuickBooks. "
                    "If a match isn't found, it will use the default expense account."
                )

                # We'll need a default expense account as fallback
                accounts = get_accounts(account_type="Expense")

                if accounts:
                    account_names = [name for name, _ in accounts]
                    selected_account = st.selectbox(
                        "Default Expense Account (for items not found)", account_names
                    )

                    selected_account_id = next(
                        (id for name, id in accounts if name == selected_account), "7"
                    )
                else:
                    selected_account_id = "7"  # Default account
                    st.warning("No expense accounts found. Using default account.")
            else:
                # Regular expense account
                accounts = get_accounts(account_type="Expense")

                if accounts:
                    account_names = [name for name, _ in accounts]
                    selected_account = st.selectbox("Expense Account", account_names)

                    selected_account_id = next(
                        (id for name, id in accounts if name == selected_account), "7"
                    )
                else:
                    selected_account_id = "7"  # Default account
                    st.warning("No expense accounts found. Using default account.")

            # Submit button
            if selected_vendor_id and bill_data is not None:
                if st.button("Submit to QuickBooks"):
                    try:
                        success, result, missing_items = create_bill(
                            bill_data=bill_data,
                            vendor_id=selected_vendor_id,
                            account_id=selected_account_id,
                            txn_date=bill_date.strftime("%Y-%m-%d"),
                            use_item_based_expense=use_items,
                            default_expense_account_id=selected_account_id,
                        )

                        if success:
                            st.success(
                                f"Bill created successfully! Bill ID: {result.get('Bill', {}).get('Id')}"
                            )

                            if missing_items:
                                with st.expander("Items not found in QuickBooks"):
                                    st.warning(
                                        "The following items could not be matched to inventory items in QuickBooks "
                                        "and were recorded using the default expense account:"
                                    )
                                    for item in missing_items:
                                        st.write(f"- {item}")
                        else:
                            st.error(f"Failed to create bill: {result}")
                    except Exception as e:
                        st.error(f"Error creating bill: {str(e)}")


if __name__ == "__main__":
    main()
