"""
Servicio OCR de DocScan AR
===========================
Estrategia (en orden de prioridad):
  1. OpenAI GPT-4o Vision  → más preciso, devuelve JSON estructurado directamente.
  2. Google Cloud Vision   → extrae texto crudo; luego se parsea con document_parser.
  3. pdfplumber            → para archivos PDF (sin visión; extrae texto nativo).

Se intenta automáticamente según las variables de entorno disponibles.
"""
import os
import io
import json
import base64
import tempfile

from PIL import Image

from services.document_parser import parse_document


# ---------------------------------------------------------------------------
# Punto de entrada principal
# ---------------------------------------------------------------------------

def process_document(filepath: str, doc_type: str) -> dict:
    """
    Procesa el archivo y devuelve un dict con los campos extraídos.
    Lanza Exception si no hay servicio configurado o si falla todo.
    """
    ext = filepath.rsplit(".", 1)[-1].lower()

    # PDF: extraer texto nativo primero
    if ext == "pdf":
        raw_text = _extract_pdf_text(filepath)
        return parse_document(raw_text, doc_type)

    # Imagen: preferir OpenAI (devuelve JSON directo)
    openai_key = os.environ.get("OPENAI_API_KEY", "")
    google_creds = os.environ.get("GOOGLE_CREDENTIALS_JSON", "")

    if openai_key:
        return _process_with_openai(filepath, doc_type)

    if google_creds or os.path.exists("credentials.json"):
        raw_text = _extract_with_google_vision(filepath)
        return parse_document(raw_text, doc_type)

    raise RuntimeError(
        "No hay servicio OCR configurado. "
        "Definí OPENAI_API_KEY o GOOGLE_CREDENTIALS_JSON en las variables de entorno."
    )


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

    "REMITO": """Sos un asistente experto en documentos comerciales argentinos.
Analizá esta imagen de un remito y extraé los datos. Devolvé ÚNICAMENTE un objeto JSON válido, sin markdown:
{
  "fecha": "DD/MM/YYYY",
  "numero": "XXXX-XXXXXXXX",
  "proveedor": "razón social del emisor",
  "destinatario": "nombre del destinatario",
  "articulos": "listado de artículos con cantidades separados por \\n",
  "observaciones": ""
}
Si algún campo no está visible, dejalo vacío (""). Devolvé solo el JSON.""",

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
