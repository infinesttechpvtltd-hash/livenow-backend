FROM python:3.11-slim

WORKDIR /app

# Cache bust v2
ARG CACHEBUST=2

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && pip install email-validator

COPY . .

ENV PORT=8001

CMD ["sh", "-c", "uvicorn server:app --host 0.0.0.0 --port $PORT"]
