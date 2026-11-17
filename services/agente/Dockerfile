# 1) Interfaz React (Vite + shadcn/ui)
FROM node:22-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

# 2) API FastAPI que sirve tambien la interfaz (mismo origen: sin CORS)
FROM python:3.12-slim
WORKDIR /srv
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY --from=web /web/dist ./static
RUN useradd --system --uid 1001 agente
USER agente
ENV PYTHONUNBUFFERED=1
EXPOSE 8000
# --proxy-headers: la IP real del cliente llega desde Traefik (limite de intentos de login).
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips=\"${FORWARDED_ALLOW_IPS:-127.0.0.1}\""]
