"""
Servicio Google Sheets de DocScan AR
=======================================
Usa gspread + Service Account para leer y escribir en el spreadsheet.
Las credenciales se pasan como JSON en GOOGLE_CREDENTIALS_JSON
(toda la variable se guarda como string en Railway / .env).
"""
import os
import json
import tempfile
from datetime import datetime
from typing import Optional

import gspread
from google.oauth2.service_account import Credentials

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# ---------------------------------------------------------------------------
# Cabeceras por tipo de documento
# ---------------------------------------------------------------------------

HEADERS = {
    "FACTURAS": [
        "Fecha Registro",
        "Fecha Doc.",
        "Tipo",
        "Número",
        "Proveedor",
        "CUIT",
        "Subtotal",
        "IVA %",
        "IVA $",
        "Total",
        "CAE",
        "Venc. CAE",
        "Observaciones",
    ],
    "REMITOS": [
        "Fecha Registro",
        "Fecha Doc.",
        "Orden de Salida",
        "Pack Nº",
        "Origen",
        "Dirección Origen",
        "Ciudad Origen",
        "Tel. Origen",
        "Destinatario",
        "Dirección Destino",
        "Ciudad Destino",
        "Tel. Destino",
        "Artículos",
        "Peso Total (kg)",
        "Observaciones",
    ],
    "TICKETS": [
        "Fecha Registro",
        "Fecha Doc.",
        "Comercio",
        "Concepto",
        "Categoría",
        "Monto",
        "Observaciones",
    ],
}

# Mapeo tipo → nombre hoja
SHEET_MAP = {
    "FACTURA": "FACTURAS",
    "REMITO":  "REMITOS",
    "TICKET":  "TICKETS",
}


# ---------------------------------------------------------------------------
# Client factory
# ---------------------------------------------------------------------------

def _get_client() -> gspread.Client:
    creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON", "")
    if creds_json:
        creds_dict = json.loads(creds_json)
        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    elif os.path.exists("credentials.json"):
        creds = Credentials.from_service_account_file("credentials.json", scopes=SCOPES)
    else:
        raise RuntimeError("No se encontraron credenciales de Google. Definí GOOGLE_CREDENTIALS_JSON.")
    return gspread.authorize(creds)


def _get_worksheet(spreadsheet, sheet_name: str) -> gspread.Worksheet:
    """Obtiene o crea la hoja y se asegura que tenga cabeceras."""
    try:
        ws = spreadsheet.worksheet(sheet_name)
    except gspread.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=sheet_name, rows=2000, cols=20)

    # Verificar / crear cabeceras
    headers = HEADERS.get(sheet_name, [])
    if headers:
        existing = ws.row_values(1)
        if not existing:
            ws.append_row(headers, value_input_option="USER_ENTERED")

    return ws


# ---------------------------------------------------------------------------
# Guardar registro
# ---------------------------------------------------------------------------

def save_to_sheet(data: dict, doc_type: str) -> dict:
    """
    Guarda `data` en la hoja correspondiente al `doc_type`.
    Devuelve {'success': True, 'row': N} o {'success': False, 'error': '...'}.
    """
    try:
        client = _get_client()
        spreadsheet_id = os.environ.get("GOOGLE_SPREADSHEET_ID", "")
        if not spreadsheet_id:
            raise RuntimeError("GOOGLE_SPREADSHEET_ID no configurado.")

        spreadsheet = client.open_by_key(spreadsheet_id)
        sheet_name = SHEET_MAP.get(doc_type.upper(), "TICKETS")
        ws = _get_worksheet(spreadsheet, sheet_name)

        now = datetime.now().strftime("%d/%m/%Y %H:%M")

        if sheet_name == "FACTURAS":
            row = [
                now,
                data.get("fecha", ""),
                data.get("tipo_comprobante", ""),
                data.get("numero", ""),
                data.get("proveedor", ""),
                data.get("cuit", ""),
                data.get("subtotal", ""),
                data.get("iva_porcentaje", ""),
                data.get("iva_monto", ""),
                data.get("total", ""),
                data.get("cae", ""),
                data.get("vencimiento_cae", ""),
                data.get("observaciones", ""),
            ]
        elif sheet_name == "REMITOS":
            row = [
                now,
                data.get("fecha", ""),
                data.get("orden_salida", ""),
                data.get("pack", ""),
                data.get("origen_nombre", ""),
                data.get("origen_direccion", ""),
                data.get("origen_ciudad", ""),
                data.get("origen_telefono", ""),
                data.get("destinatario", ""),
                data.get("destino_direccion", ""),
                data.get("destino_ciudad", ""),
                data.get("destino_telefono", ""),
                data.get("articulos", ""),
                data.get("peso_total", ""),
                data.get("observaciones", ""),
            ]
        else:  # TICKETS
            row = [
                now,
                data.get("fecha", ""),
                data.get("comercio", ""),
                data.get("concepto", ""),
                data.get("categoria", ""),
                data.get("monto", ""),
                data.get("observaciones", ""),
            ]

        ws.append_row(row, value_input_option="USER_ENTERED")
        total_rows = len(ws.get_all_values())
        return {"success": True, "row": total_rows}

    except Exception as e:
        print(f"[sheets_service] Error: {e}")
        return {"success": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Obtener registros recientes
# ---------------------------------------------------------------------------

def get_recent_records(doc_type: str, limit: int = 30) -> list[dict]:
    """Devuelve los últimos `limit` registros de la hoja, en orden descendente."""
    try:
        client = _get_client()
        spreadsheet_id = os.environ.get("GOOGLE_SPREADSHEET_ID", "")
        if not spreadsheet_id:
            return []

        spreadsheet = client.open_by_key(spreadsheet_id)
        sheet_name = SHEET_MAP.get(doc_type.upper(), "TICKETS")

        try:
            ws = spreadsheet.worksheet(sheet_name)
        except gspread.WorksheetNotFound:
            return []

        records = ws.get_all_records()
        # Más recientes primero
        return list(reversed(records[-limit:]))

    except Exception as e:
        print(f"[sheets_service] Error al leer registros: {e}")
        return []
