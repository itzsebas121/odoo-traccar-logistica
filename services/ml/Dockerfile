FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 MODEL_DIR=/app/models DATA_DIR=/app/data
COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements-dev.txt
COPY mlsvc ./mlsvc
COPY tests ./tests
RUN mkdir -p /app/models /app/data
EXPOSE 8000
CMD ["uvicorn", "mlsvc.serve:app", "--host", "0.0.0.0", "--port", "8000"]
