"""
XML Parser for QuickBooks Bill Automation

This module handles parsing XML files containing bill information
into structured data ready for QuickBooks API integration.
"""

import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import logging
import pandas as pd
import re

logger = logging.getLogger(__name__)

# Register namespaces for XML parsing
NAMESPACES = {
    "cfdi": "http://www.sat.gob.mx/cfd/4",
    "xsi": "http://www.w3.org/2001/XMLSchema-instance",
    "cce20": "http://www.sat.gob.mx/ComercioExterior20",
}


def parse_bill(file_path: str) -> Tuple:
    """
    Parse a CFDI XML bill file.

    Args:
        file_path: Path to the XML file

    Returns:
        Tuple containing invoice number, DataFrame of line items, and raw bill data
    """
    try:
        tree = ET.parse(file_path)
        root = tree.getroot()
        # Extracting invoice number
        invoice_number = root.attrib.get("Folio", "")

        # Log basic document info for debugging
        logging.info(f"Processing invoice #{invoice_number}")

        bill_data = {
            "line_items": [],
        }

        conceptos = root.find("cfdi:Conceptos", NAMESPACES)
        if conceptos is not None:
            for concepto in conceptos.findall("cfdi:Concepto", NAMESPACES):
                # Extract all relevant fields from the XML
                full_description = concepto.attrib.get("Descripcion", "")
                product_id = concepto.attrib.get(
                    "NoIdentificacion", ""
                )  # This is the NoIdentificacion
                cantidad = concepto.attrib.get("Cantidad", "1.0000")
                valor_unitario = concepto.attrib.get("ValorUnitario", "0.0000")
                importe = concepto.attrib.get("Importe", "0.0000")

                # Extract the SKU from the description
                sku = ""
                parent_sku = ""

                if "SKU:" in full_description:
                    # Extract the SKU part after "SKU:"
                    sku_part = full_description.split("SKU:")[1].strip()
                    # The SKU is the first word after "SKU:"
                    sku = sku_part.split()[0] if " " in sku_part else sku_part

                    # Extract parent SKU if possible (assuming format like 24fauxbois-sharbor)
                    if "-" in sku:
                        parent_sku = sku.split("-")[0]
                    else:
                        parent_sku = sku

                    # Format QuickBooks PRODUCT/SERVICE field as parent:sku
                    qb_product_service = f"{parent_sku}:{sku}"
                else:
                    # If no SKU in description, use product_id as fallback
                    qb_product_service = product_id

                line_item = {
                    "product": qb_product_service,  # Format as "parent:sku" for QuickBooks matching
                    "sku": sku,  # The actual SKU (e.g., "24fauxbois-sharbor")
                    "parent_sku": parent_sku,  # The parent SKU (e.g., "24fauxbois")
                    "product_id": product_id,  # The NoIdentificacion value
                    "description": product_id,  # Use NoIdentificacion as description for QB matching
                    "full_description": full_description,  # Save the full description
                    "Cantidad": cantidad,
                    "ValorUnitario": valor_unitario,
                    "Importe": importe,
                    "quantity": cantidad,
                    "rate": valor_unitario,
                    "amount": importe,
                }
                bill_data["line_items"].append(line_item)

        else:
            logging.error("No 'cfdi:Conceptos' found in the XML file.")

        bill_df = pd.DataFrame(bill_data["line_items"])

        return invoice_number, bill_df, bill_data

    except FileNotFoundError:
        logging.error(f"File not found: {file_path}")
        raise FileNotFoundError(f"File not found: {file_path}")
    except ET.ParseError as e:
        logging.error(f"Invalid XML format: {str(e)}")
        raise ET.ParseError(f"Invalid XML format: {str(e)}")


def extract_sku_components(sku_str: str) -> Tuple[str, str]:
    """
    Extract parent and specific SKU components.

    Args:
        sku_str: The full SKU string

    Returns:
        Tuple of (parent_sku, full_sku)
    """
    if not sku_str:
        return "", ""

    # If it has a dash (e.g., "24fauxbois-sharbor"), split it
    if "-" in sku_str:
        parts = sku_str.split("-", 1)
        return parts[0], sku_str

    # Otherwise, the parent is the same as the full SKU
    return sku_str, sku_str
