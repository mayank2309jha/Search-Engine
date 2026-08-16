# Multi-stage build. Build context is query-server/ itself (not the repo root)
# specifically so a huge sibling directory (../crawler/data/crawler.db is 2.1GB)
# can never accidentally end up inside the build context or the image -- real
# data is mounted in at runtime (see docker-compose.yml), never baked in.

# ---- Stage 1: install Python dependencies into an isolated venv ----
FROM python:3.13-slim AS builder

WORKDIR /build
COPY requirements.txt .
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
# CRITICAL: install the CPU-ONLY torch wheel first, from PyTorch's own index,
# before requirements.txt gets anywhere near it. Plain `pip install torch`
# from PyPI resolves to the CUDA-enabled build by default, which bundles
# several GB of NVIDIA libraries (libcublasLt.so, cuDNN, etc.) that a Mac --
# or any CPU-only deployment target, which is what app/semantic.py actually
# runs -- can never use. Hit this the hard way: the CUDA wheel's download
# filled the Docker Desktop VM's virtual disk (Docker.raw hit 16GB) and
# crashed a build with a layer-extraction I/O error, then took the host's
# free disk space down with it. Installing the matching CPU-only version here
# first means requirements.txt's own `torch==2.13.0` pin is already
# satisfied by the time pip gets to it, so it never reaches for the CUDA
# build at all.
RUN pip install --no-cache-dir torch==2.13.0 --index-url https://download.pytorch.org/whl/cpu
# pytest/ruff/coverage are still installed here since requirements.txt isn't
# split prod/dev yet -- a real, scoped follow-up, not done now to keep this
# change focused on Dockerizing rather than restructuring dependency files.
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download the sentence-transformer model and NLTK's stopword corpus at
# BUILD time, not first request -- so the container needs no outbound network
# access at runtime, and cold start doesn't pay a multi-second HF Hub download
# on top of the index-load/embedding-build cost it already pays (see
# docs-sde/current-state.md's measured ~3-minute startup at real data scale).
ENV HF_HOME=/opt/hf_cache
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"
# nltk.download() (and the CLI `python -m nltk.downloader`) both hit an
# intermittent "Security Violation: Unauthorized path ...stopwords.zip.tmp"
# inside this specific build context -- reproduced twice, not just once, and
# not reproducible in isolation outside the multi-stage build, so root cause
# wasn't chased further. Worked around by bypassing nltk's downloader class
# entirely: fetch and extract the same zip nltk itself would, with plain
# stdlib calls only. Verified this produces the same 34-language stopwords
# corpus nltk.download() does when it succeeds.
RUN python -c "\
import urllib.request, zipfile, io, os; \
url = 'https://raw.githubusercontent.com/nltk/nltk_data/gh-pages/packages/corpora/stopwords.zip'; \
os.makedirs('/opt/nltk_data/corpora', exist_ok=True); \
data = urllib.request.urlopen(url, timeout=30).read(); \
zipfile.ZipFile(io.BytesIO(data)).extractall('/opt/nltk_data/corpora')"

# ---- Stage 2: runtime image ----
FROM python:3.13-slim AS runtime

# libgomp1: torch's CPU backend links against it at runtime; slim base doesn't
# ship it by default.
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /opt/nltk_data /opt/nltk_data
# NOT /root/.cache/huggingface -- that was the bug. The container runs as a
# non-root `appuser` below, which can't read root's home directory, so the
# pre-downloaded model was invisible at runtime and the app fell through to
# a live network fetch that HF_HUB_OFFLINE=1 then correctly blocked,
# crashing with "couldn't connect to huggingface.co ... couldn't find them
# in the cached files." HF_HOME is set explicitly (both here and at
# download time above) to a neutral path any user can read, sidestepping
# whose home directory the cache happens to live under entirely.
COPY --from=builder /opt/hf_cache /opt/hf_cache

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH=/app/query-server \
    PYTHONUNBUFFERED=1 \
    NLTK_DATA=/opt/nltk_data \
    HF_HOME=/opt/hf_cache \
    HF_HUB_OFFLINE=1

# Runs as non-root -- standard hardening, and there's no reason this process
# needs root once dependencies are installed.
RUN useradd --create-home --uid 1000 appuser
WORKDIR /app/query-server
COPY app ./app
COPY static ./static
RUN mkdir -p data && chown -R appuser:appuser /app /opt/hf_cache
USER appuser

EXPOSE 8000

# app/main.py hard-requires ../data/index.bin at import time (see
# docs-sde/architecture.md's request-lifecycle section) -- it is NOT baked
# into this image; mount it (and ../data/crawler.db, optional) via
# docker-compose.yml before running this container standalone.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
