FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 MPLCONFIGDIR=/tmp/mpl
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install ".[web]" && useradd --create-home --uid 10001 app
USER app
EXPOSE 8000
# Two workers: one analysis takes a second or two of CPU. Uploads are limited to 60 MB by the app.
CMD ["gunicorn", "--workers", "2", "--timeout", "120", "--bind", "0.0.0.0:8000", "--access-logfile", "-", "mbhf.web:create_app()"]
