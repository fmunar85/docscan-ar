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
import re
import time
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

import gspread
from google.oauth2.service_account import Credentials
from gspread.exceptions import APIError

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
        "Peso Total (kg)",
        "Observaciones",
        # Columnas de artículo (una fila por artículo)
        "Nº Línea",
        "Artículo (Código)",
        "Descripción",
        "Cant. Enviada",
        "Peso Ind. (kg)",
        "Peso Total Art. (kg)",
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
    "COMP_RESUMEN": [
        "Fecha Registro",
        "Fecha Doc.",
        "Comprobante Nº",
        "Cliente",
        "Dirección",
        "Cantidad Total",
        "Total USD",
        "Grupo",
        "Cant. Grupo",
        "Costo Grupo USD",
        "Observaciones",
    ],
    "COMP_DETALLE": [
        "Fecha Registro",
        "Fecha Doc.",
        "Comprobante Nº",
        "Cliente",
        "Dirección",
        "Grupo",
        "Tipo Línea",
        "Línea Padre",
        "Cantidad",
        "Nombre Artículo",
        "Número Serie",
        "Costo Reposición",
        "Raw OCR",
        "Observaciones",
    ],
}

# Mapeo tipo → nombre hoja
SHEET_MAP = {
    "FACTURA": "FACTURAS",
    "REMITO":  "REMITOS",
    "TICKET":  "TICKETS",
    "COMPROBANTE": "COMP_RESUMEN",
}


def _clean_sheet_title(value: str) -> str:
    """Limpia texto para usarlo como título de pestaña en Google Sheets."""
    if not value:
        return "SIN_NUMERO"
    cleaned = re.sub(r"[\[\]\*\?/\\:]", "_", str(value).strip())
    cleaned = re.sub(r"\s+", "_", cleaned)
    cleaned = re.sub(r"_+", "_", cleaned)
    return cleaned[:70] if cleaned else "SIN_NUMERO"


def _get_doc_number(data: dict, doc_type: str) -> str:
    dt = doc_type.upper()
    if dt == "FACTURA":
        return data.get("numero", "")
    if dt == "REMITO":
        return data.get("orden_salida", data.get("numero", ""))
    if dt == "COMPROBANTE":
        return data.get("comprobante_numero", "")
    return data.get("numero", "")


def _ensure_doc_tab(spreadsheet, data: dict, doc_type: str) -> gspread.Worksheet:
    """Crea/obtiene una pestaña por documento: DOC_<TIPO>_<NUMERO>."""
    numero = _clean_sheet_title(_get_doc_number(data, doc_type))
    tipo = doc_type.upper()
    prefix = "COMP" if tipo == "COMPROBANTE" else tipo
    title = f"DOC_{prefix}_{numero}"

    try:
        return spreadsheet.worksheet(title)
    except gspread.WorksheetNotFound:
        return spreadsheet.add_worksheet(title=title[:99], rows=3000, cols=30)


def _write_doc_snapshot(ws_doc: gspread.Worksheet, headers: list[str], rows: list[list]):
    """Escribe snapshot completo en pestaña por documento (limpia y vuelve a generar)."""
    ws_doc.clear()
    ws_doc.append_row(headers, value_input_option="USER_ENTERED")
    if rows:
        _append_rows_resilient(ws_doc, rows)


def _now_buenos_aires() -> str:
    return datetime.now(ZoneInfo("America/Argentina/Buenos_Aires")).strftime("%d/%m/%Y %H:%M")


def _append_rows_resilient(ws: gspread.Worksheet, rows: list[list], retries: int = 4):
    if not rows:
        return
    wait = 1.0
    for attempt in range(retries):
        try:
            ws.append_rows(rows, value_input_option="USER_ENTERED")
            return
        except APIError as e:
            msg = str(e)
            if "429" in msg and attempt < retries - 1:
                time.sleep(wait)
                wait *= 2
                continue
            raise


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

        now = _now_buenos_aires()

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
            _append_rows_resilient(ws, [row])

            ws_doc = _ensure_doc_tab(spreadsheet, data, "FACTURA")
            headers = HEADERS["FACTURAS"]
            _write_doc_snapshot(ws_doc, headers, [row])

            total_rows = len(ws.get_all_values())
            return {"success": True, "row": total_rows}
        elif sheet_name == "REMITOS":
            # Parsear artículos: una línea por artículo en Sheets
            articulos_raw = data.get("articulos", "")
            lineas = [l.strip() for l in articulos_raw.splitlines() if l.strip()] or [""]

            base = [
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
                data.get("peso_total", ""),
                data.get("observaciones", ""),
            ]

            # Separar cada columna del artículo: NºLinea|Artículo|Descripción|Cant|Peso ind.|Peso
            rows_remito = []
            for linea in lineas:
                partes = [p.strip() for p in linea.split("|")]
                while len(partes) < 6:
                    partes.append("")
                row = base + partes[:6]
                rows_remito.append(row)
                rows_remito.append(row)

            _append_rows_resilient(ws, rows_remito)

            ws_doc = _ensure_doc_tab(spreadsheet, data, "REMITO")
            headers = HEADERS["REMITOS"]
            _write_doc_snapshot(ws_doc, headers, rows_remito)

            total_rows = len(ws.get_all_values())
            return {"success": True, "row": total_rows}

        elif doc_type.upper() == "COMPROBANTE":
            ws_resumen = _get_worksheet(spreadsheet, "COMP_RESUMEN")
            ws_detalle = _get_worksheet(spreadsheet, "COMP_DETALLE")

            # RESUMEN: Grupo | Cant | Costo
            resumen_lineas = [
                l.strip() for l in data.get("comp_resumen_lineas", "").splitlines() if l.strip()
            ] or [""]
            # DETALLE: Grupo | Tipo | LP | Cant | Detalle | Serie | Costo | Raw
            detalle_lineas = [
                l.strip() for l in data.get("comp_detalle_lineas", "").splitlines() if l.strip()
            ] or [""]

            res_base = [
                now,
                data.get("fecha", ""),
                data.get("comprobante_numero", ""),
                data.get("cliente", ""),
                data.get("direccion", ""),
                data.get("cantidad_total", ""),
                data.get("total_usd", ""),
            ]

            rows_resumen = []
            for linea in resumen_lineas:
                partes = [p.strip() for p in linea.split("|")]
                while len(partes) < 3:
                    partes.append("")
                rows_resumen.append(res_base + partes[:3] + [data.get("observaciones", "")])

            _append_rows_resilient(ws_resumen, rows_resumen)

            det_base = [
                now,
                data.get("fecha", ""),
                data.get("comprobante_numero", ""),
                data.get("cliente", ""),
                data.get("direccion", ""),
            ]
            rows_detalle = []
            for linea in detalle_lineas:
                partes = [p.strip() for p in linea.split("|")]
                while len(partes) < 8:
                    partes.append("")
                rows_detalle.append(det_base + partes[:8] + [data.get("observaciones", "")])

            _append_rows_resilient(ws_detalle, rows_detalle)

            ws_doc = _ensure_doc_tab(spreadsheet, data, "COMPROBANTE")
            headers_doc = ["SECCION"] + HEADERS["COMP_RESUMEN"]
            rows_doc = (
                [["RESUMEN"] + r for r in rows_resumen]
                + [["DETALLE"] + r for r in rows_detalle]
            )
            _write_doc_snapshot(ws_doc, headers_doc, rows_doc)

            total_rows = len(ws_resumen.get_all_values())
            return {"success": True, "row": total_rows}

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
            _append_rows_resilient(ws, [row])

            ws_doc = _ensure_doc_tab(spreadsheet, data, "TICKET")
            headers = HEADERS["TICKETS"]
            _write_doc_snapshot(ws_doc, headers, [row])

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
