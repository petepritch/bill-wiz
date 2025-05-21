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

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
)

from parsers.xml_parser import parse_bill
from qb.qb_auth import check_qb_connection
from qb.qb_api import get_vendors, get_accounts
from qb.qb_bill import (
    get_all_items,
    build_quickbooks_bill,
    create_sku_mapping,
    find_item_by_sku_or_name,
)

st.set_page_config(page_title="Mama's Bill Wizard", page_icon="📊", layout="wide")


def format_bill_data(invoice_number, bill_df):
    """Format bill dataframe into the structure expected by the bill builder"""
    line_items = []

    # DEBUGGING: Display the DataFrame schema and sample values
    st.write("DataFrame Info:")
    st.write(f"Columns: {bill_df.columns.tolist()}")
    st.write("First few rows:")
    st.write(bill_df.head())

    # Process each row
    for _, row in bill_df.iterrows():
        # CRITICAL: Extract SKU information for QuickBooks matching
        full_sku = row.get("sku", "")
        parent_sku = row.get("parent_sku", "")
        product_id = row.get("product_id", "")

        # For QuickBooks matching, we need the product in format: "parent_sku:full_sku"
        qb_product = ""

        # If both parent and full SKU are available, format as parent:full
        if parent_sku and full_sku:
            qb_product = f"{parent_sku}:{full_sku}"
            st.write(f"Formatted QB product: {qb_product}")
        # If only full_sku is available
        elif full_sku:
            # If it contains a dash, extract parent component
            if "-" in full_sku:
                parent = full_sku.split("-")[0]
                qb_product = f"{parent}:{full_sku}"
            else:
                qb_product = f"{full_sku}:{full_sku}"
            st.write(f"Derived QB product: {qb_product}")
        # Fallback to the product field
        else:
            qb_product = row.get("product", "")
            st.write(f"Using fallback product: {qb_product}")

        # Get the description - in QB, this is the NoIdentificacion (product_id)
        description = product_id or row.get("description", "")

        # If description is empty, use the full_description field
        if not description and "full_description" in row:
            description = row["full_description"]
            st.write(f"Using full_description as fallback: {description[:30]}...")

        # Get amount with proper conversion
        amount = 0.0
        try:
            # Try Importe first (standard CFDI field)
            if "Importe" in row and row["Importe"]:
                amount = float(row["Importe"])
            # Fallback to amount field
            elif "amount" in row and row["amount"]:
                amount = float(row["amount"])
        except (ValueError, TypeError) as e:
            st.error(f"Could not convert amount: {e}")
            amount = 0.0

        # If amount is still zero, try to search in other columns
        if amount <= 0:
            for col in bill_df.columns:
                if any(term in col.lower() for term in ["amount", "total", "importe"]):
                    try:
                        value = row[col]
                        if isinstance(value, str):
                            value = "".join(c for c in value if c.isdigit() or c == ".")
                        amt = float(value)
                        if amt > 0:
                            amount = amt
                            st.write(f"Found amount {amount} in column {col}")
                            break
                    except (ValueError, TypeError):
                        pass

        # Get quantity
        quantity = 1.0
        try:
            if "Cantidad" in row and row["Cantidad"]:
                quantity = float(row["Cantidad"])
            elif "quantity" in row and row["quantity"]:
                quantity = float(row["quantity"])
        except (ValueError, TypeError):
            quantity = 1.0

        # Make sure quantity is positive
        if quantity <= 0:
            quantity = 1.0

        # DEBUG OUTPUT
        st.write(
            f"Item: QB Product={qb_product}, SKU={full_sku}, ID={product_id}, Amount={amount}, Qty={quantity}"
        )

        # Create the line item with correctly formatted fields for QB matching
        item = {
            "product": qb_product,  # Format as parent:sku for QB matching
            "sku": full_sku,  # The specific SKU
            "description": description,  # Use product_id as description
            "amount": amount,
            "quantity": quantity,
        }

        line_items.append(item)

    # Provide summary
    st.success(f"Successfully created {len(line_items)} line items!")

    return {"invoice_number": invoice_number, "line_items": line_items}


def main():
    """Main application function"""
    st.title("Mama's Bill Wizard")

    if not check_qb_connection():
        return

    col1, col2 = st.columns([1, 1])

    with col1:
        st.subheader("Upload CFDI")
        upload_file = st.file_uploader("Upload your CFDI file", type=["xml"])

        bill_data = None
        if upload_file is not None:
            try:
                invoice_number, bill_df, raw_bill_data = parse_bill(upload_file)

                bill_data = format_bill_data(invoice_number, bill_df)

                st.success(f"Successfully parsed invoice #{invoice_number}")
                st.dataframe(bill_df)
            except Exception as e:
                st.error(f"Error parsing XML file: {str(e)}")
                bill_df = None
                invoice_number = None

    with col2:
        st.subheader("QuickBooks Details")

        vendors = get_vendors()

        if not vendors:
            st.warning("No vendors found in your QuickBooks account.")
        else:
            vendor_names = [name for name, _ in vendors]
            selected_vendor = st.selectbox("Select a Vendor", vendor_names)

            selected_vendor_id = next(
                (id for name, id in vendors if name == selected_vendor), None
            )

            st.subheader("Bill Options")

            bill_date = st.date_input("Bill Date", value=datetime.now())

            use_items = st.checkbox("Use Inventory Items (Recommended)", value=True)

            if use_items:
                st.info(
                    "The system will try to match product descriptions to inventory items in QuickBooks. "
                    "If a match isn't found, it will use the default expense account."
                )

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
                accounts = get_accounts(account_type="Expense")

                if accounts:
                    account_names = [name for name, _ in accounts]
                    selected_account = st.selectbox("Expense Account", account_names)

                    selected_account_id = next(
                        (id for name, id in accounts if name == selected_account), "7"
                    )
                else:
                    selected_account_id = "7"
                    st.warning("No expense accounts found. Using default account.")
            # Add this right after the bill options section in main.py
        with st.expander("Advanced Debugging Options"):
            st.subheader("QuickBooks Item Debugging")

            if st.checkbox("View QuickBooks Items"):
                st.write("Loading items from QuickBooks...")
                all_qb_items = get_all_items()

                st.write(f"Found {len(all_qb_items)} items in QuickBooks")

                # Filter items
                search_term = st.text_input("Filter items (enter SKU or name part)")

                filtered_items = all_qb_items
                if search_term:
                    filtered_items = [
                        (name, id)
                        for name, id in all_qb_items
                        if search_term.lower() in name.lower()
                    ]
                    st.write(
                        f"Found {len(filtered_items)} items matching '{search_term}'"
                    )

                # Display items
                if filtered_items:
                    st.write("Items in QuickBooks:")
                    for name, id in filtered_items[
                        :30
                    ]:  # Limit to prevent overwhelming UI
                        st.write(f"- Name: {name} (ID: {id})")

                    if len(filtered_items) > 30:
                        st.write(f"... and {len(filtered_items) - 30} more items")
                else:
                    st.write("No matching items found")

            # SKU testing section
            if st.checkbox("Test SKU Matching"):
                test_sku = st.text_input("Enter a SKU to test matching")
                if test_sku and st.button("Test Match"):
                    st.write(f"Testing matching for SKU: {test_sku}")

                    # Create SKU mapping
                    all_items = get_all_items()
                    items_map = create_sku_mapping(all_items)

                    # Try different matching approaches
                    match_attempts = [
                        test_sku.lower(),
                        "".join(c for c in test_sku.lower() if c.isalnum()),
                    ]

                    if "-" in test_sku:
                        match_attempts.append(test_sku.split("-")[-1].lower())

                    # Check each match attempt
                    for attempt in match_attempts:
                        if attempt in items_map:
                            item_id = items_map[attempt]
                            # Find the name that matches this ID
                            matching_name = next(
                                (name for name, id in all_items if id == item_id),
                                "Unknown",
                            )
                            st.success(f"✅ Matched using: {attempt}")
                            st.write(f"Item: {matching_name} (ID: {item_id})")
                            break
                    else:
                        st.error(f"❌ No match found for SKU: {test_sku}")

                        # Try direct query
                        st.write("Trying direct QuickBooks query...")
                        qb_item = find_item_by_sku_or_name("", test_sku)
                        if qb_item:
                            st.success(
                                f"✅ Found via direct query: {qb_item.get('Name', 'Unknown')}"
                            )
                            st.write(f"Item ID: {qb_item.get('Id', 'Unknown')}")
                        else:
                            st.error("No match found via direct query either")

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
