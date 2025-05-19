from datetime import datetime
from typing import List, Dict

def build_quickbooks_bill(
        bill_data: Dict,
        vendor_id: str,
        account_id: str,
        txn_date: str = None,
)
    """
    Transforms parsed bill data into a QuickBooks-compatible format.
    """
    if txn_date is None:
        txn_date = datetime.now().strftime('%Y-%m-%d')
    
    qb_line_items = []
    for item in bill_data["line_items"]:
        try:
            amount = float(item["amount"])
        except (ValueError, TypeError):
            amount = 0.0

        line = {
            
        }