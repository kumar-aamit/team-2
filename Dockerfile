# Use the official slim Python image
FROM python:3.10-slim

# Set environment variables to ensure Python output is sent straight to terminal
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set work directory
WORKDIR /app

# Install system dependencies (if any) and then Python dependencies
RUN apt-get update && apt-get install -y --no-install-recommends gcc && \
    rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Create the data directory for SQLite (if it doesn't exist) and set permissions
RUN mkdir -p /data && chmod 777 /data

# Expose the port (will be overridden by docker-compose)
EXPOSE 8742

# Run the application
CMD ["python", "main.py"]