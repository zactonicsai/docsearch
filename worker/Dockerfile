FROM python:3.13-slim

# System deps for unstructured document parsing:
#   poppler-utils  → PDF text extraction (pdftotext)
#   tesseract-ocr  → OCR for images and scanned PDFs
#   libreoffice    → DOC/DOCX/PPT/XLS conversion
#   pandoc         → RTF, EPUB, ORG conversion
#   libmagic1      → file-type detection (python-magic)
#   libxml2-dev / libxslt1-dev → lxml for HTML/XML parsing
RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils \
    tesseract-ocr \
    tesseract-ocr-eng \
    libreoffice \
    pandoc \
    libmagic1 \
    libxml2-dev \
    libxslt1-dev \
    libgl1 \
    libglib2.0-0 \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY shared.py activities.py workflows.py run_worker.py ./

ENV DO_NOT_TRACK=true

RUN mkdir -p /data/uploads

CMD ["python", "run_worker.py"]
