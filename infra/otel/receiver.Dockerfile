FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir 'fastapi>=0.115,<1' 'uvicorn>=0.30,<1' 'opentelemetry-proto>=1.25,<2' 'protobuf>=5,<7'
COPY services/telemetry /app/services/telemetry
RUN touch /app/services/__init__.py
ENV QA_DATA_DIR=/app/data QA_ALLOW_PUBLIC_OTLP=1
USER 65534:65534
EXPOSE 4319
CMD ["python", "-m", "uvicorn", "services.telemetry.receiver:app", "--host", "0.0.0.0", "--port", "4319"]
