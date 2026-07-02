import csv
import re
from datetime import datetime
from io import BytesIO, StringIO
from zoneinfo import ZoneInfo

from openpyxl import Workbook

from services.sheets_service import HEADERS


def _now_buenos_aires() -> str:
    return datetime.now(ZoneInfo("America/Argentina/Buenos_Aires")).strftime("%d/%m/%Y %H:%M")


def _clean_filename(value: str) -> str:
    if not value:
        return "documento"
    cleaned = re.sub(r"[^\w\-\.]+", "_", str(value).strip(), flags=re.UNICODE)
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned[:80] or "documento"


def _doc_number(data: dict, doc_type: str) -> str:
    doc_type = doc_type.upper()
    if doc_type == "FACTURA":
        return data.get("numero", "")
    if doc_type == "REMITO":
        return data.get("orden_salida", data.get("numero", ""))
    if doc_type == "COMPROBANTE":
        return data.get("comprobante_numero", "")
    return data.get("numero", "")


def _build_rows_by_sheet(data: dict, doc_type: str) -> dict[str, list[list]]:
    now = _now_buenos_aires()
    dt = doc_type.upper()

    if dt == "FACTURA":
        rows = [[
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
        ]]
        return {"FACTURAS": [HEADERS["FACTURAS"]] + rows}

    if dt == "REMITO":
        articulos_raw = data.get("articulos", "")
        lineas = [line.strip() for line in articulos_raw.splitlines() if line.strip()] or [""]
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
        rows = []
        for line in lineas:
            parts = [part.strip() for part in line.split("|")]
            while len(parts) < 6:
                parts.append("")
            rows.append(base + parts[:6])
        return {"REMITOS": [HEADERS["REMITOS"]] + rows}

    if dt == "COMPROBANTE":
        resumen_lineas = [line.strip() for line in data.get("comp_resumen_lineas", "").splitlines() if line.strip()] or [""]
        detalle_lineas = [line.strip() for line in data.get("comp_detalle_lineas", "").splitlines() if line.strip()] or [""]

        resumen_base = [
            now,
            data.get("fecha", ""),
            data.get("comprobante_numero", ""),
            data.get("cliente", ""),
            data.get("direccion", ""),
            data.get("cantidad_total", ""),
            data.get("total_usd", ""),
        ]
        resumen_rows = []
        for line in resumen_lineas:
            parts = [part.strip() for part in line.split("|")]
            while len(parts) < 2:
                parts.append("")
            resumen_rows.append(resumen_base + parts[:2] + [data.get("observaciones", "")])

        detalle_base = [
            now,
            data.get("fecha", ""),
            data.get("comprobante_numero", ""),
            data.get("cliente", ""),
            data.get("direccion", ""),
        ]
        detalle_rows = []
        for line in detalle_lineas:
            parts = [part.strip() for part in line.split("|")]
            while len(parts) < 7:
                parts.append("")
            detalle_rows.append(detalle_base + parts[:7] + [data.get("observaciones", "")])

        return {
            "COMP_RESUMEN": [HEADERS["COMP_RESUMEN"]] + resumen_rows,
            "COMP_DETALLE": [HEADERS["COMP_DETALLE"]] + detalle_rows,
        }

    rows = [[
        now,
        data.get("fecha", ""),
        data.get("comercio", ""),
        data.get("concepto", ""),
        data.get("categoria", ""),
        data.get("monto", ""),
        data.get("observaciones", ""),
    ]]
    return {"TICKETS": [HEADERS["TICKETS"]] + rows}


def _build_csv_bytes(rows_by_sheet: dict[str, list[list]]) -> bytes:
    first_sheet = next(iter(rows_by_sheet.keys()))

    if len(rows_by_sheet) == 1:
        output = StringIO()
        writer = csv.writer(output)
        writer.writerows(rows_by_sheet[first_sheet])
        return output.getvalue().encode("utf-8-sig")

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["SECCION", "HOJA", "DATA_1", "DATA_2", "DATA_3", "DATA_4", "DATA_5", "DATA_6", "DATA_7", "DATA_8", "DATA_9", "DATA_10", "DATA_11", "DATA_12", "DATA_13", "DATA_14", "DATA_15"])
    for sheet_name, rows in rows_by_sheet.items():
        for idx, row in enumerate(rows):
            section = "HEADER" if idx == 0 else "ROW"
            writer.writerow([section, sheet_name] + row)
    return output.getvalue().encode("utf-8-sig")


def _build_xlsx_bytes(rows_by_sheet: dict[str, list[list]]) -> bytes:
    wb = Workbook()
    first = True

    for sheet_name, rows in rows_by_sheet.items():
        if first:
            ws = wb.active
            ws.title = sheet_name[:31]
            first = False
        else:
            ws = wb.create_sheet(title=sheet_name[:31])

        for row in rows:
            ws.append(row)

    content = BytesIO()
    wb.save(content)
    return content.getvalue()


def build_local_export(data: dict, doc_type: str, file_format: str) -> dict:
    dt = doc_type.upper()
    file_format = (file_format or "xlsx").lower()
    rows_by_sheet = _build_rows_by_sheet(data or {}, dt)

    number = _clean_filename(_doc_number(data or {}, dt))
    base_name = f"{dt}_{number}" if number and number != "documento" else dt

    if file_format == "csv":
        return {
            "success": True,
            "bytes": _build_csv_bytes(rows_by_sheet),
            "mimetype": "text/csv",
            "filename": f"{base_name}.csv",
        }

    return {
        "success": True,
        "bytes": _build_xlsx_bytes(rows_by_sheet),
        "mimetype": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "filename": f"{base_name}.xlsx",
    }