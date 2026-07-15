"""
Servicio de exportación local – DocScan AR
==========================================
Genera archivos XLSX y CSV descargables con formato profesional.
• XLSX: pestañas por hoja, cabeceras con color, anchos automáticos,
        fila de totales, filas alternadas.
• CSV:  sección separada por tipo, compatible UTF-8 con BOM.
"""
import csv
import re
from datetime import datetime
from io import BytesIO, StringIO
from zoneinfo import ZoneInfo

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from services.sheets_service import HEADERS


# ---------------------------------------------------------------------------
# Helpers de tiempo y nombres
# ---------------------------------------------------------------------------

def _now_ba() -> str:
    return datetime.now(ZoneInfo("America/Argentina/Buenos_Aires")).strftime(
        "%d/%m/%Y %H:%M"
    )


def _clean_filename(value: str) -> str:
    if not value:
        return "documento"
    cleaned = re.sub(r"[^\w\-\.]+", "_", str(value).strip(), flags=re.UNICODE)
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned[:80] or "documento"


def _doc_number(data: dict, doc_type: str) -> str:
    dt = doc_type.upper()
    if dt == "FACTURA":
        return data.get("numero", "")
    if dt == "REMITO":
        return data.get("orden_salida", data.get("numero", ""))
    if dt == "COMPROBANTE":
        return data.get("comprobante_numero", "")
    return data.get("numero", "")


# ---------------------------------------------------------------------------
# Estilos Excel
# ---------------------------------------------------------------------------

_HDR_FILL   = PatternFill("solid", fgColor="1F4E79")   # azul oscuro
_HDR_FONT   = Font(color="FFFFFF", bold=True, size=10, name="Calibri")
_HDR_ALIGN  = Alignment(horizontal="center", vertical="center", wrap_text=True)

_INFO_FILL  = PatternFill("solid", fgColor="D6E4F0")
_INFO_FONT  = Font(bold=True, size=11, name="Calibri", color="1F4E79")
_INFO_ALIGN = Alignment(horizontal="left", vertical="center")

_TOT_FILL   = PatternFill("solid", fgColor="FFF2CC")
_TOT_FONT   = Font(bold=True, size=10, name="Calibri")

_ALT_FILL   = PatternFill("solid", fgColor="EAF2FB")
_NRM_FILL   = PatternFill("solid", fgColor="FFFFFF")
_ROW_FONT   = Font(size=9, name="Calibri")
_ROW_ALIGN  = Alignment(horizontal="left", vertical="center", wrap_text=False)

_THIN_SIDE  = Side(style="thin", color="BDD7EE")
_BORDER     = Border(
    left=_THIN_SIDE, right=_THIN_SIDE,
    top=_THIN_SIDE,  bottom=_THIN_SIDE
)


def _style_info(ws, row: int, ncols: int):
    for c in range(1, ncols + 1):
        cell = ws.cell(row=row, column=c)
        cell.fill = _INFO_FILL
        cell.font = _INFO_FONT
        cell.alignment = _INFO_ALIGN
        cell.border = _BORDER
    ws.row_dimensions[row].height = 22


def _style_header(ws, row: int, ncols: int):
    for c in range(1, ncols + 1):
        cell = ws.cell(row=row, column=c)
        cell.fill = _HDR_FILL
        cell.font = _HDR_FONT
        cell.alignment = _HDR_ALIGN
        cell.border = _BORDER
    ws.row_dimensions[row].height = 30


def _style_data(ws, row: int, ncols: int, alt: bool):
    fill = _ALT_FILL if alt else _NRM_FILL
    for c in range(1, ncols + 1):
        cell = ws.cell(row=row, column=c)
        cell.fill = fill
        cell.font = _ROW_FONT
        cell.alignment = _ROW_ALIGN
        cell.border = _BORDER
    ws.row_dimensions[row].height = 15


def _style_total(ws, row: int, ncols: int):
    for c in range(1, ncols + 1):
        cell = ws.cell(row=row, column=c)
        cell.fill = _TOT_FILL
        cell.font = _TOT_FONT
        cell.alignment = _ROW_ALIGN
        cell.border = _BORDER
    ws.row_dimensions[row].height = 18


def _auto_width(ws, min_w: int = 8, max_w: int = 60):
    for col_cells in ws.columns:
        length = min_w
        for cell in col_cells:
            try:
                length = max(length, min(len(str(cell.value or "")) + 2, max_w))
            except Exception:
                pass
        ws.column_dimensions[get_column_letter(col_cells[0].column)].width = length


def _write_sheet(ws, headers: list, data_rows: list[list],
                 info_label: str = "", totals_row: list | None = None,
                 freeze: bool = True):
    ncols = len(headers)
    r = 1

    if info_label:
        ws.merge_cells(start_row=r, start_column=1,
                       end_row=r, end_column=max(ncols, 1))
        ws.cell(row=r, column=1, value=info_label)
        _style_info(ws, r, ncols)
        r += 1

    for c, h in enumerate(headers, 1):
        ws.cell(row=r, column=c, value=h)
    _style_header(ws, r, ncols)
    freeze_row = r + 1
    r += 1

    for i, row in enumerate(data_rows):
        for c, v in enumerate(row, 1):
            ws.cell(row=r, column=c, value=v)
        _style_data(ws, r, ncols, alt=(i % 2 == 1))
        r += 1

    if totals_row:
        for c, v in enumerate(totals_row, 1):
            ws.cell(row=r, column=c, value=v)
        _style_total(ws, r, ncols)

    if freeze:
        ws.freeze_panes = ws.cell(row=freeze_row, column=1).coordinate

    _auto_width(ws)


# ---------------------------------------------------------------------------
# Constructores de datos por tipo
# ---------------------------------------------------------------------------

def _factura(data: dict, now: str):
    h = HEADERS["FACTURAS"]
    row = [now, data.get("fecha",""), data.get("tipo_comprobante",""),
           data.get("numero",""), data.get("proveedor",""), data.get("cuit",""),
           data.get("subtotal",""), data.get("iva_porcentaje",""),
           data.get("iva_monto",""), data.get("total",""),
           data.get("cae",""), data.get("vencimiento_cae",""),
           data.get("observaciones","")]
    tot = [""] * len(h)
    tot[0] = "TOTAL"
    tot[9] = data.get("total", "")
    return h, [row], tot


def _remito(data: dict, now: str):
    h = HEADERS["REMITOS"]
    raw = data.get("articulos", "")
    lineas = [l.strip() for l in raw.splitlines() if l.strip()] or [""]
    base = [now, data.get("fecha",""), data.get("orden_salida",""),
            data.get("pack",""), data.get("origen_nombre",""),
            data.get("origen_direccion",""), data.get("origen_ciudad",""),
            data.get("origen_telefono",""), data.get("destinatario",""),
            data.get("destino_direccion",""), data.get("destino_ciudad",""),
            data.get("destino_telefono",""), data.get("peso_total",""),
            data.get("observaciones","")]
    rows = []
    for line in lineas:
        parts = [p.strip() for p in line.split("|")]
        while len(parts) < 6:
            parts.append("")
        rows.append(base + parts[:6])
    tot = [""] * len(h)
    tot[0] = f"TOTAL — {len(rows)} artículo(s)"
    tot[12] = data.get("peso_total", "")
    return h, rows, tot


def _ticket(data: dict, now: str):
    h = HEADERS["TICKETS"]
    row = [now, data.get("fecha",""), data.get("comercio",""),
           data.get("concepto",""), data.get("categoria",""),
           data.get("monto",""), data.get("observaciones","")]
    tot = [""] * len(h)
    tot[0] = "TOTAL"
    tot[5] = data.get("monto", "")
    return h, [row], tot


def _comprobante(data: dict, now: str):
    """Devuelve (res_headers, res_rows, res_totals, det_headers, det_rows)."""
    res_h = HEADERS["COMP_RESUMEN"]
    det_h = HEADERS["COMP_DETALLE"]

    res_lineas = [l.strip() for l in data.get("comp_resumen_lineas","").splitlines() if l.strip()] or [""]
    det_lineas = [l.strip() for l in data.get("comp_detalle_lineas","").splitlines() if l.strip()] or [""]

    res_base = [now, data.get("fecha",""), data.get("comprobante_numero",""),
                data.get("cliente",""), data.get("direccion",""),
                data.get("cantidad_total",""), data.get("total_usd","")]
    res_rows = []
    for line in res_lineas:
        parts = [p.strip() for p in line.split("|")]
        while len(parts) < 2:
            parts.append("")
        res_rows.append(res_base + parts[:2] + [data.get("observaciones","")])

    det_base = [now, data.get("fecha",""), data.get("comprobante_numero",""),
                data.get("cliente",""), data.get("direccion","")]
    det_rows = []
    for line in det_lineas:
        parts = [p.strip() for p in line.split("|")]
        while len(parts) < 7:
            parts.append("")
        det_rows.append(det_base + parts[:7] + [data.get("observaciones","")])

    res_tot = [""] * len(res_h)
    res_tot[0] = f"TOTAL — {len(res_rows)} artículo(s)"
    res_tot[5] = data.get("cantidad_total", "")
    res_tot[6] = data.get("total_usd", "")

    return res_h, res_rows, res_tot, det_h, det_rows


# ---------------------------------------------------------------------------
# XLSX builder
# ---------------------------------------------------------------------------

def _xlsx(data: dict, doc_type: str) -> bytes:
    dt  = doc_type.upper()
    now = _now_ba()
    wb  = Workbook()

    if dt == "COMPROBANTE":
        res_h, res_rows, res_tot, det_h, det_rows = _comprobante(data, now)
        comp   = data.get("comprobante_numero", "")
        cliente = data.get("cliente", "")
        fecha  = data.get("fecha", "")
        info   = f"Comprobante Nº {comp}  |  Cliente: {cliente}  |  Fecha: {fecha}"

        ws1 = wb.active
        ws1.title = "Comp. Resumen"
        _write_sheet(ws1, res_h, res_rows, info_label=info, totals_row=res_tot)

        ws2 = wb.create_sheet(title="Comp. Detalle")
        _write_sheet(ws2, det_h, det_rows, info_label=info, totals_row=None)

    elif dt == "FACTURA":
        h, rows, tot = _factura(data, now)
        info = (f"Factura Nº {data.get('numero','')}  |  "
                f"Proveedor: {data.get('proveedor','')}  |  Fecha: {data.get('fecha','')}")
        ws = wb.active
        ws.title = "Factura"
        _write_sheet(ws, h, rows, info_label=info, totals_row=tot)

    elif dt == "REMITO":
        h, rows, tot = _remito(data, now)
        info = (f"Remito Nº {data.get('orden_salida','')}  |  "
                f"Destinatario: {data.get('destinatario','')}  |  Fecha: {data.get('fecha','')}")
        ws = wb.active
        ws.title = "Remito"
        _write_sheet(ws, h, rows, info_label=info, totals_row=tot)

    else:
        h, rows, tot = _ticket(data, now)
        info = (f"Ticket  |  Comercio: {data.get('comercio','')}  |  "
                f"Fecha: {data.get('fecha','')}")
        ws = wb.active
        ws.title = "Ticket"
        _write_sheet(ws, h, rows, info_label=info, totals_row=tot)

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# CSV builder  (limpio, sin DATA_N)
# ---------------------------------------------------------------------------

def _csv(data: dict, doc_type: str) -> bytes:
    dt  = doc_type.upper()
    now = _now_ba()
    out = StringIO()
    wr  = csv.writer(out, quoting=csv.QUOTE_MINIMAL)

    if dt == "COMPROBANTE":
        res_h, res_rows, res_tot, det_h, det_rows = _comprobante(data, now)
        comp = data.get("comprobante_numero", "")
        wr.writerow([f"=== COMP. RESUMEN — Comprobante Nº {comp} ==="])
        wr.writerow(res_h)
        wr.writerows(res_rows)
        wr.writerow(res_tot)
        wr.writerow([])
        wr.writerow([f"=== COMP. DETALLE — Comprobante Nº {comp} ==="])
        wr.writerow(det_h)
        wr.writerows(det_rows)

    elif dt == "FACTURA":
        h, rows, tot = _factura(data, now)
        wr.writerow(h); wr.writerows(rows); wr.writerow(tot)

    elif dt == "REMITO":
        h, rows, tot = _remito(data, now)
        wr.writerow(h); wr.writerows(rows); wr.writerow(tot)

    else:
        h, rows, tot = _ticket(data, now)
        wr.writerow(h); wr.writerows(rows); wr.writerow(tot)

    return out.getvalue().encode("utf-8-sig")


# ---------------------------------------------------------------------------
# Punto de entrada público
# ---------------------------------------------------------------------------

def build_local_export(data: dict, doc_type: str, file_format: str) -> dict:
    dt          = (doc_type or "FACTURA").upper()
    file_format = (file_format or "xlsx").lower()
    data        = data or {}

    number    = _clean_filename(_doc_number(data, dt))
    base_name = f"{dt}_{number}" if number and number != "documento" else dt

    if file_format == "csv":
        return {
            "success":  True,
            "bytes":    _csv(data, dt),
            "mimetype": "text/csv",
            "filename": f"{base_name}.csv",
        }

    return {
        "success":  True,
        "bytes":    _xlsx(data, dt),
        "mimetype": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "filename": f"{base_name}.xlsx",
    }
