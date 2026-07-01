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

    comprobante_score = sum([
        5 if 'comprobante para compania de seguro' in t or 'comprobante para compañía de seguro' in t else 0,
        4 if 'costo reposicion' in t or 'costo reposición' in t else 0,
        3 if 'numero serie' in t or 'número serie' in t else 0,
        2 if 'sale' in t and 'vuelve' in t else 0,
        2 if 'cliente:' in t else 0,
        1 if 'usd' in t else 0,
    ])

    scores = {
        'REMITO': remito_score,
        'FACTURA': factura_score,
        'TICKET': ticket_score,
        'COMPROBANTE': comprobante_score,
    }
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
        "COMPROBANTE": _parse_comprobante,
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
    # Separar columnas Destino (izq) y Origen (der)
    destino_txt, origen_txt = _split_destino_origen(text)

    # Orden de salida
    orden = (
        _re_first(text, r'Orden\s+de\s+salida:\s*([A-Z0-9_\-]+)', 1, re.IGNORECASE) or
        _re_first(text, r'Orden\s+de\s+salida[:\s]+([A-Z]{1,3}[_\-]?\d+)', 1, re.IGNORECASE) or
        ""
    )

    # Destinatario: "A:" en seccion destino
    destinatario = (
        _re_first(destino_txt, r'^A:\s+(.+)', 1, re.MULTILINE) or
        re.split(r'\s{3,}', _re_first(text, r'^A:\s+([^\n\r]{3,60})', 1, re.MULTILINE) or '')[0].strip()
    )

    # Direcciones: findall devuelve [destino, origen] en orden
    dirs = re.findall(r'Direcci[o\u00f3]n:\s+(.+?)(?=\s{2,}|\n|Direcci[o\u00f3]n:|$)', text, re.IGNORECASE)
    destino_dir = dirs[0].strip()[:80] if len(dirs) > 0 else ''
    origen_dir  = dirs[1].strip()[:80] if len(dirs) > 1 else _re_first(origen_txt, r'Direcci[o\u00f3]n:\s+(.+)', 1, re.IGNORECASE)

    # Ciudades
    ciudades = re.findall(r'Ciudad,?\s*Provincia,?\s*CP:\s+(.+?)(?=\s{2,}|\n|Ciudad|$)', text, re.IGNORECASE)
    destino_ciudad = ciudades[0].strip()[:80] if len(ciudades) > 0 else ''
    origen_ciudad  = ciudades[1].strip()[:80] if len(ciudades) > 1 else _re_first(origen_txt, r'Ciudad,?\s*Provincia,?\s*CP:\s+(.+)', 1, re.IGNORECASE)

    # Telefonos
    tels = re.findall(r'Tel[e\u00e9]fono:\s+(.+?)(?=\s{2,}|\n|Tel[e\u00e9]fono:|$)', text, re.IGNORECASE)
    destino_tel = tels[0].strip()[:40] if len(tels) > 0 else ''
    origen_tel  = tels[1].strip()[:40] if len(tels) > 1 else _re_first(origen_txt, r'Tel[e\u00e9]fono:\s+(.+)', 1, re.IGNORECASE)

    # Origen nombre
    origen_nombre = (
        _re_first(origen_txt, r'^Origen:\s+(.+)', 1, re.MULTILINE | re.IGNORECASE) or
        _re_first(text, r'Origen:\s+([A-Z][A-Za-z0-9\s]{1,25})(?:\s{2,}|\n|$)', 1)
    )

    return {
        "fecha":             _find_date(text),
        "orden_salida":      orden,
        "pack":              _re_first(text, r'Pack[:\s#N\u00ba]*(\d+)', 1, re.IGNORECASE),
        "origen_nombre":     (origen_nombre or '').strip()[:60],
        "origen_direccion":  (origen_dir or '').strip()[:80],
        "origen_ciudad":     (origen_ciudad or '').strip()[:80],
        "origen_telefono":   (origen_tel or '').strip()[:40],
        "destinatario":      (destinatario or '').strip()[:60],
        "destino_direccion": (destino_dir or '').strip()[:80],
        "destino_ciudad":    (destino_ciudad or '').strip()[:80],
        "destino_telefono":  (destino_tel or '').strip()[:40],
        "articulos":         _find_remito_items(text),
        "peso_total":        _re_first(text, r'Peso\s+total\s*(?:\(kg\))?[:\s]*([0-9]+(?:[.,][0-9]+)?)', 1, re.IGNORECASE),
        "observaciones":     "",
    }


def _find_remito_items(text: str) -> str:
    """Extrae la tabla de artículos: NºLínea|Artículo|Descripción|Cant|Peso ind.|Peso."""
    lines = text.splitlines()
    items = []
    in_table = False

    for line in lines:
        s = line.strip()
        if not s:
            continue
        # Detectar encabezado de tabla
        if re.search(r'art[\u00edií]culo|descripci[o\u00f3]n|cant\.?\s*env|n[\u00ba\u00b0]?\s*l[\u00edií]n', s, re.IGNORECASE):
            in_table = True
            continue
        # Fin de tabla
        if in_table and re.search(r'peso\s*total|firma|observ', s, re.IGNORECASE):
            break
        if in_table and re.match(r'^\d+\s+', s):
            parts = re.split(r'\s{2,}', s)
            items.append(' | '.join(p.strip() for p in parts if p.strip()))

    if not items:
        # Fallback: lineas con codigo de 5-6 digitos
        for line in lines:
            s = line.strip()
            if re.match(r'^\d+\s+\d{5,6}\s+', s):
                parts = re.split(r'\s{2,}', s)
                items.append(' | '.join(p.strip() for p in parts if p.strip()))

    return "\n".join(items[:25]) if items else ""


def _split_destino_origen(text: str) -> tuple:
    """
    Para remitos de 2 columnas (easyWMS, etc.), divide el texto OCR
    en seccion Destino (izq) y Origen (der).
    Cada linea se divide por 2+ espacios: izq=destino, der=origen.
    """
    destino_lines = []
    origen_lines  = []
    mode = None  # None | 'destino' | 'origen' | 'both'

    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        has_d = bool(re.search(r'\bDestino\b', s, re.IGNORECASE))
        has_o = bool(re.search(r'\bOrigen\b', s, re.IGNORECASE))

        if has_d and has_o:
            mode = 'both'
            continue
        if has_d and not has_o:
            mode = 'destino'
            continue
        if has_o and not has_d:
            mode = 'origen'
            continue

        parts = re.split(r'\s{2,}', s)
        if len(parts) >= 2 and mode in ('both', None):
            destino_lines.append(parts[0])
            origen_lines.append(parts[-1])
        elif mode == 'destino':
            destino_lines.append(s)
        elif mode == 'origen':
            origen_lines.append(s)
        else:
            destino_lines.append(s)

    return '\n'.join(destino_lines), '\n'.join(origen_lines)


def _parse_ticket(text: str) -> dict:
    return {
        "fecha":         _find_date(text),
        "comercio":      _find_provider(text),
        "concepto":      _find_concept(text),
        "categoria":     _detect_category(text),
        "monto":         _find_total(text),
        "observaciones": "",
    }


def _parse_comprobante(text: str) -> dict:
    numero = (
        _re_first(text, r'N[°º]\s*([0-9]{3,5}\s*[-/]\s*[0-9]{3,8})', 1, re.IGNORECASE)
        .replace(" ", "")
    )
    fecha = _find_date(text)
    cliente, direccion = _extract_cliente_direccion(text)
    total = _find_last_usd_total(text)

    resumen_items, detalle_items = _extract_comprobante_items(text)

    cantidad_total = 0
    for item in resumen_items:
        try:
            cantidad_total += int(item.get("cantidad", "0") or "0")
        except ValueError:
            pass

    resumen_lines = [
        " | ".join([
            item.get("cantidad", ""),
            item.get("detalle", ""),
            item.get("numero_serie", ""),
            item.get("costo_reposicion", ""),
        ])
        for item in resumen_items
    ]

    detalle_lines = [
        " | ".join([
            item.get("tipo", ""),
            item.get("linea_padre", ""),
            item.get("cantidad", ""),
            item.get("detalle", ""),
            item.get("numero_serie", ""),
            item.get("costo_reposicion", ""),
        ])
        for item in detalle_items
    ]

    return {
        "fecha": fecha,
        "comprobante_numero": numero,
        "cliente": cliente,
        "direccion": direccion,
        "cantidad_total": str(cantidad_total),
        "total_usd": total,
        "comp_resumen_lineas": "\n".join(resumen_lines),
        "comp_detalle_lineas": "\n".join(detalle_lines),
        "observaciones": "",
    }


def _find_last_usd_total(text: str) -> str:
    matches = re.findall(r'USD\s*([0-9\.,]+)', text, re.IGNORECASE)
    return matches[-1] if matches else ""


def _extract_cliente_direccion(text: str) -> tuple[str, str]:
    cliente_line = _re_first(text, r'Cliente\s*:\s*([^\n\r]+)', 1, re.IGNORECASE)
    direccion_line = _re_first(text, r'Direcci[oó]n\s*:\s*([^\n\r]+)', 1, re.IGNORECASE)

    cliente = cliente_line
    direccion = direccion_line

    if cliente_line and re.search(r'Direcci[oó]n\s*:', cliente_line, re.IGNORECASE):
        parts = re.split(r'Direcci[oó]n\s*:\s*', cliente_line, maxsplit=1, flags=re.IGNORECASE)
        cliente = parts[0]
        if len(parts) > 1 and not direccion:
            direccion = parts[1]

    cliente = re.sub(r'\s+', ' ', (cliente or '')).strip(' .:-')
    direccion = re.sub(r'\s+', ' ', (direccion or '')).strip(' .:-')

    if direccion in ('', '-', '.', '·'):
        direccion = ''

    return cliente, direccion


def _extract_serial_candidate(text: str) -> str:
    m = re.search(r'((?=[A-Z0-9\.\-]*\d)[A-Z0-9\.\-]{6,})\s*$', text, re.IGNORECASE)
    return m.group(1) if m else ""


def _extract_comprobante_items(text: str) -> tuple[list[dict], list[dict]]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    in_table = False
    resumen_items = []
    detalle_items = []
    parent_idx = 0

    for raw in lines:
        line = re.sub(r'\s{2,}', '  ', raw)

        if not in_table and re.search(r'\bcant\b.*\bdetalle\b.*\bserie\b', line, re.IGNORECASE):
            in_table = True
            continue

        if not in_table:
            continue

        if re.search(r'^total\b', line, re.IGNORECASE):
            break

        cost = _re_first(line, r'USD\s*([0-9\.,]+)\s*$', 1, re.IGNORECASE)
        line_wo_cost = re.sub(r'\s*USD\s*[0-9\.,]+\s*$', '', line, flags=re.IGNORECASE)

        main_match = re.match(r'^(\d{1,3})\s+(.+)$', line_wo_cost)
        if main_match:
            qty = main_match.group(1).strip()
            content = main_match.group(2).strip()
            serial = _extract_serial_candidate(content)
            detail = content
            if serial:
                detail = re.sub(r'\s*(?=[A-Z0-9\.\-]*\d)[A-Z0-9\.\-]{6,}\s*$', '', detail).strip()

            parent_idx += 1
            resumen_items.append({
                "cantidad": qty,
                "detalle": detail,
                "numero_serie": serial,
                "costo_reposicion": cost,
                "linea_padre": str(parent_idx),
            })
            detalle_items.append({
                "tipo": "ARTICULO",
                "linea_padre": str(parent_idx),
                "cantidad": qty,
                "detalle": detail,
                "numero_serie": serial,
                "costo_reposicion": cost,
            })
            continue

        if parent_idx > 0:
            serial = _extract_serial_candidate(line_wo_cost)
            detail = line_wo_cost
            if serial:
                detail = re.sub(r'\s*(?=[A-Z0-9\.\-]*\d)[A-Z0-9\.\-]{6,}\s*$', '', detail).strip()
            detail = detail.lstrip('.').strip('-').strip()
            detail = re.sub(r'^\:+', '', detail).strip()
            if detail:
                detalle_items.append({
                    "tipo": "SUBARTICULO",
                    "linea_padre": str(parent_idx),
                    "cantidad": "",
                    "detalle": detail,
                    "numero_serie": serial,
                    "costo_reposicion": "",
                })

    return resumen_items, detalle_items


# ---------------------------------------------------------------------------
# Helpers de extracción
# ---------------------------------------------------------------------------

def _find_date(text: str) -> str:
    """Busca la primera fecha en el texto."""
    patterns = [
        r"\b(\d{2}[/\-]\d{2}[/\-]\d{4})\b",
        r"\b(\d{4}[/\-]\d{2}[/\-]\d{2})\b",
        r"\b(\d{2}\s+\d{2}\s+\d{4})\b",
        r"\b(\d{2}\s+de\s+\w+\s+de\s+\d{4})\b",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            found = m.group(1).strip()
            if re.match(r"^\d{2}\s+\d{2}\s+\d{4}$", found):
                return re.sub(r"\s+", "/", found)
            return found
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
