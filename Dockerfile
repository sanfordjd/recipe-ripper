# This image includes Chromium and its Linux dependencies.
# Keep its Playwright release matched to requirements-hosting.txt.
FROM mcr.microsoft.com/playwright/python:v1.65.2-noble@sha256:38dd67fc654b56b3cba611e4c8eb71cd33750e1cd29eea2a5dc00b484817a75f

USER root
WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    HOST=0.0.0.0 \
    PORT=8000 \
    DATABASE_PATH=/var/data/recipes.sqlite3 \
    COOKIE_SECURE=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends gosu \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 recipe \
    && useradd --uid 10001 --gid recipe --create-home --shell /usr/sbin/nologin recipe

COPY requirements-hosting.txt ./requirements-hosting.txt
RUN python -m pip install --no-cache-dir --disable-pip-version-check -r requirements-hosting.txt

COPY app.py ./app.py
COPY templates/index.html ./templates/index.html
COPY docker-entrypoint.sh /usr/local/bin/recipe-entrypoint
RUN sed -i 's/\r$//' /usr/local/bin/recipe-entrypoint \
    && chmod 755 /usr/local/bin/recipe-entrypoint \
    && install -d -m 700 -o recipe -g recipe /var/data

EXPOSE 8000
ENTRYPOINT ["/usr/local/bin/recipe-entrypoint"]
CMD ["python", "-B", "app.py"]
