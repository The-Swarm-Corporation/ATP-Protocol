FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONHASHSEED=random \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN adduser --disabled-password --gecos "" appuser

COPY requirements.txt .

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        gcc \
        build-essential \
        curl \
        && \
    python -m venv /app/venv && \
    . /app/venv/bin/activate && \
    pip install --no-cache-dir -r requirements.txt && \
    apt-get purge -y --auto-remove gcc build-essential && \
    apt-get autoremove -y && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

COPY . /app/

COPY launch_gunicorn.sh /app/launch_gunicorn.sh
RUN chmod +x /app/launch_gunicorn.sh

RUN chown -R appuser:appuser /app

USER appuser

ENV PATH="/app/venv/bin:$PATH"

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

CMD ["/app/launch_gunicorn.sh"]

