FROM python:3.11-slim

LABEL maintainer="galileo1"

# Create a non-root user `adduser` and group `addgroup`
RUN groupadd -g 1001 appuser && useradd -u 1001 -g appuser -s /bin/bash -m appuser

WORKDIR /app

# Copy requirements and install as root
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app files and change ownership
COPY ./tunnel_init.py .
RUN chown -R appuser:appuser /app

# Drop root privileges
USER 1001:1001

# Run your script as the default entrypoint
CMD ["python", "tunnel_init.py"]