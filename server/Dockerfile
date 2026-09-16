FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv/app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
# Site vitrine : feuille de style, polices (copiées depuis ui/fonts), logo 512 px et favicon.
COPY static ./static

# Utilisateur non root ; /data (volume) lui appartient dès la création du volume.
RUN useradd --system --uid 1000 --create-home app \
    && mkdir -p /data && chown app:app /data
USER app
VOLUME ["/data"]
EXPOSE 8000

# Un seul worker : les salons vivent en mémoire. --proxy-headers : IP réelle derrière Traefik (Dokploy), mais
# seuls les proxys de FORWARDED_ALLOW_IPS (défaut : réseaux Docker 172.16.0.0/12) ont le droit de la déclarer,
# sinon n'importe quel client forgerait X-Forwarded-For et contournerait la limitation de débit.
# --ws-max-size : un message WebSocket dépasse rarement quelques centaines d'octets (16 Ko côté applicatif).
# `exec` : uvicorn reste le processus 1 (signaux d'arrêt reçus directement).
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port 8000 \
     --proxy-headers --forwarded-allow-ips \"${FORWARDED_ALLOW_IPS:-172.16.0.0/12}\" \
     --ws-max-size 65536 --ws-ping-interval 20 --ws-ping-timeout 20"]
