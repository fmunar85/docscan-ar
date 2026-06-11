FROM python:3.11-slim

# Tesseract OCR con español e inglés (todo lo necesario para el OCR local)
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-spa \
    tesseract-ocr-eng \
    libglib2.0-0 \
    libpng-dev \
    libjpeg-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /tmp/docscan_uploads

EXPOSE 5000

CMD gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --timeout 120 --access-logfile -


# Copiar código
COPY . .

# Directorio temporal para uploads
RUN mkdir -p /tmp/docscan_uploads

EXPOSE 5000

CMD gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --timeout 120 --access-logfile -
