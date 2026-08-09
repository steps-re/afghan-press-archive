# The search index ships INSIDE the image: 509MB SQLite + 214MB vectors. That keeps the service
# stateless and scale-to-zero with no database to run, at the cost of a redeploy whenever the
# corpus changes -- which is roughly never, since the corpus is a finished historical artefact.
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends libsqlite3-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# data first: it never changes, so a code edit rebuilds only the layer above it
COPY data /data
COPY app /srv/app

ENV ADL_DATA=/data PYTHONUNBUFFERED=1
EXPOSE 8080
# One worker: the vectors are ~214MB resident and a second worker would double that for no gain,
# since search is I/O- and BLAS-bound rather than GIL-bound.
CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080} --workers 1
