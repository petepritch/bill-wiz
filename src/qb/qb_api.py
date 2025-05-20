"""
QuickBooks API Module

This module provides functions to interact with QuickBooks API endpoints.
"""

import streamlit as st
from .qb_auth import make_api_request, run_query


@st.cache_data(ttl=3600)  # Cache for 1 hour
def get_vendors():
    """Get all active vendors from QuickBooks"""
    query = (
        "SELECT Id, DisplayName, Active FROM Vendor WHERE Active = true MAXRESULTS 1000"
    )
    vendors_response = run_query(query)

    if vendors_response and vendors_response.status_code == 200:
        vendors_data = vendors_response.json()
        if (
            "QueryResponse" in vendors_data
            and "Vendor" in vendors_data["QueryResponse"]
        ):
            vendors = vendors_data["QueryResponse"]["Vendor"]
            return [
                (vendor.get("DisplayName", "Unnamed Vendor"), vendor.get("Id", ""))
                for vendor in vendors
            ]

    return []


def get_accounts(account_type=None):
    """Get accounts from QuickBooks, optionally filtered by type"""
    if account_type:
        query = f"SELECT Id, Name, AccountType, AccountSubType FROM Account WHERE AccountType = '{account_type}' AND Active = true"
    else:
        query = "SELECT Id, Name, AccountType, AccountSubType FROM Account WHERE Active = true"

    accounts_response = run_query(query)

    if accounts_response and accounts_response.status_code == 200:
        accounts_data = accounts_response.json()
        if (
            "QueryResponse" in accounts_data
            and "Account" in accounts_data["QueryResponse"]
        ):
            accounts = accounts_data["QueryResponse"]["Account"]
            return [
                (account.get("Name", "Unnamed Account"), account.get("Id", ""))
                for account in accounts
            ]

    return []


def get_vendor_by_id(vendor_id):
    """Get detailed vendor information by ID"""
    if not vendor_id:
        return None

    response = make_api_request(f"vendor/{vendor_id}")
    if response and response.status_code == 200:
        return response.json().get("Vendor")

    return None


def create_bill(vendor_id, invoice_number, bill_data, account_id="7"):
    """Create a bill in QuickBooks

    Args:
        vendor_id (str): QuickBooks Vendor ID
        invoice_number (str): Invoice number from the bill
        bill_data (DataFrame): DataFrame containing bill line items
        account_id (str): Default expense account ID

    Returns:
        Response object from QuickBooks API
    """
    import pandas as pd

    # Format bill data for QuickBooks API
    today = pd.Timestamp.now().strftime("%Y-%m-%d")

    # Prepare line items
    line_items = []
    for _, row in bill_data.iterrows():
        line_items.append(
            {
                "DetailType": "AccountBasedExpenseLineDetail",
                "Amount": float(row["Importe"]),
                "Description": row.get("Descripcion", ""),
                "AccountBasedExpenseLineDetail": {
                    "AccountRef": {"value": account_id},
                    "TaxCodeRef": {"value": "TAX"},
                },
            }
        )

    # Create bill object
    bill = {
        "VendorRef": {"value": vendor_id},
        "Line": line_items,
        "DocNumber": invoice_number,
        "TxnDate": today,
    }

    # Send to QuickBooks
    response = make_api_request("bill", method="POST", data=bill)
    return response
