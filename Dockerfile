# JalRaksha Dam-Break Modelling System Dockerfile
FROM python:3.11-slim

# Install system dependencies (GDAL/GEOS for GeoTIFF and Shapefile processing)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gdal-bin \
    libgdal-dev \
    gcc \
    g++ \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirement / pyproject files
COPY pyproject.toml /app/
COPY jalraksha /app/jalraksha

# Install JalRaksha and dependencies
RUN pip install --no-cache-dir -e .

# This image packages the jalraksha library and its CLI only.
#
# It previously launched a Streamlit dashboard on 8501; that dashboard has been
# removed, superseded by the React frontend + FastAPI service. Those are built
# by frontend/Dockerfile and services/api/Dockerfile respectively and wired up
# in docker-compose.yml — this file is not referenced by compose at all.
#
# Default to the CLI's help rather than a server: the image has no web
# component to serve, and silently exposing a port nothing listens on is worse
# than doing nothing.
CMD ["python", "-m", "jalraksha.cli", "--help"]
