"""
Parser de documentos argentinos (Facturas, Remitos, Tickets).
Extrae campos con expresiones regulares. Sin APIs externas.
"""
import re
from datetime import datetime


# ---------------------------------------------------------------------------
# Detección automática del tipo de documento
# ---------------------------------------------------------------------------

def detect_doc_type(text: str) -> str:
    """Detecta el tipo de documento desde el texto extraído."""
    t = text.lower()

    remito_score = sum([
        4 if 'remito' in t else 0,
        3 if 'orden de salida' in t else 0,
        2 if 'destinatario' in t else 0,
        2 if ('pack' in t and 'peso' in t) else 0,
        2 if 'easywms' in t.replace(' ', '') else 0,
        1 if 'bulto' in t or 'palet' in t else 0,
        1 if 'despacho' in t else 0,
    ])

    factura_score = sum([
        4 if re.search(r'\bfactura\b', t) else 0,
        3 if 'cae' in t else 0,
        3 if 'cuit' in t else 0,
        2 if re.search(r'\biva\b|i\.v\.a', t) else 0,
        2 if 'afip' in t else 0,
        1 if 'subtotal' in t else 0,
    ])

    ticket_score = sum([
        4 if re.search(r'\bticket\b|comprobante de pago', t) else 0,
        3 if any(w in t for w in ['nafta', 'combustible', 'gasoil', 'ypf', 'shell', 'axion']) else 0,
        3 if any(w in t for w in ['peaje', 'autopista', 'telepeaje']) else 0,
        1 if any(w in t for w in ['estacionamiento', 'parking']) else 0,
    ])

    scores = {'REMITO': remito_score, 'FACTURA': factura_score, 'TICKET': ticket_score}
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else 'FACTURA'


# ---------------------------------------------------------------------------
# Dispatcher principal
# ---------------------------------------------------------------------------

def parse_document(text: str, doc_type: str) -> dict:
    # Si el tipo es AUTO o vacío, detectarlo del texto
    if not doc_type or doc_type.upper() == 'AUTO':
        doc_type = detect_doc_type(text)

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
    # Número de orden / remito
    orden = (
        _re_first(text, r'orden\s*de\s*salida[:\s#Nº]*([A-Z]{1,3}[-\s]?\d+)', 1) or
        _re_first(text, r'orden\s*de\s*salida[:\s#Nº]*(\d{4,})', 1) or
        ""
    )
    numero = _find_invoice_number(text) or orden

    return {
        "fecha":             _find_date(text),
        "numero":            numero,
        "orden_salida":      orden,
        "pack":              _re_first(text, r'pack[:\s#Nº]*(\d+)', 1),
        "proveedor":         (
                               _re_first(text, r'Origen:[ \t]+([A-Z][^\n\r:]{2,40})', 1, re.IGNORECASE) or
                               _re_first(text, r'(?:remitente|proveedor):[ \t]+([^\n\r]{3,60})', 1) or
                               _find_provider(text)
                             ),
        "destinatario":      (
                               # Para remitos de 2 columnas el OCR mezcla Destino y Origen en la misma línea
                               # Usamos el separador de columnas (3+ espacios) para cortar
                               re.split(r'\s{3,}', _re_first(text, r'^A:[ \t]+([^\n\r]{3,60})', 1, re.MULTILINE))[0].strip() or
                               _re_first(text, r'destinatario:[ \t]+([^\n\r]{3,60})', 1) or
                               _re_first(text, r'receptor:[ \t]+([^\n\r]{3,60})', 1) or
                               ""
                             ),
        "destino_direccion": _re_first(text, r'Direcci[oó]n:[ \t]+([^\n\r]{5,80})', 1, re.IGNORECASE),
        "destino_localidad": (
                               _re_first(text, r'Ciudad[,\s]*(?:Provincia[,\s]*CP)?:[ \t]+([^\n\r]{3,80})', 1, re.IGNORECASE) or
                               _re_first(text, r'Localidad:[ \t]+([^\n\r]{3,60})', 1, re.IGNORECASE) or
                               ""
                             ),
        "articulos":         _find_remito_items(text),
        "peso_total":        _re_first(text, r'peso\s*total\s*(?:\(kg\))?[:\s]*([0-9]+(?:[.,][0-9]+)?)', 1),
        "observaciones":     "",
    }


def _find_remito_items(text: str) -> str:
    """Extrae las líneas de artículos de la tabla del remito."""
    lines = text.splitlines()
    items = []
    in_table = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        # Detectar encabezado de tabla
        if re.search(r'art[\u00edí]culo|descripci[oó]n|cant\.?\s*env|cont\.?\s*env|n\.?\s*l[ií]n', stripped, re.IGNORECASE):
            in_table = True
            continue
        # Detectar pie de tabla
        if in_table and re.search(r'peso\s*total|total\s*general|subtotal|firma|obser', stripped, re.IGNORECASE):
            break
        if in_table and stripped:
            # Línea de artículo: empieza con dígito(s) seguido de código/descripción
            if re.match(r'^\d+\s+', stripped):
                parts = re.split(r'\s{2,}', stripped)
                items.append('  |  '.join(p.strip() for p in parts if p.strip()))

    if not items:
        # Fallback genérico
        for line in lines:
            stripped = line.strip()
            if re.search(r'\b\d+\s*(un|unid|pzas?|pares?|kg|lt|mts|bultos?|cajas?)\b', stripped, re.IGNORECASE):
                items.append(stripped)
            elif re.match(r'^\d+\s+\d{4,}\s+[A-ZÁÉÍÓÚ]', stripped):
                items.append(stripped)

    return "\n".join(items[:25]) if items else ""


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


def _re_first(text: str, pattern: str, group: int = 0, flags: int = re.IGNORECASE) -> str:
    """Devuelve el primer match del grupo indicado, o string vacío."""
    m = re.search(pattern, text, flags)
    return m.group(group).strip() if m else ""


def _find_provider(text: str) -> str:
    """Intenta encontrar la razón social o nombre del emisor."""
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
