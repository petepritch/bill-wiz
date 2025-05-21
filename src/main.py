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

    for _, row in bill_df.iterrows():
        # Extract SKU from the description if possible
        description = row.get("Descripcion", "")
        sku = ""

        # Check if there's a NoIdentificacion field (common in CFDI for product code/SKU)
        if "NoIdentificacion" in row and row["NoIdentificacion"]:
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

        # Get amount and quantity, ensure they're valid numbers
        try:
            amount = float(row.get("Importe", 0))
        except (ValueError, TypeError):
            amount = 0.0

        try:
            quantity = float(row.get("Cantidad", 1))
        except (ValueError, TypeError):
            quantity = 1.0

        # Skip items with zero or negative amounts
        if amount <= 0:
            st.warning(f"Skipping item with zero/negative amount: {description}")
            continue

        # Ensure quantity is at least 1
        if quantity <= 0:
            quantity = 1.0

        item = {
            "product": description
            or "Unnamed Item",  # Ensure we always have a description
            "sku": sku,
            "amount": amount,
            "quantity": quantity,
        }
        line_items.append(item)

    # Debug information
    st.write(f"Formatted {len(line_items)} valid line items from bill data")
    if line_items:
        with st.expander("View Line Items"):
            for i, item in enumerate(line_items):
                st.write(f"Item {i+1}:")
                st.write(f"- Product: {item['product']}")
                st.write(f"- SKU: {item['sku']}")
                st.write(f"- Amount: ${item['amount']:.2f}")
                st.write(f"- Quantity: {item['quantity']}")
    else:
        st.error("No valid line items found in the bill data!")
        # Add a placeholder item to avoid empty bills (optional)
        if st.checkbox("Add placeholder item?"):
            line_items.append(
                {
                    "product": "Default Line Item",
                    "sku": "DEFAULT",
                    "amount": 1.0,
                    "quantity": 1.0,
                }
            )
            st.success("Added placeholder item")

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
