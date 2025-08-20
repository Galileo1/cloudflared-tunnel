FROM python:3.11-slim

LABEL maintainer="galileo1"

# Create a non-root user `adduser` and group `addgroup`
RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser

WORKDIR /app

# Copy requirements and install as root
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app files and change ownership
COPY ./tunnel_init.py .
RUN chown -R appuser:appgroup /app

# Switch to non-root
USER appuser

# Run your script as the default entrypoint
CMD ["python", "tunnel_init.py"]