FROM python:3.12-slim

ARG IMAGE_TAG
WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    IMAGE_TAG=${IMAGE_TAG}

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/model_train ./src/model_train

CMD ["python", "-m", "model_train.main"]
