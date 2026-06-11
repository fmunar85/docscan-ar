"""
Parser de documentos argentinos (Facturas, Remitos, Tickets).
Se usa como fallback cuando no hay OpenAI o cuando el input es PDF.
Extrae campos mediante expresiones regulares adaptadas al formato AFIP.
"""
import re
from datetime import datetime


# ---------------------------------------------------------------------------
# Dispatcher principal
# ---------------------------------------------------------------------------

def parse_document(text: str, doc_type: str) -> dict:
    parsers = {
        "FACTURA": _parse_factura,
        "REMITO":  _parse_remito,
        "TICKET":  _parse_ticket,
    }
    parser = parsers.get(doc_type.upper(), _parse_ticket)
    data = parser(text)
    data["tipo"] = doc_type.upper()
    return data


# ---------------------------------------------------------------------------
# Parsers por tipo de documento
# ---------------------------------------------------------------------------

def _parse_factura(text: str) -> dict:
    return {
        "fecha":            _find_date(text),
        "tipo_comprobante": _find_invoice_type(text),
        "numero":           _find_invoice_number(text),
        "proveedor":        _find_provider(text),
        "cuit":             _find_cuit(text),
        "subtotal":         _find_amount(text, r"(?:neto\s+gravado|subtotal|base\s+imponible)"),
        "iva_porcentaje":   _find_iva_pct(text),
        "iva_monto":        _find_amount(text, r"(?:i\.?v\.?a\.?|impuesto\s+al\s+valor)"),
        "total":            _find_total(text),
        "cae":              _find_cae(text),
        "vencimiento_cae":  _find_cae_expiry(text),
        "observaciones":    "",
    }


def _parse_remito(text: str) -> dict:
    return {
        "fecha":         _find_date(text),
        "numero":        _find_remito_number(text),
        "proveedor":     _find_provider(text),
        "destinatario":  _find_field(text, r"(?:destinatario|receptor|cliente)[:\s]+([^\n]+)"),
        "articulos":     _find_items(text),
        "observaciones": "",
    }


def _parse_ticket(text: str) -> dict:
    return {
        "fecha":         _find_date(text),
        "comercio":      _find_provider(text),
        "concepto":      _find_concept(text),
        "categoria":     _detect_category(text),
        "monto":         _find_total(text),
        "observaciones": "",
    }


# ---------------------------------------------------------------------------
# Helpers de extracción
# ---------------------------------------------------------------------------

def _find_date(text: str) -> str:
    """Busca la primera fecha en el texto."""
    patterns = [
        r"\b(\d{2}[/\-]\d{2}[/\-]\d{4})\b",
        r"\b(\d{4}[/\-]\d{2}[/\-]\d{2})\b",
        r"\b(\d{2}\s+de\s+\w+\s+de\s+\d{4})\b",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return m.group(1)
    return ""


def _find_invoice_type(text: str) -> str:
    """Tipo de comprobante: A, B, C, M."""
    m = re.search(r"\bfactura\s+([ABCM])\b", text, re.IGNORECASE)
    if m:
        return m.group(1).upper()
    # Letra en recuadro grande (código AFIP)
    m = re.search(r"(?:CODIGO\s+\d+)?\s*\b([ABCM])\b", text)
    if m:
        return m.group(1).upper()
    return ""


def _find_invoice_number(text: str) -> str:
    """Número de comprobante AFIP: XXXX-XXXXXXXX."""
    m = re.search(r"\b(\d{4}[-\s]\d{8})\b", text)
    if m:
        return m.group(1)
    m = re.search(r"(?:N[°º\.]?|NUMERO|FACTURA\s+N)[°º\.\s:]*(\d{8,13})", text, re.IGNORECASE)
    if m:
        return m.group(1)
    return ""


def _find_remito_number(text: str) -> str:
    m = re.search(r"(?:REMITO|R[°º]?)[°º\s:#]*(\d{4}[-\s]\d{8}|\d{6,13})", text, re.IGNORECASE)
    if m:
        return m.group(1)
    return ""


def _find_provider(text: str) -> str:
    """Intenta encontrar la razón social."""
    m = re.search(r"(?:raz[oó]n\s+social|nombre\s+y\s+apellido|empresa)[:\s]+([^\n]{3,60})", text, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    # Primera línea no vacía como fallback
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    return lines[0][:60] if lines else ""


def _find_cuit(text: str) -> str:
    m = re.search(r"(?:cuit|cuil)[:\s]*(\d{2}[-\s]\d{8}[-\s]\d)\b", text, re.IGNORECASE)
    if m:
        return m.group(1).replace(" ", "-")
    m = re.search(r"(?:cuit|cuil)[:\s]*(\d{11})\b", text, re.IGNORECASE)
    if m:
        raw = m.group(1)
        return f"{raw[:2]}-{raw[2:10]}-{raw[10]}"
    return ""


def _find_amount(text: str, label_pattern: str) -> str:
    """Busca un importe a continuación de una etiqueta."""
    pattern = rf"(?:{label_pattern})[:\s\$]*([0-9]+(?:[.,][0-9]{{3}})*(?:[.,][0-9]{{2}})?)"
    m = re.search(pattern, text, re.IGNORECASE)
    if m:
        raw = m.group(1).replace(".", "").replace(",", ".")
        return raw
    return ""


def _find_iva_pct(text: str) -> str:
    m = re.search(r"(?:i\.?v\.?a\.?)[\s:]+(\d+(?:[.,]\d+)?)\s*%", text, re.IGNORECASE)
    if m:
        return m.group(1).replace(",", ".")
    # Tasas estándar AFIP
    if re.search(r"\b10[,.]5\b", text):
        return "10.5"
    if re.search(r"\b27\b", text):
        return "27"
    return "21"


def _find_total(text: str) -> str:
    patterns = [
        r"(?:total\s+a\s+pagar|importe\s+total|total\s+factura|total)[:\s\$]*([0-9]+(?:[.,][0-9]{3})*(?:[.,][0-9]{2})?)",
        r"(?:a\s+pagar)[:\s\$]*([0-9]+(?:[.,][0-9]{3})*(?:[.,][0-9]{2})?)",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return m.group(1).replace(".", "").replace(",", ".")
    return ""


def _find_cae(text: str) -> str:
    m = re.search(r"\bCAE\b[:\s]*(\d{14})\b", text, re.IGNORECASE)
    return m.group(1) if m else ""


def _find_cae_expiry(text: str) -> str:
    m = re.search(r"(?:venc(?:imiento)?\.?\s*(?:del?\s*)?cae|cae\s*venc)[:\s]*(\d{2}[/\-]\d{2}[/\-]\d{4}|\d{8})", text, re.IGNORECASE)
    return m.group(1) if m else ""


def _find_field(text: str, pattern: str) -> str:
    m = re.search(pattern, text, re.IGNORECASE)
    return m.group(1).strip()[:80] if m else ""


def _find_items(text: str) -> str:
    """Extrae líneas que parecen artículos (número + texto)."""
    lines = text.splitlines()
    items = []
    for line in lines:
        line = line.strip()
        # Líneas con cantidad y descripción
        if re.search(r"^\d+[\s,]+\w", line) and len(line) > 5:
            items.append(line)
        elif re.search(r"\b\d+\s*(un|unid|kg|lt|mts|pzas?)\b", line, re.IGNORECASE):
            items.append(line)
    return "\n".join(items[:15]) if items else ""


def _find_concept(text: str) -> str:
    """Primera línea significativa como concepto del gasto."""
    lines = [l.strip() for l in text.splitlines() if l.strip() and len(l.strip()) > 3]
    return lines[0][:100] if lines else ""


def _detect_category(text: str) -> str:
    t = text.lower()
    if any(w in t for w in ["nafta", "gasoil", "diesel", "combustible", "shell", "ypf", "axion", "puma", "litro"]):
        return "NAFTA/COMBUSTIBLE"
    if any(w in t for w in ["peaje", "autopista", "autovía", "telepeaje", "aupass"]):
        return "PEAJE"
    if any(w in t for w in ["estacionamiento", "parking", "playa de", "garage"]):
        return "ESTACIONAMIENTO"
    if any(w in t for w in ["hotel", "hospedaje", "alojamiento", "motel", "apart"]):
        return "HOSPEDAJE"
    if any(w in t for w in ["restaurant", "resto", "comida", "almuerzo", "cena", "café", "café", "delivery", "pizz"]):
        return "ALIMENTACION"
    return "OTRO"
