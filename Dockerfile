FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY rag_saas ./rag_saas
RUN pip install --no-cache-dir .
EXPOSE 8000
CMD ["sh", "-c", "python -m rag_saas migrate && uvicorn rag_saas.api:app_from_env --factory --host 0.0.0.0 --port 8000"]
