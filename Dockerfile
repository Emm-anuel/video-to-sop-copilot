# Imagen de la API (sopvid). Python 3.11 fijado a parche y distro.
FROM python:3.11.17-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# ffmpeg/ffprobe para la etapa de medios (duración, audio, fotogramas). Versión de Debian bookworm.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
# torch solo CPU (MiniLM, ADR-012): el wheel de PyPI para Linux arrastra CUDA (varios GB). Se
# instala primero desde el índice CPU de PyTorch, con la versión fijada en pyproject.toml; después
# `pip install .` lo da por cumplido (2.13.0+cpu satisface torch==2.13.0).
RUN pip install --index-url https://download.pytorch.org/whl/cpu \
        "$(grep -o 'torch==[0-9.]*' pyproject.toml)"
COPY src ./src
RUN pip install . \
    && ! pip list 2>/dev/null | grep -i -E '^(nvidia|cuda|triton)'

COPY alembic.ini ./
COPY migrations ./migrations

RUN useradd --create-home --uid 1000 app \
    && mkdir -p /app/models \
    && chown app:app /app/models
USER app

# Pesos de MiniLM: se descargan la primera vez al volumen montado aquí, no a la imagen.
ENV EMBEDDER_CACHE_DIR=/app/models/embedder

EXPOSE 8000

CMD ["uvicorn", "sopvid.plataforma.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
