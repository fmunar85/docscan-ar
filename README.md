# DocScan AR 📋

App web mobile-first para digitalizar **Facturas, Remitos y Tickets** de gastos.
Sube una foto o PDF → IA extrae los datos → se guardan automáticamente en **Google Sheets**.

---

## ✨ Funcionalidades

| Feature | Descripción |
|---------|-------------|
| 📱 Mobile-first | Diseño optimizado para celular, soporte cámara nativa |
| 🤖 OCR con IA | OpenAI GPT-4o Vision (principal) + Google Cloud Vision (alternativo) |
| 📄 PDF | Extracción de texto nativo con pdfplumber |
| 🗂️ Google Sheets | 3 hojas automáticas: **FACTURAS**, **REMITOS**, **TICKETS** |
| ✏️ Revisión manual | Formulario editable antes de guardar |
| 📜 Historial | Vista de los últimos registros por tipo |
| 🌙 Dark mode | Soporte automático según preferencia del sistema |
| PWA | Instalable como app en el home screen del celular |

---

## 🚀 Setup local

### 1. Clonar y crear entorno

```bash
git clone <tu-repo>
cd DocScanAR
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Mac/Linux:
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configurar variables de entorno

```bash
cp .env.example .env
# Editar .env con tus claves
```

### 3. Configurar Google Sheets

1. Ir a [Google Cloud Console](https://console.cloud.google.com)
2. Crear un proyecto o usar uno existente
3. Habilitar **Google Sheets API** y **Google Drive API**
4. Crear una **Service Account** → descargar el JSON de credenciales
5. Crear un **Google Spreadsheet** → compartirlo con el email de la Service Account (editor)
6. Copiar el ID del spreadsheet a `GOOGLE_SPREADSHEET_ID` en `.env`
7. Pegar el contenido completo del JSON en `GOOGLE_CREDENTIALS_JSON` en `.env`

### 4. Configurar OCR

**Opción A — OpenAI (recomendada):**
```
OPENAI_API_KEY=sk-...
```

**Opción B — Google Cloud Vision:**
- Habilitar **Cloud Vision API** en el mismo proyecto de Google
- Las mismas credenciales de la Service Account sirven

### 5. Ejecutar

```bash
flask run --port 5000
# o:
python app.py
```

Abrir `http://localhost:5000`

---

## 🚂 Deploy en Railway

### Variables de entorno en Railway

En el dashboard de Railway → tu servicio → **Variables**, agregar:

| Variable | Valor |
|----------|-------|
| `SECRET_KEY` | Clave aleatoria larga |
| `OPENAI_API_KEY` | `sk-...` |
| `GOOGLE_SPREADSHEET_ID` | ID del spreadsheet |
| `GOOGLE_CREDENTIALS_JSON` | JSON completo de la Service Account (string) |

### Estructura de Hojas en Google Sheets

Las hojas se crean automáticamente con las cabeceras correctas en el primer uso.

#### FACTURAS
| Fecha Registro | Fecha Doc. | Tipo | Número | Proveedor | CUIT | Subtotal | IVA % | IVA $ | Total | CAE | Venc. CAE | Observaciones |

#### REMITOS
| Fecha Registro | Fecha Doc. | Número | Proveedor | Destinatario | Artículos | Observaciones |

#### TICKETS
| Fecha Registro | Fecha Doc. | Comercio | Concepto | Categoría | Monto | Observaciones |

---

## 🗂️ Estructura del proyecto

```
DocScanAR/
├── app.py                   # Flask app principal
├── config.py                # Configuración
├── requirements.txt
├── Procfile                 # Railway / Heroku
├── railway.toml
├── .env.example
├── templates/
│   ├── base.html            # Layout base (navbar, toast)
│   ├── index.html           # Pantalla principal (upload + resultado)
│   └── history.html         # Historial de registros
├── static/
│   ├── css/style.css        # Estilos mobile-first
│   ├── js/app.js            # Lógica cliente (AJAX, formularios)
│   └── manifest.json        # PWA manifest
└── services/
    ├── ocr_service.py       # OCR: OpenAI / Google Vision / PDF
    ├── document_parser.py   # Parser regex para docs argentinos
    └── sheets_service.py    # Google Sheets API
```

---

## 📦 Tecnologías

- **Backend**: Python 3.11+, Flask 3
- **OCR**: OpenAI GPT-4o Vision / Google Cloud Vision
- **PDF**: pdfplumber
- **Imágenes**: Pillow, pillow-heif (HEIC de iPhone)
- **Google Sheets**: gspread + google-auth
- **Frontend**: Bootstrap 5.3, Font Awesome 6, Inter font
- **Deploy**: Railway + Gunicorn
