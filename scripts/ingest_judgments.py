"""
Stream-ingest Indian SC judgments from GCS zip into Pinecone.

Design:
- Zero disk space: GCSSeekable wraps blob via byte-range reads.
- Vertex AI text-embedding-005 (768-dim) via REST API — runs within GCP
  network (no outbound internet needed), high quota with billing enabled,
  batch up to 250 texts per call.
- Parallel shards: CLOUD_RUN_TASK_INDEX / CLOUD_RUN_TASK_COUNT.
- Checkpoint: GCS JSON file per task for resume on restart.

Cost: FREE with Vertex AI (embeddings are billed at $0.00002/1k chars, but
text-embedding-005 is actually free up to 1 million chars/month on Vertex AI
with billing enabled — well within limits for 26k judgments).

Usage:
  python scripts/ingest_judgments.py              # GCS (default)
  python scripts/ingest_judgments.py --limit 500  # quick test
  python scripts/ingest_judgments.py --zip path   # local zip
"""
import argparse
import io
import json
import os
import random
import re
import sys
import time
import zipfile
from pathlib import Path

import httpx
import google.auth
import google.auth.transport.requests
from pinecone import Pinecone, ServerlessSpec
from pypdf import PdfReader
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

PINECONE_KEY   = os.getenv("PINECONE_API_KEY", "")
PINECONE_HOST  = os.getenv("PINECONE_HOST", "")
PINECONE_INDEX = os.getenv("PINECONE_INDEX", "sahayak-judgments")
GCS_ZIP_URI    = os.getenv("GCS_ZIP_URI", "gs://sahaiyak/archive.zip")
GCP_PROJECT    = os.getenv("GOOGLE_CLOUD_PROJECT", "sahaiyak")
VERTEX_REGION  = "us-central1"
EMBED_MODEL    = "text-embedding-005"

PINECONE_DIM  = 768
EMBED_BATCH   = 20     # texts per Vertex AI call (20 × ~460 tokens = ~9200, under 20k limit)
UPSERT_BATCH  = 100    # vectors per Pinecone upsert
MAX_CHARS     = 800    # chars per PDF (< 230 tokens; 20 × 230 = 4600 tokens total per call)
VERTEX_RPM    = 1000   # Vertex AI quota (conservative)


# ── GCS seekable wrapper ──────────────────────────────────────────────────────

class _GCSSeekable:
    """Wrap a GCS blob as a seekable file via range reads (no full download)."""
    def __init__(self, blob):
        self._blob = blob
        self._pos  = 0
        self._size = blob.size

    def read(self, n=-1):
        if self._pos >= self._size:
            return b""
        start = self._pos
        end   = (self._size - 1) if n == -1 else min(self._pos + n - 1, self._size - 1)
        if start > end:
            return b""
        data = self._blob.download_as_bytes(start=start, end=end)
        self._pos += len(data)
        return data

    def seek(self, pos, whence=0):
        if whence == 0:   self._pos = pos
        elif whence == 1: self._pos += pos
        elif whence == 2: self._pos = self._size + pos
        self._pos = max(0, min(self._pos, self._size))
        return self._pos

    def tell(self):     return self._pos
    def seekable(self): return True
    def readable(self): return True

    def readinto(self, b):
        data = self.read(len(b))
        n = len(data)
        b[:n] = data
        return n


# ── PDF helpers ───────────────────────────────────────────────────────────────

def _year(path: str) -> str:
    m = re.search(r'(\d{4})', path)
    return m.group(1) if m else "2000"

def _case_name(path: str) -> str:
    name = Path(path).stem
    name = re.sub(r'_on_\d.*', '', name)
    return name.replace('_', ' ').strip()[:120]

def _outcome(text: str) -> str:
    t = text.lower()
    if any(w in t for w in ['petition dismissed', 'appeal dismissed', 'dismissed']):
        return 'DISMISSED'
    if any(w in t for w in ['appeal allowed', 'petition allowed', 'allowed', 'granted']):
        return 'ALLOWED'
    if any(w in t for w in ['upheld', 'affirmed', 'confirmed']):
        return 'UPHELD'
    if any(w in t for w in ['partly allowed', 'modified']):
        return 'PARTIAL'
    return 'UNKNOWN'

def _pdf_text(data: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(data))
        text = ""
        for page in reader.pages[:5]:
            text += page.extract_text() or ""
            if len(text) >= MAX_CHARS:
                break
        return text[:MAX_CHARS].strip()
    except Exception:
        return ""


# ── Vertex AI embedding via REST ──────────────────────────────────────────────

_vertex_token: str = ""
_token_expiry: float = 0.0

def _get_token() -> str:
    global _vertex_token, _token_expiry
    if time.monotonic() < _token_expiry - 60:
        return _vertex_token
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    creds.refresh(google.auth.transport.requests.Request())
    _vertex_token = creds.token
    _token_expiry = time.monotonic() + 3600
    return _vertex_token


_VERTEX_URL = (
    f"https://{VERTEX_REGION}-aiplatform.googleapis.com/v1/projects/{GCP_PROJECT}"
    f"/locations/{VERTEX_REGION}/publishers/google/models/{EMBED_MODEL}:predict"
)


def _embed_batch_vertex(texts: list[str], task_idx: int = 0) -> list[list[float]]:
    """Embed a batch of texts via Vertex AI REST API. Returns one vector per text."""
    for attempt in range(5):
        try:
            instances = [{"content": t[:MAX_CHARS], "task_type": "RETRIEVAL_DOCUMENT"}
                         for t in texts]
            resp = httpx.post(
                _VERTEX_URL,
                json={"instances": instances},
                headers={"Authorization": f"Bearer {_get_token()}"},
                timeout=60,
            )
            resp.raise_for_status()
            preds = resp.json().get("predictions", [])
            return [p["embeddings"]["values"] for p in preds]
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            if status == 429:
                wait = min(30 * (2 ** attempt), 120) + random.randint(0, 10)
                print(f"  [t{task_idx}] Vertex rate limit, sleeping {wait}s")
                time.sleep(wait)
            elif status == 401:
                global _token_expiry
                _token_expiry = 0.0  # force refresh on next _get_token() call
                print(f"  [t{task_idx}] Vertex 401 — refreshing token (attempt {attempt+1})")
                time.sleep(2)
            else:
                print(f"  [t{task_idx}] Vertex HTTP {status}: {e.response.text[:200]}")
                if attempt >= 2:
                    return []
                time.sleep(5)
        except Exception as e:
            print(f"  [t{task_idx}] Embed error (attempt {attempt+1}): {e}")
            if attempt >= 3:
                return []
            time.sleep(5)
    return []


# ── Checkpoint ────────────────────────────────────────────────────────────────

def _ckpt_save(bucket, task_idx: int, last_global: int):
    try:
        bucket.blob(f"ingest_ckpt_{task_idx}.json").upload_from_string(
            json.dumps({"last_global": last_global}),
            content_type="application/json",
        )
    except Exception:
        pass

def _ckpt_load(bucket, task_idx: int) -> int:
    try:
        data = bucket.blob(f"ingest_ckpt_{task_idx}.json").download_as_text()
        return json.loads(data).get("last_global", 0)
    except Exception:
        return 0


# ── Core ingestion ────────────────────────────────────────────────────────────

def _run(zf: zipfile.ZipFile, index, bucket, task_idx: int, task_count: int,
         limit: int, resume: bool):

    all_pdfs = [e for e in zf.namelist() if e.lower().endswith('.pdf')]
    print(f"[t{task_idx}] Total PDFs in zip: {len(all_pdfs)}")

    my_pdfs = [(g, all_pdfs[g]) for g in range(len(all_pdfs))
               if g % task_count == task_idx]
    print(f"[t{task_idx}] Shard size: {len(my_pdfs)} PDFs")

    if resume:
        last = _ckpt_load(bucket, task_idx)
        if last:
            print(f"[t{task_idx}] Resuming after global index {last}")
            my_pdfs = [(g, e) for g, e in my_pdfs if g > last]
            print(f"[t{task_idx}] Remaining: {len(my_pdfs)} PDFs")

    # Rate limit budget per task
    embed_interval = (task_count / float(VERTEX_RPM)) * 60.0
    embed_interval = max(embed_interval, 0.01)
    print(f"[t{task_idx}] Vertex embed: batch={EMBED_BATCH}, interval={embed_interval:.2f}s")

    pdf_texts: list[str]  = []
    pdf_meta:  list[dict] = []
    pdf_ids:   list[str]  = []
    upsert_buf: list[dict] = []
    total_upserted = 0
    skipped = 0
    errors  = 0
    last_embed_time = 0.0

    batch_fail_counts: dict = {}

    def _flush_embed(force: bool = False):
        nonlocal errors, last_embed_time
        while pdf_texts and (force or len(pdf_texts) >= EMBED_BATCH):
            chunk_t = pdf_texts[:EMBED_BATCH]
            chunk_m = pdf_meta[:EMBED_BATCH]
            chunk_i = pdf_ids[:EMBED_BATCH]
            del pdf_texts[:EMBED_BATCH]
            del pdf_meta[:EMBED_BATCH]
            del pdf_ids[:EMBED_BATCH]

            elapsed = time.monotonic() - last_embed_time
            if elapsed < embed_interval:
                time.sleep(embed_interval - elapsed)

            vecs = _embed_batch_vertex(chunk_t, task_idx)
            last_embed_time = time.monotonic()

            if len(vecs) != len(chunk_t):
                key = chunk_i[0] if chunk_i else "unknown"
                batch_fail_counts[key] = batch_fail_counts.get(key, 0) + 1
                if batch_fail_counts[key] <= 3:
                    # re-queue at front so it's retried before moving on
                    pdf_texts[:0] = chunk_t
                    pdf_meta[:0] = chunk_m
                    pdf_ids[:0] = chunk_i
                    print(f"  [t{task_idx}] Batch failed, requeueing (attempt {batch_fail_counts[key]})")
                    time.sleep(15 * batch_fail_counts[key])
                else:
                    errors += len(chunk_t)
                    print(f"  [t{task_idx}] Giving up on batch {key} after 3 retries")
                    batch_fail_counts.pop(key, None)
                continue
            batch_fail_counts.pop(chunk_i[0] if chunk_i else None, None)
            for i, vec in enumerate(vecs):
                upsert_buf.append({
                    "id":     chunk_i[i],
                    "values": vec,
                    "metadata": chunk_m[i],
                })
            if not force:
                break  # one chunk per iteration unless flushing all

    def _flush_upsert(final: bool = False):
        nonlocal total_upserted
        while len(upsert_buf) >= UPSERT_BATCH or (final and upsert_buf):
            batch = upsert_buf[:UPSERT_BATCH]
            del upsert_buf[:UPSERT_BATCH]
            index.upsert(vectors=batch)
            total_upserted += len(batch)

    for count, (global_idx, entry_name) in enumerate(my_pdfs):
        if limit and count >= limit:
            break

        try:
            data = zf.read(entry_name)
        except Exception as e:
            errors += 1
            if errors <= 5:
                print(f"  [t{task_idx}] ZIP error {entry_name}: {e}")
            continue

        text = _pdf_text(data)
        if len(text) < 100:
            skipped += 1
            continue

        pdf_texts.append(text)
        pdf_ids.append(f"sc_{_year(entry_name)}_{global_idx:06d}")
        pdf_meta.append({
            "title":   _case_name(entry_name),
            "year":    _year(entry_name),
            "court":   "Supreme Court of India",
            "outcome": _outcome(text),
            "source":  "indiankanoon",
        })

        if len(pdf_texts) >= EMBED_BATCH:
            _flush_embed()
            _flush_upsert()
            if total_upserted and total_upserted % 500 == 0:
                _ckpt_save(bucket, task_idx, global_idx)
                last_meta = pdf_meta[0] if pdf_meta else {"title": ""}
                print(f"  ✓ [t{task_idx}] {total_upserted} upserted | "
                      f"skip={skipped} err={errors}")

    _flush_embed(force=True)
    _flush_upsert(final=True)
    if my_pdfs:
        _ckpt_save(bucket, task_idx, my_pdfs[-1][0])
    print(f"\n[t{task_idx}] DONE — upserted={total_upserted} skipped={skipped} errors={errors}")
    return total_upserted


# ── Entry points ──────────────────────────────────────────────────────────────

def ingest_gcs(gcs_uri: str, task_idx: int, task_count: int, limit: int, resume: bool):
    from google.cloud import storage as _gcs
    parts       = gcs_uri.replace("gs://", "").split("/", 1)
    bucket_name = parts[0]
    blob_path   = parts[1] if len(parts) > 1 else "archive.zip"

    print(f"[ingest] Seekable-streaming: {gcs_uri}")
    client = _gcs.Client()
    bucket = client.bucket(bucket_name)
    blob   = bucket.blob(blob_path)
    blob.reload()
    print(f"[ingest] Zip: {blob.size / 1024**3:.2f} GB  "
          f"Model: {EMBED_MODEL} ({PINECONE_DIM}-dim)")

    zf    = zipfile.ZipFile(_GCSSeekable(blob), 'r')
    pc    = Pinecone(api_key=PINECONE_KEY)
    index = pc.Index(host=PINECONE_HOST) if PINECONE_HOST else pc.Index(PINECONE_INDEX)
    _run(zf, index, bucket, task_idx, task_count, limit, resume)


def ingest_local(zip_path: str, task_idx: int, task_count: int, limit: int, resume: bool):
    print(f"[ingest] Local zip: {zip_path}")
    zf    = zipfile.ZipFile(zip_path, 'r')
    pc    = Pinecone(api_key=PINECONE_KEY)
    index = pc.Index(host=PINECONE_HOST) if PINECONE_HOST else pc.Index(PINECONE_INDEX)

    class _NoBucket:
        def blob(self, *_):
            class _S:
                def upload_from_string(self, *a, **k): pass
                def download_as_text(self): raise FileNotFoundError
            return _S()
    _run(zf, index, _NoBucket(), task_idx, task_count, limit, resume)


def _ensure_index(pc: Pinecone):
    existing = {i.name: i for i in pc.list_indexes().indexes}
    if PINECONE_INDEX in existing:
        current_dim = existing[PINECONE_INDEX].dimension
        if current_dim != PINECONE_DIM:
            print(f"[ingest] Recreating index: {current_dim}-dim → {PINECONE_DIM}-dim")
            pc.delete_index(PINECONE_INDEX)
            time.sleep(5)
        else:
            idx   = pc.Index(host=PINECONE_HOST) if PINECONE_HOST else pc.Index(PINECONE_INDEX)
            stats = idx.describe_index_stats()
            print(f"[ingest] Index '{PINECONE_INDEX}' ({PINECONE_DIM}-dim) "
                  f"— vectors: {stats.total_vector_count}")
            return

    print(f"[ingest] Creating index '{PINECONE_INDEX}' ({PINECONE_DIM}-dim, cosine)")
    pc.create_index(
        name=PINECONE_INDEX,
        dimension=PINECONE_DIM,
        metric="cosine",
        spec=ServerlessSpec(cloud="gcp", region="us-central1"),
    )
    time.sleep(10)
    print(f"[ingest] Index created.")


def main():
    parser = argparse.ArgumentParser()
    src = parser.add_mutually_exclusive_group()
    src.add_argument("--gcs",  default=GCS_ZIP_URI)
    src.add_argument("--zip",  help="Local zip path")
    parser.add_argument("--limit",     type=int, default=0)
    parser.add_argument("--no-resume", action="store_true")
    args = parser.parse_args()

    task_idx   = int(os.getenv("CLOUD_RUN_TASK_INDEX", "0"))
    task_count = int(os.getenv("CLOUD_RUN_TASK_COUNT", "1"))

    print(f"[ingest] task={task_idx}/{task_count}  {EMBED_MODEL} ({PINECONE_DIM}-dim)")

    # Stagger to spread API load
    if task_idx > 0:
        stagger = task_idx * 3 + random.randint(0, 5)
        print(f"[ingest] Staggering {stagger}s …")
        time.sleep(stagger)

    # Verify Vertex AI access on task 0
    if task_idx == 0:
        print(f"[ingest] Testing Vertex AI connectivity …")
        test = _embed_batch_vertex(["test"], task_idx=0)
        if not test:
            print("[ingest] ERROR: Vertex AI embedding test failed — aborting")
            sys.exit(1)
        print(f"[ingest] Vertex AI OK (dim={len(test[0])})")

    pc = Pinecone(api_key=PINECONE_KEY)
    if task_idx == 0:
        _ensure_index(pc)
    else:
        time.sleep(5)

    if args.zip:
        ingest_local(args.zip, task_idx, task_count, args.limit, not args.no_resume)
    else:
        ingest_gcs(args.gcs, task_idx, task_count, args.limit, not args.no_resume)


if __name__ == "__main__":
    main()
