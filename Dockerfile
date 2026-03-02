FROM python:3.10-slim

WORKDIR /app

# Install system dependencies needed for Playwright Chromium
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 libnss3 libxcb1 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm-common libdrm2 libxkbcommon0 \
    libxcomposite1 libxdamage1 libxfixes3 \
    libxrandr2 libgbm1 libasound2 \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install
COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt
RUN playwright install chromium
RUN playwright install-deps chromium

# Copy application files
COPY google_maps_scraper.py .
COPY app.py .
COPY templates/ templates/

# Create output directory for mounted volumes
RUN mkdir -p /app/output

EXPOSE 5000

CMD ["python", "app.py"]
