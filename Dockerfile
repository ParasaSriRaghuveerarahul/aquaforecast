FROM python:3.12-slim
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir -r backend/requirements.txt
WORKDIR /app/backend
CMD ["sh","-c","uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
