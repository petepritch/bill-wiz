"""
QuickBooks Bill Builder Functions

This module provides functions to build and create bills in QuickBooks,
with support for both inventory and expense items.
"""

from datetime import datetime
from typing import List, Dict, Optional, Union, Tuple
import streamlit as st
from .qb_auth import make_api_request, run_query


def create_bill(
    bill_data: Dict,
    vendor_id: str,
    account_id: str = None,
    txn_date: str = None,
    use_item_based_expense: bool = True,
    default_expense_account_id: str = None,
) -> Tuple[bool, Dict, List[str]]:
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
            return False, "No line items found in bill data", []

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
            else:
                return False, "No valid line items with positive amounts", []

        # Build the QuickBooks bill
        try:
            qb_bill, missing_items = build_quickbooks_bill(
                bill_data,
                vendor_id,
                account_id,
                txn_date,
                use_item_based_expense=use_item_based_expense,
                default_expense_account_id=default_expense_account_id,
            )
        except Exception as e:
            st.exception(f"Error in build_quickbooks_bill: {str(e)}")
            return False, f"Error in build_quickbooks_bill: {str(e)}", []

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
    # CRITICAL FIX: Check for empty inputs to prevent infinite loops
    if not name and not sku:
        st.warning("Both name and SKU are empty, cannot search for item")
        return None

    # Clean the inputs
    clean_name = name.replace("'", "").replace('"', "") if name else ""

    # Use cached results to prevent repetitive queries
    # Create a simple cache key
    cache_key = f"{clean_name}:{sku if sku else ''}"

    # Check if we've already searched for this item
    # We'll use st.session_state to store our cache
    if "item_cache" not in st.session_state:
        st.session_state.item_cache = {}

    if cache_key in st.session_state.item_cache:
        st.write(f"Using cached result for '{cache_key}'")
        return st.session_state.item_cache[cache_key]

    # Check if SKU is provided and not empty
    if sku and sku.strip():
        # Try exact SKU match
        query = (
            f"SELECT Id, Name, Type, Description FROM Item WHERE Name LIKE '%{sku}%'"
        )
        try:
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
                            # Cache this result
                            st.session_state.item_cache[cache_key] = item
                            return item

                    # If no exact pattern match, return the first match
                    if data["QueryResponse"]["Item"]:
                        first_item = data["QueryResponse"]["Item"][0]
                        # Cache this result
                        st.session_state.item_cache[cache_key] = first_item
                        return first_item
        except Exception as e:
            st.error(f"Error querying by SKU: {str(e)}")

    # If SKU search failed or no SKU provided, try name search if name isn't empty
    if clean_name:
        try:
            result = get_item_by_name(clean_name)
            # Cache this result
            st.session_state.item_cache[cache_key] = result
            return result
        except Exception as e:
            st.error(f"Error in get_item_by_name: {str(e)}")

    # No match found
    st.session_state.item_cache[cache_key] = None
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

    st.write(f"Creating SKU mapping from {len(items_list)} items")

    for name, item_id in items_list:
        # Store the full name as a key
        mapping[name.lower()] = item_id
        st.write(f"Added mapping: '{name.lower()}' -> {item_id}")

        # Handle parent-child SKU format (parent:child)
        if ":" in name:
            parent_sku, child_sku = name.split(":", 1)

            # Store each component
            mapping[parent_sku.lower()] = item_id
            mapping[child_sku.lower()] = item_id
            st.write(f"Added parent mapping: '{parent_sku.lower()}' -> {item_id}")
            st.write(f"Added child mapping: '{child_sku.lower()}' -> {item_id}")

            # Also store combinations
            if "-" in child_sku:
                child_parts = child_sku.split("-")
                # Store the last part (often a unique identifier)
                mapping[child_parts[-1].lower()] = item_id
                # Store the first part (often the parent category)
                mapping[child_parts[0].lower()] = item_id
                st.write(
                    f"Added child part mapping: '{child_parts[-1].lower()}' -> {item_id}"
                )
                st.write(
                    f"Added child first part mapping: '{child_parts[0].lower()}' -> {item_id}"
                )

                # Store full child part without parent prefix
                child_sku_clean = "".join(c for c in child_sku.lower() if c.isalnum())
                if child_sku_clean != child_sku.lower():
                    mapping[child_sku_clean] = item_id
                    st.write(
                        f"Added clean child mapping: '{child_sku_clean}' -> {item_id}"
                    )

        # For non-parent-child names, store without special characters too
        clean_name = "".join(c for c in name.lower() if c.isalnum())
        if clean_name != name.lower():
            mapping[clean_name] = item_id
            st.write(f"Added clean name mapping: '{clean_name}' -> {item_id}")

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
    Returns a tuple containing the QB bill structure and a list of items not found.
    """
    if txn_date is None:
        txn_date = datetime.now().strftime("%Y-%m-%d")

    invoice_number = bill_data.get("invoice_number", "")

    qb_line_items = []
    missing_items = []

    # CRITICAL FIX: Ensure we have a valid bill_data with line_items
    if bill_data is None or not isinstance(bill_data, dict):
        st.error("Invalid bill_data: None or not a dictionary")
        # Return empty bill structure and missing items to avoid unpacking error
        return {"VendorRef": {"value": vendor_id}, "TxnDate": txn_date, "Line": []}, [
            "Invalid bill data"
        ]

    if "line_items" not in bill_data or not bill_data["line_items"]:
        st.error("No line items found in bill_data")
        # Return empty bill structure and missing items to avoid unpacking error
        return {"VendorRef": {"value": vendor_id}, "TxnDate": txn_date, "Line": []}, [
            "No line items found"
        ]

    # Get all items once if we're using item-based expenses and don't have a map
    if use_item_based_expense and not items_map:
        try:
            all_items = get_all_items()
            if not all_items:
                st.warning("No items found in QuickBooks!")
                # Still continue with empty items map
                items_map = {}
            else:
                items_map = (
                    create_sku_mapping(all_items)
                    if "create_sku_mapping" in globals()
                    else {}
                )
                if not items_map and all_items:
                    # Simple fallback if create_sku_mapping isn't available
                    items_map = {item[0].lower(): item[1] for item in all_items}
        except Exception as e:
            st.error(f"Error getting QuickBooks items: {str(e)}")
            # Continue with empty items map
            items_map = {}

    # Debug: Check what we have in bill_data
    st.write(f"Processing bill with {len(bill_data.get('line_items', []))} line items")

    # CRITICAL FIX: Use enumerate to track the index and avoid getting stuck
    for index, item in enumerate(bill_data.get("line_items", [])):
        st.write(
            f"--- Processing item {index + 1}/{len(bill_data.get('line_items', []))} ---"
        )

        try:
            amount = float(item.get("amount", 0))
        except (ValueError, TypeError):
            st.warning(
                f"Item {index + 1}: Invalid amount format - {item.get('amount')}"
            )
            amount = 0.0

        if amount <= 0:
            st.warning(
                f"Item {index + 1}: Skipping item with zero/negative amount: {item.get('product', 'Unknown')}"
            )
            continue  # Skip zero or negative amounts

        # CRITICAL: Get product field in QuickBooks format (parent:sku)
        product_name = item.get("product", "")
        # Get specific SKU
        sku = item.get("sku", "")
        # Get description (which is NoIdentificacion in your case)
        description = item.get("description", "")

        # Debug information about the current item
        st.write(
            f"Item {index + 1}: QB Product: '{product_name}', SKU: '{sku}', Description: '{description}', Amount: {amount}"
        )

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
                st.write(
                    f"Item {index + 1}: Trying to match item: {product_name}, SKU: {sku}"
                )

                # Try matching with different approaches
                match_attempts = []

                # First try the exact QB product format (parent:sku)
                if product_name:
                    match_attempts.append(product_name.lower())  # Exact match

                # Then try different forms of the SKU
                if sku:
                    match_attempts.append(sku.lower())  # Exact SKU

                    # If SKU has parent-child format with dash (e.g., 24fauxbois-sharbor)
                    if "-" in sku:
                        parent = sku.split("-")[0].lower()
                        child = sku.split("-")[1].lower()

                        # Try parent:sku format
                        match_attempts.append(f"{parent}:{sku}".lower())

                        # Try parent component
                        match_attempts.append(parent)

                        # Try child component
                        match_attempts.append(child)

                    # Try alphanumeric only
                    sku_clean = "".join(c for c in sku.lower() if c.isalnum())
                    if sku_clean != sku.lower():
                        match_attempts.append(sku_clean)

                # Show attempts for debugging
                st.write(f"Item {index + 1}: Will try matches: {match_attempts}")

                # Try each matching attempt
                for attempt in match_attempts:
                    if attempt and attempt in items_map:
                        item_id = items_map[attempt]
                        st.write(f"Item {index + 1}: ✅ Matched using: {attempt}")
                        break

            if not item_id:
                # Try direct QuickBooks search
                st.write(
                    f"Item {index + 1}: No match in mapping, trying direct QuickBooks query"
                )

                # First try product_name (which should be in parent:sku format)
                if product_name:
                    qb_item = find_item_by_sku_or_name(product_name, "")
                    if qb_item:
                        item_id = qb_item.get("Id")
                        st.write(
                            f"Item {index + 1}: ✅ Found via product name query: {qb_item.get('Name', 'Unknown')}"
                        )

                # Then try the SKU if product name search failed
                if not item_id and sku:
                    qb_item = find_item_by_sku_or_name("", sku)
                    if qb_item:
                        item_id = qb_item.get("Id")
                        st.write(
                            f"Item {index + 1}: ✅ Found via SKU query: {qb_item.get('Name', 'Unknown')}"
                        )

                # Lastly, try with the description/ID if provided
                if not item_id and description:
                    qb_item = find_item_by_sku_or_name(description, "")
                    if qb_item:
                        item_id = qb_item.get("Id")
                        st.write(
                            f"Item {index + 1}: ✅ Found via description query: {qb_item.get('Name', 'Unknown')}"
                        )

    qb_bill = {
        "VendorRef": {"value": vendor_id},
        "TxnDate": txn_date,
        "Line": qb_line_items,
    }

    # Add invoice number if available
    if invoice_number:
        qb_bill["DocNumber"] = invoice_number

    st.write(
        f"Created bill with {len(qb_line_items)} line items out of {len(bill_data.get('line_items', []))} total items"
    )

    # CRITICAL: Always return a tuple with the bill and missing items
    return qb_bill, missing_items
