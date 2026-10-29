# Cicada's relay (G132 phase 3a): one image, the hosted default and the self-host option alike.
#
#   docker build -t cicada-relay relay
#   docker run -d --name cicada-relay -p 8443:8443 -v cicada-relay-data:/data \
#     --read-only --cap-drop ALL --security-opt no-new-privileges cicada-relay
#
# On a public address the relay terminates TLS for its own name only: mount the certificate and set
#   -v /etc/cicada-relay/tls:/tls:ro -e RELAY_TLS_CERT=/tls/fullchain.pem -e RELAY_TLS_KEY=/tls/privkey.pem
# Every bound is a RELAY_* variable (cicada_relay/config.py). The mailbox holds ciphertext only; /data is a cache the
# devices can always rebuild, except transactions still in flight (which also stay in their device's outbox).
FROM python:3.12.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    RELAY_HOST=0.0.0.0 \
    RELAY_PORT=8443 \
    RELAY_DB_PATH=/data/relay.db

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --no-compile --require-hashes --only-binary=:all: -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt \
    && useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin relay \
    && mkdir /data && chown 10001 /data

COPY cicada_relay /app/cicada_relay
WORKDIR /app
USER 10001
VOLUME /data
EXPOSE 8443
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 CMD ["python", "-m", "cicada_relay.health"]
CMD ["python", "-m", "cicada_relay"]
