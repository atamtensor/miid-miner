# CPU-only image for the hosted backend (2 vCPU / 4 GB RAM is enough).
#   docker build -t miid-miner .
#   docker build --build-arg WITH_ADAFACE=1 -t miid-miner .   # + local identity pre-check
# Run: see README "Run with Docker".
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN apt-get update && apt-get install -y --no-install-recommends git build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt requirements-adaface.txt ./
RUN pip install --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt

COPY . .
RUN pip install --no-deps -e .

ARG WITH_ADAFACE=0
RUN if [ "$WITH_ADAFACE" = "1" ]; then bash scripts/setup_adaface.sh; fi

ENV MIID_BACKEND=hosted \
    MIID_FACE_CHECK=auto \
    MIID_HOSTED_SPEND_FILE=/data/hosted_spend.json
VOLUME ["/data"]
EXPOSE 8091

HEALTHCHECK --interval=60s --timeout=10s --start-period=120s \
  CMD python -c "import socket,os; s=socket.create_connection(('127.0.0.1', int(os.environ.get('AXON_PORT','8091'))), 5)" || exit 1

ENTRYPOINT ["bash", "scripts/run_miner.sh"]
