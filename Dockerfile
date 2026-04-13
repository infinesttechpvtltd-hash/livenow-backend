FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PORT=8001

CMD ["sh", "-c", "python -c \"import os; print('PORT=' + os.environ.get('PORT','8001'))\" && uvicorn server:app --host 0.0.0.0 --port $PORT"]
