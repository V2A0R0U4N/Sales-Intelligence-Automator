# Use the official Microsoft Playwright image which includes browser dependencies
FROM mcr.microsoft.com/playwright/python:v1.45.0-jammy

# Set the working directory
WORKDIR /app

# Copy requirements and install them securely
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# IMPORTANT FOR OPENSHIFT: 
# OpenShift assigns arbitrary user IDs. We must ensure the app directory 
# and Playwright paths are writable by the root group (which the arbitrary user will belong to).
RUN chgrp -R 0 /app && chmod -R g=u /app
RUN chmod -R 777 /ms-playwright || true

# Expose the FastAPI port
EXPOSE 8000

# Start the application using Uvicorn
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
