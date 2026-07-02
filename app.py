import os
import uuid
import json
from io import BytesIO
from flask import Flask, render_template, request, jsonify, send_file
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "cambiar-en-produccion-secret-key-4872")
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024  # 20 MB

# Carpeta de uploads: /tmp para Railway (efímero), uploads/ local
UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER", os.path.join("/tmp", "docscan_uploads"))
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp", "heic", "heif", "pdf"}


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


# ---------------------------------------------------------------------------
# Rutas
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/process", methods=["POST"])
def process():
    """Recibe archivo + tipo de documento, ejecuta OCR y devuelve JSON con los campos extraídos."""
    if "file" not in request.files:
        return jsonify({"success": False, "error": "No se seleccionó ningún archivo"}), 400

    file = request.files["file"]
    doc_type = request.form.get("doc_type", "AUTO").upper()

    if not file or file.filename == "":
        return jsonify({"success": False, "error": "Archivo vacío"}), 400

    if not allowed_file(file.filename):
        return jsonify({"success": False, "error": "Formato no permitido (JPG, PNG, PDF, WEBP, HEIC)"}), 400

    # Guardar con nombre único
    ext = file.filename.rsplit(".", 1)[1].lower()
    filename = f"{uuid.uuid4().hex}.{ext}"
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    file.save(filepath)

    try:
        from services.ocr_service import process_document
        result = process_document(filepath, doc_type)
        detected_type = result.get("tipo", doc_type)
        return jsonify({"success": True, "data": result, "doc_type": detected_type})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        # Borrar archivo inmediatamente (Railway no tiene storage persistente)
        try:
            os.remove(filepath)
        except OSError:
            pass


@app.route("/save", methods=["POST"])
def save():
    """Recibe datos del formulario y los guarda en Google Sheets."""
    payload = request.get_json(silent=True)
    if not payload:
        return jsonify({"success": False, "error": "Payload inválido"}), 400

    doc_type = payload.get("doc_type", "FACTURA").upper()
    doc_data = payload.get("data", {})

    try:
        from services.sheets_service import save_to_sheet
        result = save_to_sheet(doc_data, doc_type)
        if result["success"]:
            return jsonify({"success": True, "message": f"✅ Guardado en hoja {doc_type}", "row": result.get("row")})
        return jsonify({"success": False, "error": result.get("error", "Error desconocido")}), 500
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/export-local", methods=["POST"])
def export_local():
    """Genera archivo local descargable (XLSX/CSV) con los datos del documento."""
    payload = request.get_json(silent=True)
    if not payload:
        return jsonify({"success": False, "error": "Payload inválido"}), 400

    doc_type = payload.get("doc_type", "FACTURA").upper()
    doc_data = payload.get("data", {})
    file_format = payload.get("format", "xlsx")

    try:
        from services.local_export_service import build_local_export

        result = build_local_export(doc_data, doc_type, file_format)
        if not result.get("success"):
            return jsonify({"success": False, "error": result.get("error", "Error exportando")}), 500

        return send_file(
            BytesIO(result["bytes"]),
            as_attachment=True,
            download_name=result["filename"],
            mimetype=result["mimetype"],
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/history")
def history():
    doc_type = request.args.get("type", "FACTURA").upper()
    try:
        from services.sheets_service import get_recent_records
        records = get_recent_records(doc_type)
    except Exception:
        records = []
    return render_template("history.html", records=records, doc_type=doc_type)


@app.route("/health")
def health():
    return jsonify({"status": "ok", "app": "DocScan AR"})


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------

@app.errorhandler(413)
def too_large(e):
    return jsonify({"success": False, "error": "Archivo demasiado grande (máximo 20 MB)"}), 413


@app.errorhandler(404)
def not_found(e):
    return render_template("index.html"), 404


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug)
