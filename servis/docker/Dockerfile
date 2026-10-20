# The score-reading service on a CPU-only server. Build from the folder hazirla.py assembles (code + weights):
#     docker build -t nota-okuma:v24 .
FROM python:3.10-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    OMP_NUM_THREADS=4 \
    MKL_NUM_THREADS=4 \
    OMR_PORT=8765

# libgl1/libglib2.0: the non-headless OpenCV that the OCR dependency pulls in links them
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements-cpu.txt .
# two OpenCV wheels share the cv2 folder; the last line puts back the headless one the service was tested with
# the CPU index alone serves a typing_extensions wheel with broken metadata, so PyPI stays reachable
RUN pip install --index-url https://download.pytorch.org/whl/cpu --extra-index-url https://pypi.org/simple \
        torch==2.5.1+cpu torchvision==0.20.1+cpu \
    && pip install -r requirements-cpu.txt \
    && pip install --no-deps --force-reinstall opencv-python-headless==5.0.0.93

COPY kod/ /app/
RUN useradd --create-home --uid 10001 okuyucu && chown -R okuyucu /app
USER okuyucu

EXPOSE 8765
# the model loads at start-up (tens of seconds on a CPU); /v1/saglik answers once it is in memory
HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/v1/saglik', timeout=8)"
# one worker: jobs live in that process's memory and the model reads one page at a time
CMD ["sh", "-c", "exec uvicorn servis.nota_servisi:app --host 0.0.0.0 --port ${OMR_PORT} --workers 1"]
