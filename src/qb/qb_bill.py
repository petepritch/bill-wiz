"""
QuickBooks Bill Builder Functions

This module provides functions to build and create bills in QuickBooks,
with support for both inventory and expense items.
"""

from datetime import datetime
from typing import List, Dict, Optional, Union, Tuple
import streamlit as st
from .qb_auth import make_api_request, run_query


def get_item_by_name(item_name: str) -> Optional[Dict]:
    """
    Find a QuickBooks item by name.

    Args:
        item_name (str): The name of the item to search for

    Returns:
        Dict or None: The item data if found, None otherwise
    """
    # Clean the item name for the query (remove special characters)
    clean_name = item_name.replace("'", "").replace('"', "")

    # First try exact match
    query = f"SELECT Id, Name, Type, Description FROM Item WHERE Name = '{clean_name}'"
    response = run_query(query)

    if response and response.status_code == 200:
        data = response.json()
        if (
            "QueryResponse" in data
            and "Item" in data["QueryResponse"]
            and data["QueryResponse"]["Item"]
        ):
            return data["QueryResponse"]["Item"][0]

    # If exact match fails, try a LIKE query
    query = (
        f"SELECT Id, Name, Type, Description FROM Item WHERE Name LIKE '%{clean_name}%'"
    )
    response = run_query(query)

    if response and response.status_code == 200:
        data = response.json()
        if (
            "QueryResponse" in data
            and "Item" in data["QueryResponse"]
            and data["QueryResponse"]["Item"]
        ):
            return data["QueryResponse"]["Item"][0]

    return None


def find_item_by_sku_or_name(name: str, sku: str = None) -> Optional[Dict]:
    """
    Find a QuickBooks item by SKU or name, handling parent-child SKU relationships.

    Args:
        name (str): The name of the item to search for
        sku (str, optional): The SKU to search for

    Returns:
        Dict or None: The item data if found, None otherwise
    """
    # Clean the inputs
    clean_name = name.replace("'", "").replace('"', "")

    if sku:
        # Try exact SKU match first
        query = (
            f"SELECT Id, Name, Type, Description FROM Item WHERE Name LIKE '%{sku}%'"
        )
        response = run_query(query)

        if response and response.status_code == 200:
            data = response.json()
            if "QueryResponse" in data and "Item" in data["QueryResponse"]:
                # Check each returned item to find one with the right pattern
                for item in data["QueryResponse"]["Item"]:
                    item_name = item.get("Name", "")
                    # Look for exact SKU after colon or dash
                    if (
                        f":{sku}" in item_name
                        or f"-{sku}" in item_name
                        or sku in item_name
                    ):
                        return item

                # If no exact pattern match, return the first match
                if data["QueryResponse"]["Item"]:
                    return data["QueryResponse"]["Item"][0]

    # If no match by SKU or no SKU provided, fall back to name search
    return get_item_by_name(clean_name)


@st.cache_data(ttl=3600)
def get_all_items():
    """
    Get all items from QuickBooks.

    Returns:
        List: A list of tuples (name, id) for all items
    """
    query = "SELECT Id, Name, Type FROM Item WHERE Active = true MAXRESULTS 1000"
    response = run_query(query)

    if response and response.status_code == 200:
        data = response.json()
        if "QueryResponse" in data and "Item" in data["QueryResponse"]:
            items = data["QueryResponse"]["Item"]
            return [
                (item.get("Name", "Unnamed Item"), item.get("Id", "")) for item in items
            ]

    return []


@st.cache_data(ttl=3600)
def get_all_items_with_details():
    """
    Get all items from QuickBooks with detailed information including SKUs.

    Returns:
        List: A list of tuples (name, id, sku) for all items
    """
    query = "SELECT Id, Name, SKU, Type FROM Item WHERE Active = true MAXRESULTS 1000"
    response = run_query(query)

    if response and response.status_code == 200:
        data = response.json()
        if "QueryResponse" in data and "Item" in data["QueryResponse"]:
            items = data["QueryResponse"]["Item"]
            return [
                (
                    item.get("Name", "Unnamed Item"),
                    item.get("Id", ""),
                    item.get("SKU", ""),
                )
                for item in items
            ]

    return []


def create_sku_mapping(items_list: List[Tuple[str, str]]) -> Dict[str, str]:
    """
    Create a comprehensive mapping of SKUs to item IDs.
    Handles parent-child SKU formats.

    Args:
        items_list: List of tuples (name, id) for QuickBooks items

    Returns:
        Dict: Mapping of various SKU formats to item IDs
    """
    mapping = {}

    for name, item_id in items_list:
        # Store the full name as a key
        mapping[name.lower()] = item_id

        # Handle parent-child SKU format (parent:child)
        if ":" in name:
            parent_sku, child_sku = name.split(":", 1)

            # Store each component
            mapping[parent_sku.lower()] = item_id
            mapping[child_sku.lower()] = item_id

            # Also store combinations
            if "-" in child_sku:
                child_parts = child_sku.split("-")
                # Store the last part (often a unique identifier)
                mapping[child_parts[-1].lower()] = item_id

                # Store full child part without parent prefix
                child_sku_clean = "".join(c for c in child_sku.lower() if c.isalnum())
                if child_sku_clean != child_sku.lower():
                    mapping[child_sku_clean] = item_id

        # For non-parent-child names, store without special characters too
        clean_name = "".join(c for c in name.lower() if c.isalnum())
        if clean_name != name.lower():
            mapping[clean_name] = item_id

    return mapping


def build_quickbooks_bill(
    bill_data: Dict,
    vendor_id: str,
    account_id: str = None,
    txn_date: str = None,
    items_map: Dict = None,
    use_item_based_expense: bool = True,
    default_expense_account_id: str = None,
) -> Tuple[Dict, List[str]]:
    """
    Transforms parsed bill data into a QuickBooks-compatible format.

    Args:
        bill_data (Dict): The parsed bill data with line items
        vendor_id (str): The QuickBooks Vendor ID
        account_id (str, optional): Default account ID for expenses. Can be None if using item-based expenses.
        txn_date (str, optional): Transaction date in YYYY-MM-DD format. Defaults to today.
        items_map (Dict, optional): A mapping of product names to QuickBooks Item IDs. If provided,
                                   the function will use this instead of querying QuickBooks.
        use_item_based_expense (bool): Whether to use ItemBasedExpenseLineDetail (True) or
                                      AccountBasedExpenseLineDetail (False)
        default_expense_account_id (str, optional): Default expense account ID to use if an item can't be found
                                                   and we're using item-based expenses

    Returns:
        Tuple: (Dict, List[str]) - A QuickBooks-compatible bill object and a list of missing items
    """
    if txn_date is None:
        txn_date = datetime.now().strftime("%Y-%m-%d")

    invoice_number = bill_data.get("invoice_number", "")

    qb_line_items = []
    missing_items = []

    # Get all items once if we're using item-based expenses and don't have a map
    if use_item_based_expense and not items_map:
        all_items = get_all_items()
        items_map = create_sku_mapping(all_items)

    # Debug: Check what we have in bill_data
    st.write(f"Processing bill with {len(bill_data.get('line_items', []))} line items")

    for item in bill_data.get("line_items", []):
        try:
            amount = float(item.get("amount", 0))
        except (ValueError, TypeError):
            amount = 0.0

        if amount <= 0:
            st.write(
                f"Skipping item with zero/negative amount: {item.get('product', 'Unknown')}"
            )
            continue  # Skip zero or negative amounts

        product_name = item.get("product", "No description")
        sku = item.get("sku", "")

        quantity = 1.0
        try:
            quantity = float(item.get("quantity", 1))
        except (ValueError, TypeError):
            quantity = 1.0

        # Ensure quantity is at least 1
        if quantity <= 0:
            quantity = 1.0

        if use_item_based_expense:
            # Try to find the item in QuickBooks
            item_id = None

            if items_map:
                # Debug
                st.write(f"Trying to match item: {product_name}, SKU: {sku}")

                # Try matching with different approaches
                match_attempts = [
                    # First try exact matches
                    product_name.lower(),  # Full product name
                    sku.lower() if sku else None,  # Exact SKU
                ]

                # Add variant matches
                if sku:
                    # Handle SKU parts
                    if "-" in sku:
                        match_attempts.append(
                            sku.split("-")[-1].lower()
                        )  # Last part of SKU

                    # Handle SKU without special chars
                    clean_sku = "".join(c for c in sku.lower() if c.isalnum())
                    if clean_sku != sku.lower():
                        match_attempts.append(clean_sku)

                # Try clean product name
                clean_name = "".join(c for c in product_name.lower() if c.isalnum())
                if clean_name != product_name.lower():
                    match_attempts.append(clean_name)

                # Try each matching attempt
                for attempt in match_attempts:
                    if attempt is not None and attempt in items_map:
                        item_id = items_map[attempt]
                        st.write(f"✅ Matched using: {attempt}")
                        break

            if not item_id:
                # Try to find the item by name or SKU in QuickBooks
                st.write(
                    f"No match in mapping, trying direct QuickBooks query for {sku}"
                )
                qb_item = find_item_by_sku_or_name(product_name, sku)
                if qb_item:
                    item_id = qb_item.get("Id")
                    # Add to our map for future use
                    if items_map is not None and sku:
                        items_map[sku.lower()] = item_id
                    st.write(
                        f"✅ Found via direct query: {qb_item.get('Name', 'Unknown')}"
                    )

            if item_id:
                line = {
                    "DetailType": "ItemBasedExpenseLineDetail",
                    "Amount": amount,
                    "Description": product_name,
                    "ItemBasedExpenseLineDetail": {
                        "ItemRef": {"value": item_id},
                        "Qty": quantity,
                        "UnitPrice": amount / quantity if quantity else amount,
                    },
                }
                st.write(f"Added item with ID: {item_id}")
            else:
                # Fall back to account-based expense if we can't find the item
                missing_items.append(product_name)
                st.write(f"❌ Could not find item: {product_name}, SKU: {sku}")

                if default_expense_account_id:
                    line = {
                        "DetailType": "AccountBasedExpenseLineDetail",
                        "Amount": amount,
                        "Description": f"{product_name} (Item not found in QuickBooks)",
                        "AccountBasedExpenseLineDetail": {
                            "AccountRef": {"value": default_expense_account_id}
                        },
                    }
                    st.write(
                        f"Using default expense account: {default_expense_account_id}"
                    )
                else:
                    # Skip this line if we don't have a default account
                    st.write("No default expense account provided, skipping item")
                    continue
        else:
            # Use account-based expense
            line = {
                "DetailType": "AccountBasedExpenseLineDetail",
                "Amount": amount,
                "Description": product_name,
                "AccountBasedExpenseLineDetail": {"AccountRef": {"value": account_id}},
            }

        qb_line_items.append(line)

    qb_bill = {
        "VendorRef": {"value": vendor_id},
        "TxnDate": txn_date,
        "Line": qb_line_items,
    }

    # Add invoice number if available
    if invoice_number:
        qb_bill["DocNumber"] = invoice_number

    st.write(f"Created bill with {len(qb_line_items)} line items")
    return qb_bill, missing_items


def create_bill(
    bill_data: Dict,
    vendor_id: str,
    account_id: str = None,
    txn_date: str = None,
    use_item_based_expense: bool = True,
    default_expense_account_id: str = None,
) -> Dict:
    """
    Creates a bill in QuickBooks.

    Args:
        bill_data (Dict): The parsed bill data
        vendor_id (str): The QuickBooks Vendor ID
        account_id (str, optional): Default account ID for expenses
        txn_date (str, optional): Transaction date in YYYY-MM-DD format
        use_item_based_expense (bool): Whether to use item-based expenses
        default_expense_account_id (str, optional): Default expense account ID

    Returns:
        Tuple: (success, response_or_error, missing_items)
            - success (bool): Whether the bill was created successfully
            - response_or_error: The API response on success, error message on failure
            - missing_items (list): List of items that couldn't be found in QuickBooks
    """
    try:
        # DETAILED DEBUGGING: Show the structure of the bill data
        st.write("## Bill Data Inspection")
        st.write(f"Invoice Number: {bill_data.get('invoice_number', 'None')}")
        st.write(f"Number of line items: {len(bill_data.get('line_items', []))}")

        # Show the first few line items for inspection
        if bill_data.get("line_items"):
            st.write("Sample of line items:")
            for i, item in enumerate(bill_data["line_items"][:3]):  # Show first 3
                st.write(f"Item {i+1}:")
                for key, value in item.items():
                    st.write(f"- {key}: {value} (type: {type(value).__name__})")
        else:
            st.error("⚠️ No line items found in bill data!")

        # CRITICAL FIX: Ensure we have some line items with positive amounts
        valid_items = []
        for item in bill_data.get("line_items", []):
            try:
                amount = float(item.get("amount", 0))
                if amount > 0:
                    valid_items.append(item)
                    st.write(
                        f"✅ Valid item: {item.get('product', 'Unnamed')} - Amount: ${amount}"
                    )
                else:
                    st.warning(
                        f"⚠️ Invalid amount ({amount}) for {item.get('product', 'Unnamed')}"
                    )
            except (ValueError, TypeError) as e:
                st.error(
                    f"Error converting amount for {item.get('product', 'Unnamed')}: {str(e)}"
                )

        if not valid_items:
            st.error("No valid line items with positive amounts!")
            # For debugging purposes, create a placeholder item
            if st.checkbox("Add placeholder for debugging?"):
                placeholder = {
                    "product": "DEBUG PLACEHOLDER",
                    "amount": 1.0,
                    "quantity": 1.0,
                    "sku": "DEBUG",
                }
                valid_items.append(placeholder)
                st.success("Added placeholder item for debugging")
                # Update the bill_data
                bill_data["line_items"] = valid_items

        # Build the QuickBooks bill
        qb_bill, missing_items = build_quickbooks_bill(
            bill_data,
            vendor_id,
            account_id,
            txn_date,
            use_item_based_expense=use_item_based_expense,
            default_expense_account_id=default_expense_account_id,
        )

        # Check if we have line items
        if not qb_bill["Line"]:
            st.error("No valid line items found in bill data")
            return False, "No valid line items found in bill data", missing_items

        # Make the API request
        st.write(
            f"Making API request to create bill with {len(qb_bill['Line'])} line items..."
        )
        response = make_api_request("bill", method="POST", data=qb_bill)

        if response and response.status_code in (200, 201):
            return True, response.json(), missing_items
        else:
            error_msg = "Failed to create bill in QuickBooks"
            if response:
                error_msg += f": {response.text}"
            return False, error_msg, missing_items

    except Exception as e:
        st.exception(f"Error creating bill: {str(e)}")
        return False, f"Error creating bill: {str(e)}", []
