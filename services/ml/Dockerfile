# Dos imagenes desde este archivo:
#   - produccion (etapa final, la que usa el servicio `ml`): API y entrenamiento con las librerias del ganador.
#   - benchmark (`target: benchmark`, servicio `ml-benchmark`): ademas TODAS las herramientas de la comparativa.
FROM python:3.12-slim AS base
WORKDIR /app
ENV PYTHONUNBUFFERED=1 MODEL_DIR=/app/models DATA_DIR=/app/data ANALISIS_DIR=/app/analisis
# libgomp1: OpenMP para LightGBM, XGBoost y scikit-learn.
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements-dev.txt
RUN mkdir -p /app/models /app/data /app/analisis
EXPOSE 8000

FROM base AS benchmark
COPY requirements-benchmark.txt ./
RUN pip install --no-cache-dir -r requirements-benchmark.txt
COPY mlsvc ./mlsvc
COPY tests ./tests
CMD ["python", "-m", "mlsvc.demanda.benchmark", "--source", "dwh"]

FROM base AS produccion
COPY mlsvc ./mlsvc
COPY tests ./tests
CMD ["uvicorn", "mlsvc.serve:app", "--host", "0.0.0.0", "--port", "8000"]
