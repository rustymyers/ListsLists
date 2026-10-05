FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN useradd --create-home --uid 10001 app
WORKDIR /app
COPY pyproject.toml README.md ./
COPY app ./app
COPY migrations ./migrations
COPY alembic.ini ./
COPY scripts/entrypoint.sh /entrypoint.sh
RUN pip install --no-cache-dir . && chmod +x /entrypoint.sh && mkdir -p /data /secrets && chown -R app:app /app /data /secrets
USER app
EXPOSE 8000
ENTRYPOINT ["/entrypoint.sh"]
