"""
Configuración centralizada de DocScan AR.
Las variables se cargan desde .env (local) o variables de entorno (Railway).
"""
import os


class Config:
    # Flask
    SECRET_KEY: str = os.environ.get("SECRET_KEY", "cambiar-en-produccion")
    FLASK_DEBUG: bool = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    MAX_CONTENT_LENGTH: int = 20 * 1024 * 1024  # 20 MB

    # Upload
    UPLOAD_FOLDER: str = os.environ.get("UPLOAD_FOLDER", "/tmp/docscan_uploads")

    # OCR — al menos uno de los dos debe estar configurado
    OPENAI_API_KEY: str = os.environ.get("OPENAI_API_KEY", "")
    OPENAI_MODEL: str = os.environ.get("OPENAI_MODEL", "gpt-4o")

    # Google Cloud (Vision API + Sheets con la misma cuenta de servicio)
    GOOGLE_CREDENTIALS_JSON: str = os.environ.get("GOOGLE_CREDENTIALS_JSON", "")

    # Google Sheets
    GOOGLE_SPREADSHEET_ID: str = os.environ.get("GOOGLE_SPREADSHEET_ID", "")

    # Nombres de las hojas (se crean automáticamente si no existen)
    SHEET_FACTURAS: str = "FACTURAS"
    SHEET_REMITOS: str = "REMITOS"
    SHEET_TICKETS: str = "TICKETS"
