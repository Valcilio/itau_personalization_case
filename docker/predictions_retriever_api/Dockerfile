FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/predictions_retriever_api ./src/predictions_retriever_api
COPY data ./data
COPY model ./model

EXPOSE 8000

CMD ["uvicorn", "predictions_retriever_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
