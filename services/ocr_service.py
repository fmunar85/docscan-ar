"""
Servicio OCR de DocScan AR
===========================
Extrae texto de documentos SIN necesitar ninguna API externa.
Orden de prioridad:
  PDF    → pdfplumber        (texto nativo, 100% gratis y local)
  Imagen → pytesseract       (OCR local, gratis, necesita Tesseract instalado)
  Imagen → OpenAI GPT-4o     (opcional, máxima precisión si OPENAI_API_KEY está configurado)
  Imagen → Google Vision     (opcional, si GOOGLE_CREDENTIALS_JSON está configurado)
  Sin OCR → formulario vacío (carga manual, siempre funciona)
"""
import os
import io
import json
import base64
import tempfile

from PIL import Image, ImageEnhance, ImageFilter

from services.document_parser import parse_document


# ---------------------------------------------------------------------------
# Punto de entrada principal
# ---------------------------------------------------------------------------

def process_document(filepath: str, doc_type: str) -> dict:
    """
    Procesa el archivo y devuelve un dict con los campos extraídos.
    Nunca lanza excepción: si todo falla devuelve formulario vacío.
    """
    ext = filepath.rsplit(".", 1)[-1].lower()

    # ── PDF: texto nativo (sin API, sin Tesseract) ────────────────
    if ext == "pdf":
        try:
            raw_text = _extract_pdf_text(filepath)
            if raw_text.strip():
                return parse_document(raw_text, doc_type)
        except Exception as e:
            print(f"[OCR] pdfplumber: {e}")

    # ── Imagen: OpenAI GPT-4o si está configurado (mejor calidad) ─
    if os.environ.get("OPENAI_API_KEY"):
        try:
            return _process_with_openai(filepath, doc_type)
        except Exception as e:
            print(f"[OCR] OpenAI: {e} — probando método local")

    # ── Imagen: Google Vision si está configurado ─────────────────
    if os.environ.get("GOOGLE_CREDENTIALS_JSON") or os.path.exists("credentials.json"):
        try:
            raw_text = _extract_with_google_vision(filepath)
            if raw_text.strip():
                return parse_document(raw_text, doc_type)
        except Exception as e:
            print(f"[OCR] Google Vision: {e} — probando pytesseract")

    # ── Imagen: pytesseract LOCAL (gratis, sin internet) ─────────
    try:
        raw_text = _extract_with_tesseract(filepath)
        if raw_text.strip():
            return parse_document(raw_text, doc_type)
    except Exception as e:
        print(f"[OCR] pytesseract: {e}")

    # ── Fallback: formulario vacío para carga manual ──────────────
    print("[OCR] Sin texto extraído — mostrando formulario vacío")
    result = parse_document("", doc_type)
    result["_warning"] = "No se pudo leer el documento automáticamente. Completá los campos manualmente."
    return result


# ---------------------------------------------------------------------------
# PDF  →  pdfplumber
# ---------------------------------------------------------------------------

def _extract_pdf_text(filepath: str) -> str:
    import pdfplumber

    text_parts = []
    with pdfplumber.open(filepath) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text_parts.append(page_text)
    return "\n".join(text_parts)


# ---------------------------------------------------------------------------
# Imagen  →  pytesseract (OCR local, gratis)
# ---------------------------------------------------------------------------

def _preprocess_for_ocr(filepath: str) -> Image.Image:
    """Preprocesa la imagen para maximizar la precisión del OCR."""
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
    except ImportError:
        pass

    img = Image.open(filepath).convert("RGB")
    img = img.convert("L")  # escala de grises

    # Aumentar resolución si la imagen es pequeña
    w, h = img.size
    if w < 1200:
        scale = 1200 / w
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)

    img = ImageEnhance.Contrast(img).enhance(1.8)
    img = img.filter(ImageFilter.SHARPEN)
    return img


def _extract_with_tesseract(filepath: str) -> str:
    """
    OCR local con pytesseract. Requiere Tesseract instalado.
    Windows: https://github.com/UB-Mannheim/tesseract/wiki
    Railway/Linux: instalado vía Dockerfile (apt tesseract-ocr tesseract-ocr-spa)
    """
    import pytesseract

    img = _preprocess_for_ocr(filepath)
    config = "--psm 3 --oem 3"

    # Intentar con español + inglés, luego solo inglés como fallback
    for lang in ("spa+eng", "eng"):
        try:
            text = pytesseract.image_to_string(img, lang=lang, config=config)
            if text.strip():
                return text
        except pytesseract.TesseractError:
            continue

    return pytesseract.image_to_string(img, config=config)


# ---------------------------------------------------------------------------
# Imagen  →  OpenAI GPT-4o Vision
# ---------------------------------------------------------------------------

_OPENAI_PROMPTS = {
    "FACTURA": """Sos un asistente experto en documentos fiscales argentinos.
Analizá esta imagen de una factura y extraé los datos. Devolvé ÚNICAMENTE un objeto JSON válido, sin markdown, con estas claves:
{
  "fecha": "DD/MM/YYYY",
  "tipo_comprobante": "A|B|C|M",
  "numero": "XXXX-XXXXXXXX",
  "proveedor": "razón social del emisor",
  "cuit": "XX-XXXXXXXX-X",
  "subtotal": "monto neto gravado como número",
  "iva_porcentaje": "21|10.5|27|0",
  "iva_monto": "monto iva como número",
  "total": "importe total como número",
  "cae": "número CAE de 14 dígitos",
  "vencimiento_cae": "DD/MM/YYYY",
  "observaciones": ""
}
Si algún campo no está visible, dejalo vacío (""). Devolvé solo el JSON.""",

    "REMITO": """Sos un experto en documentos comerciales.
Analizá esta imagen de un remito y extraé los datos. Devolvé ÚNICAMENTE un objeto JSON válido, sin markdown:
{
  "fecha": "DD/MM/YYYY",
  "numero": "número de remito",
  "orden_salida": "número de orden de salida (ej: DL-304)",
  "pack": "número de pack si existe",
  "proveedor": "razón social o nombre del emisor/origen",
  "destinatario": "nombre completo del destinatario",
  "destino_direccion": "dirección de entrega",
  "destino_localidad": "ciudad, provincia y CP",
  "articulos": "listado: Artículo | Descripción | Cant | Peso separados por \\n",
  "peso_total": "peso total en kg como número",
  "observaciones": ""
}
Si algún campo no está visible, dejalo vacío (""). Solo el JSON, sin markdown.""",

    "TICKET": """Sos un asistente experto en comprobantes de gastos.
Analizá esta imagen de un ticket/comprobante y extraé los datos. Devolvé ÚNICAMENTE un objeto JSON válido, sin markdown:
{
  "fecha": "DD/MM/YYYY",
  "comercio": "nombre del comercio o estación",
  "concepto": "descripción del gasto",
  "categoria": "NAFTA/COMBUSTIBLE|PEAJE|ESTACIONAMIENTO|ALIMENTACION|HOSPEDAJE|OTRO",
  "monto": "importe total como número",
  "observaciones": ""
}
Detectá la categoría según el contexto: YPF/Shell/Axion/Puma=NAFTA, Autopista=PEAJE, etc.
Si algún campo no está visible, dejalo vacío (""). Devolvé solo el JSON.""",
}


def _image_to_base64(filepath: str) -> tuple[str, str]:
    """Convierte imagen a base64 y devuelve (b64_string, media_type)."""
    ext = filepath.rsplit(".", 1)[-1].lower()

    media_map = {
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "webp": "image/webp",
        "gif": "image/gif",
    }

    if ext in media_map:
        with open(filepath, "rb") as f:
            return base64.b64encode(f.read()).decode(), media_map[ext]

    # HEIC y otros formatos: convertir a JPEG con Pillow
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
    except ImportError:
        pass

    img = Image.open(filepath).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92)
    return base64.b64encode(buf.getvalue()).decode(), "image/jpeg"


def _process_with_openai(filepath: str, doc_type: str) -> dict:
    from openai import OpenAI

    b64, media_type = _image_to_base64(filepath)
    prompt = _OPENAI_PROMPTS.get(doc_type, _OPENAI_PROMPTS["TICKET"])
    model = os.environ.get("OPENAI_MODEL", "gpt-4o")

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{media_type};base64,{b64}",
                            "detail": "high",
                        },
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ],
        max_tokens=600,
        temperature=0,
    )

    content = response.choices[0].message.content.strip()

    # Limpiar markdown si el modelo lo incluyó igual
    if content.startswith("```"):
        lines = content.split("\n")
        content = "\n".join(lines[1:-1]) if lines[-1].strip() == "```" else "\n".join(lines[1:])

    data = json.loads(content)
    data["tipo"] = doc_type
    return data


# ---------------------------------------------------------------------------
# Imagen  →  Google Cloud Vision API
# ---------------------------------------------------------------------------

def _extract_with_google_vision(filepath: str) -> str:
    from google.cloud import vision

    creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON", "")
    if creds_json:
        creds_dict = json.loads(creds_json)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(creds_dict, f)
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = f.name

    client = vision.ImageAnnotatorClient()

    with open(filepath, "rb") as f:
        content = f.read()

    image = vision.Image(content=content)
    response = client.document_text_detection(image=image)

    if response.error.message:
        raise RuntimeError(f"Google Vision API error: {response.error.message}")

    return response.full_text_annotation.text or ""
