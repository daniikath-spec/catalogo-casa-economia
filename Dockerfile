FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends libzbar0 libglib2.0-0 libgl1 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py processor.py ./
COPY static ./static
ENV DATA_DIR=/data U2NET_HOME=/models PYTHONUNBUFFERED=1
RUN mkdir -p /data /models
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
