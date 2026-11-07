# Author: Tishneet
FROM python:3.12-slim
WORKDIR /app
COPY backend/requirements*.txt /app/backend/
RUN pip install --no-cache-dir -r backend/requirements-lock.txt
COPY backend /app/backend
COPY scripts /app/scripts
ENV PYTHONUNBUFFERED=1 PYTHONPATH=/app:/app/backend
CMD ["python", "-m", "scripts.run_integration", "worker"]
