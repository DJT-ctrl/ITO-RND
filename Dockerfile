# Image for the FastAPI app (api.main:app) — used by both the `api` and the
# one-shot `migrate` services in docker-compose.yml. Kept deliberately small:
# every runtime dependency in requirements.txt ships a manylinux wheel
# (psycopg[binary], numpy, pandas, scikit-learn, google-genai, ...), so no
# compiler/system build chain is needed on top of python:slim.

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install deps first (their own layer) so app-code changes don't bust the
# pip cache on every rebuild.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application packages. The build context is trimmed by
# .dockerignore (no data/, tests/, dashboard/, .venv/, .git/, ...), so this
# only pulls in the code the API actually imports at runtime.
COPY . .

# Run as an unprivileged user — the container never needs root at runtime.
RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Overridden by the `migrate` service; this is the default (serve the API).
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
