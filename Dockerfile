FROM python:3.12-slim

# rasterio trae GDAL propio pero enlaza contra libexpat del sistema
RUN apt-get update && apt-get install -y --no-install-recommends \
      libexpat1 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
      geopandas==1.1.4 \
      shapely==2.1.2 \
      pyproj==3.7.2 \
      pyogrio==0.12.0 \
      rasterio==1.4.3 \
      pandas==2.3.3 \
      pyarrow==21.0.0 \
      requests==2.32.5 \
      pyyaml==6.0.2

WORKDIR /work
