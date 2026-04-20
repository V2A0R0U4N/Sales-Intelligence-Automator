# Use the official Microsoft Playwright image which includes browser dependencies
FROM mcr.microsoft.com/playwright/python:v1.45.0-jammy

# Set the working directory
WORKDIR /app

# Copy requirements and install them securely
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# IMPORTANT FOR OPENSHIFT / RAILWAY:
# OpenShift assigns arbitrary user IDs. Railway uses dynamic ports.
# We must ensure the app directory and Playwright paths are writable.
RUN chgrp -R 0 /app && chmod -R g=u /app
RUN chmod -R 777 /ms-playwright || true

# Railway assigns PORT dynamically; default to 8000 for local dev
ENV PORT=8000
EXPOSE ${PORT}

# Start the application
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
