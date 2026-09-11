# Build context is the repo ROOT (set in docker-compose via `context: .`).
# This image runs either the FastAPI API or the Celery worker, selected by CMD.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    JALRAKSHA_DATA_DIR=/data

# GDAL/GEOS for GeoTIFF + Shapefile I/O used by the pipeline.
RUN apt-get update && apt-get install -y --no-install-recommends \
    gdal-bin libgdal-dev gcc g++ \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install service deps first (better layer caching).
COPY services/api/requirements.txt /app/services/api/requirements.txt
RUN pip install --no-cache-dir -r /app/services/api/requirements.txt

# Install the jalraksha package (editable) + its deps.
COPY pyproject.toml /app/pyproject.toml
COPY jalraksha /app/jalraksha
RUN pip install --no-cache-dir -e .

# Service source.
COPY services/api/jalraksha_service /app/services/api/jalraksha_service

# Default: API server. The worker overrides CMD (see docker-compose.yml).
EXPOSE 8000
CMD ["uvicorn", "jalraksha_service.main:app", "--host", "0.0.0.0", "--port", "8000"]
