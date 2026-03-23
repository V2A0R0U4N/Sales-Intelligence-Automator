# ─── Build Stage ───
FROM python:3.11-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ─── Runtime Stage ───
FROM python:3.11-slim

# Install runtime deps + Playwright browser deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from builder
COPY --from=builder /install /usr/local

# Install Playwright browsers
RUN playwright install chromium --with-deps

# Create non-root user
RUN useradd -m -r salesintel && mkdir -p /app && chown salesintel:salesintel /app
WORKDIR /app

# Copy application
COPY --chown=salesintel:salesintel . .

USER salesintel

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
