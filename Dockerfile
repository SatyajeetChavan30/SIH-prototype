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

# Expose Streamlit dashboard port
EXPOSE 8501

# Default command launches CLI help or Streamlit dashboard
CMD ["streamlit", "run", "jalraksha/dashboard/app.py", "--server.port=8501", "--server.address=0.0.0.0"]
