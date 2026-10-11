FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DEFAULT_TIMEOUT=120 PIP_RETRIES=5
WORKDIR /app
COPY pyproject.toml requirements.txt ./
COPY services ./services
RUN pip install --no-cache-dir --default-timeout=120 --retries=5 .
EXPOSE 8000
CMD ["uvicorn", "services.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
