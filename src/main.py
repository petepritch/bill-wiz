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
    create_bill,
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

    # CRITICAL FIX: Check for column name variations
    amount_column = None
    amount_column_candidates = [
        "Importe",
        "importe",
        "Amount",
        "amount",
        "Total",
        "total",
        "Valor",
        "valor",
    ]

    for col in amount_column_candidates:
        if col in bill_df.columns:
            amount_column = col
            st.write(f"Found amount column: '{amount_column}'")
            break

    if not amount_column:
        st.error("Could not find amount column! Using direct values from bill data.")

    # Display the first few values of the amount column for debugging
    if amount_column:
        st.write(f"First 5 values in {amount_column} column:")
        for i, val in enumerate(bill_df[amount_column].head()):
            st.write(f"Row {i}: {val} (type: {type(val).__name__})")

    # Process each row
    for _, row in bill_df.iterrows():
        # Extract SKU from the description if possible (same as your original code)
        description = row.get("Descripcion", "")
        sku = ""

        # Check if there's a NoIdentificacion field
        if "NoIdentificacion" in row and row["NoIdentificacion"]:
            sku = row["NoIdentificacion"]
        # Check for "SKU:" pattern
        elif "SKU:" in description:
            sku = description.split("SKU:")[1].split()[0].strip()
        elif "Codigo:" in description or "Código:" in description:
            sku_part = (
                description.split("Codigo:")[1]
                if "Codigo:" in description
                else description.split("Código:")[1]
            )
            sku = sku_part.split()[0].strip()
        elif "[" in description and "]" in description:
            start = description.find("[") + 1
            end = description.find("]", start)
            if end > start:
                sku = description[start:end].strip()
        elif "(" in description and ")" in description:
            start = description.find("(") + 1
            end = description.find(")", start)
            if end > start:
                potential_sku = description[start:end].strip()
                if any(c.isdigit() for c in potential_sku) or len(potential_sku) < 10:
                    sku = potential_sku

        # CRITICAL FIX: Get the amount value, with explicit debugging
        amount = 0.0
        amount_raw = None

        # Try multiple methods to get a valid amount
        if amount_column and amount_column in row:
            amount_raw = row[amount_column]
            st.write(
                f"Raw amount from {amount_column}: {amount_raw} (type: {type(amount_raw).__name__})"
            )

        # Convert the amount to float, handling different formats
        if amount_raw is not None:
            try:
                # Handle string values with currency symbols, commas, etc.
                if isinstance(amount_raw, str):
                    # Remove currency symbols, commas, etc.
                    clean_amount = "".join(
                        c for c in amount_raw if c.isdigit() or c == "." or c == "-"
                    )
                    amount = float(clean_amount) if clean_amount else 0.0
                else:
                    # Try direct conversion
                    amount = float(amount_raw)

                st.write(f"Converted amount: {amount}")
            except (ValueError, TypeError) as e:
                st.error(f"Could not convert amount '{amount_raw}': {e}")
                amount = 0.0

        # CRITICAL FIX: Even if amount conversion failed, try the raw values
        if amount <= 0:
            # Fallback to 'amount' key if it exists and not in column
            try:
                # Find any other column that might have an amount
                for col in bill_df.columns:
                    if (
                        "amount" in col.lower()
                        or "total" in col.lower()
                        or "precio" in col.lower()
                    ):
                        raw_val = row[col]
                        if isinstance(raw_val, (int, float)) and raw_val > 0:
                            amount = float(raw_val)
                            st.write(
                                f"Found positive amount in column '{col}': {amount}"
                            )
                            break
                        elif isinstance(raw_val, str):
                            clean_val = "".join(
                                c
                                for c in raw_val
                                if c.isdigit() or c == "." or c == "-"
                            )
                            try:
                                val = float(clean_val)
                                if val > 0:
                                    amount = val
                                    st.write(
                                        f"Parsed positive amount from column '{col}': {amount}"
                                    )
                                    break
                            except (ValueError, TypeError):
                                pass
            except Exception as e:
                st.error(f"Error in fallback amount processing: {e}")

        # CRITICAL FIX: Force positive amount for debugging if needed
        if amount <= 0:
            # Display warning but temporarily use a placeholder for debugging
            st.warning(f"⚠️ Zero/negative amount ({amount}) for item: {description}")
            st.info("Creating item with placeholder amount of 1.0 for debugging")
            # Use a placeholder amount just for testing/debugging
            amount = 1.0

        # Get quantity with fallbacks for different column names
        quantity = 1.0
        qty_columns = ["Cantidad", "cantidad", "Quantity", "quantity", "Qty", "qty"]
        for col in qty_columns:
            if col in row:
                try:
                    qty = float(row[col])
                    if qty > 0:
                        quantity = qty
                        break
                except (ValueError, TypeError):
                    pass

        # Create the line item
        item = {
            "product": description,
            "sku": sku,
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
