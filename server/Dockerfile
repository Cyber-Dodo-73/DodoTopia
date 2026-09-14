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

# Un seul worker : les salons vivent en mémoire. --proxy-headers : IP réelle derrière Traefik (Dokploy).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips=*", \
     "--ws-ping-interval", "20", "--ws-ping-timeout", "20"]
