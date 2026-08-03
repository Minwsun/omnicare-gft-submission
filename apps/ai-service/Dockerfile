FROM python:3.12-slim
WORKDIR /app
COPY apps/ai-service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY apps/ai-service/app ./app
HEALTHCHECK --interval=10s --timeout=5s --retries=10 CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
