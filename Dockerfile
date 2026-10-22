# Kintsugi workspace as a small web service. Build: docker build -t kintsugi .
# Run:   docker run -p 8765:8765 -e KINTSUGI_TOKEN=<long random string> -e KINTSUGI_API_KEY=<your model key> -v kintsugi-data:/data kintsugi
FROM python:3.12-slim

# util-linux (unshare, mount) lets the code sandbox isolate agent code when the platform allows it.
RUN apt-get update && apt-get install -y --no-install-recommends util-linux && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

# The service listens on $PORT (hosting platforms set it). The access token MUST be provided: the server refuses
# to listen on a network address with a short or missing KINTSUGI_TOKEN.
ENV KINTSUGI_WORKSPACE=/data \
    KINTSUGI_HOST=0.0.0.0 \
    PORT=8765 \
    KINTSUGI_TRUST_PROXY=1
VOLUME /data
EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/healthz' % os.environ.get('PORT','8765'), timeout=4)"

CMD ["kintsugi", "workspace", "serve"]
