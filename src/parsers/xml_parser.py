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

logger = logging.getLogger(__name__)

# Resgister namespaces for XML parsing
NAMESPACES = {
    "cfdi": "http://www.sat.gob.mx/cfd/4",
    "xsi": "http://www.w3.org/2001/XMLSchema-instance",
    "cce20": "http://www.sat.gob.mx/ComercioExterior20",
}


def parse_bill(file_path: str) -> Tuple:

    try:
        tree = ET.parse(file_path)
        root = tree.getroot()
        # Extracting invoice number
        invoice_number = root.attrib.get("Folio")

        bill_data = {
            "line_items": [],
        }

        conceptos = root.find("cfdi:Conceptos", NAMESPACES)
        if conceptos is not None:
            for concepto in conceptos.findall("cfdi:Concepto", NAMESPACES):
                line_item = {
                    "product": _extract_sku(concepto.attrib.get("Descripcion")),
                    "sku": _extract_sku(concepto.attrib.get("Descripcion")),
                    "description": concepto.attrib.get("NoIdentificacion"),
                    "quantity": concepto.attrib.get("Cantidad"),
                    "rate": concepto.attrib.get("ValorUnitario"),
                    "amount": concepto.attrib.get("Importe"),
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


def _extract_sku(input_str: str) -> str:

    delimiter = "SKU:"
    if delimiter in input_str:
        return input_str.split(delimiter)[-1].strip()
    return input_str
