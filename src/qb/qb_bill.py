"""
QuickBooks Bill Builder Functions

This module provides functions to build and create bills in QuickBooks,
with support for both inventory and expense items.
"""

from datetime import datetime
from typing import List, Dict, Optional, Union
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


def build_quickbooks_bill(
    bill_data: Dict,
    vendor_id: str,
    account_id: str = None,
    txn_date: str = None,
    items_map: Dict = None,
    use_item_based_expense: bool = True,
    default_expense_account_id: str = None,
) -> Dict:
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
        Dict: A QuickBooks-compatible bill object
    """
    if txn_date is None:
        txn_date = datetime.now().strftime("%Y-%m-%d")

    invoice_number = bill_data.get("invoice_number", "")

    qb_line_items = []
    missing_items = []

    # Get all items once if we're using item-based expenses and don't have a map
    if use_item_based_expense and not items_map:
        items_map = {}
        all_items = get_all_items()
        for name, id in all_items:
            items_map[name.lower()] = id

            # Add some common variations to improve matching
            clean_name = "".join(c for c in name.lower() if c.isalnum())
            if clean_name != name.lower():
                items_map[clean_name] = id

    for item in bill_data["line_items"]:
        try:
            amount = float(item["amount"])
        except (ValueError, TypeError):
            amount = 0.0

        if amount <= 0:
            continue  # Skip zero or negative amounts

        product_name = item.get("product", "No description")

        if use_item_based_expense:
            # Try to find the item in QuickBooks
            item_id = None

            if items_map:
                # First try exact match
                item_id = items_map.get(product_name.lower())

                if not item_id:
                    # Try with clean name (alphanumeric only)
                    clean_name = "".join(c for c in product_name.lower() if c.isalnum())
                    item_id = items_map.get(clean_name)

            if not item_id:
                # Try to find the item by name in QuickBooks
                qb_item = get_item_by_name(product_name)
                if qb_item:
                    item_id = qb_item.get("Id")
                    # Add to our map for future use
                    if items_map is not None:
                        items_map[product_name.lower()] = item_id

            if item_id:
                line = {
                    "DetailType": "ItemBasedExpenseLineDetail",
                    "Amount": amount,
                    "Description": product_name,
                    "ItemBasedExpenseLineDetail": {
                        "ItemRef": {"value": item_id},
                        "Qty": item.get("quantity", 1),
                        "UnitPrice": amount / (item.get("quantity", 1) or 1),
                    },
                }
            else:
                # Fall back to account-based expense if we can't find the item
                missing_items.append(product_name)
                if default_expense_account_id:
                    line = {
                        "DetailType": "AccountBasedExpenseLineDetail",
                        "Amount": amount,
                        "Description": f"{product_name} (Item not found in QuickBooks)",
                        "AccountBasedExpenseLineDetail": {
                            "AccountRef": {"value": default_expense_account_id}
                        },
                    }
                else:
                    # Skip this line if we don't have a default account
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
        qb_bill, missing_items = build_quickbooks_bill(
            bill_data,
            vendor_id,
            account_id,
            txn_date,
            use_item_based_expense=use_item_based_expense,
            default_expense_account_id=default_expense_account_id,
        )

        print(f"DEBUG: bill_data contains {len(bill_data['line_items'])} items")
        print(f"DEBUG: qb_bill contains {len(qb_bill['Line'])} line items")
        for i, item in enumerate(bill_data["line_items"]):
            print(
                f"DEBUG: Item {i}: {item.get('product', 'No name')} - Amount: {item.get('amount', 'No amount')}"
            )

        # Check if we have line items
        if not qb_bill["Line"]:
            return False, "No valid line items found in bill data", missing_items

        response = make_api_request("bill", method="POST", data=qb_bill)

        if response and response.status_code in (200, 201):
            return True, response.json(), missing_items
        else:
            error_msg = "Failed to create bill in QuickBooks"
            if response:
                error_msg += f": {response.text}"
            return False, error_msg, missing_items

    except Exception as e:
        return False, f"Error creating bill: {str(e)}", []
