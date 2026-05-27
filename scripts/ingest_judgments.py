"""
Stream-ingest Indian SC judgments from GCS zip into Pinecone.

Design:
- Zero disk space: GCSSeekable wraps a GCS blob via byte-range reads so
  Python's zipfile reads only the central directory + requested entries.
- One embed per text: Gemini embed_content takes a single string; each PDF
  gets its own vector (batch API does NOT produce one vector per input text).
- Parallel shards: Cloud Run Job --tasks N splits entries by modulo via
  CLOUD_RUN_TASK_INDEX / CLOUD_RUN_TASK_COUNT env vars.
- Rate limit budget: 1500 RPM / task_count per task → sleep accordingly.
- Checkpoint: saves last processed global index to GCS per task.

Usage:
  python scripts/ingest_judgments.py                        # GCS (default)
  python scripts/ingest_judgments.py --zip /path/to.zip    # local file
  python scripts/ingest_judgments.py --limit 500           # quick test
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

import google.generativeai as genai
from pinecone import Pinecone, ServerlessSpec
from pypdf import PdfReader
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

GEMINI_KEY     = os.getenv("GEMINI_API_KEY", "")
PINECONE_KEY   = os.getenv("PINECONE_API_KEY", "")
PINECONE_HOST  = os.getenv("PINECONE_HOST", "")
PINECONE_INDEX = os.getenv("PINECONE_INDEX", "sahayak-judgments")
GCS_ZIP_URI    = os.getenv("GCS_ZIP_URI", "gs://sahaiyak/archive.zip")

EMBED_MODEL   = "models/gemini-embedding-001"
UPSERT_BATCH  = 100   # vectors per Pinecone upsert call
MAX_CHARS     = 1500  # chars of PDF text to embed


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


# ── Embedding (single text per call — Gemini API requirement) ─────────────────

def _embed_one(text: str, task_idx: int = 0) -> list | None:
    """Embed a single text string. Retries with backoff on rate-limit errors."""
    for attempt in range(5):
        try:
            result = genai.embed_content(
                model=EMBED_MODEL,
                content=text,
                task_type="retrieval_document",
            )
            emb = result["embedding"] if isinstance(result, dict) else result.get("embedding")
            return emb
        except Exception as e:
            err = str(e)
            if "429" in err or "quota" in err.lower() or "RESOURCE_EXHAUSTED" in err:
                # Jitter prevents all tasks waking up in sync
                wait = min(60 * (2 ** attempt), 300) + random.randint(0, 20)
                print(f"  [t{task_idx}] Rate limit (attempt {attempt+1}), sleeping {wait}s")
                time.sleep(wait)
            else:
                print(f"  [t{task_idx}] Embed error: {e}")
                if attempt >= 2:
                    return None
                time.sleep(5)
    return None


# ── Checkpoint ────────────────────────────────────────────────────────────────

def _ckpt_save(bucket, task_idx: int, last_global: int):
    try:
        bucket.blob(f"ingest_ckpt_{task_idx}.json").upload_from_string(
            json.dumps({"last_global": last_global}), content_type="application/json")
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

    # Rate limit budget: 1500 RPM shared across all tasks
    # Each task should do at most 1500/task_count RPM
    embed_interval = (task_count / 1500.0) * 60.0  # seconds between embed calls
    embed_interval = max(embed_interval, 0.05)       # floor at 50ms
    print(f"[t{task_idx}] Embed interval: {embed_interval:.2f}s "
          f"({1/embed_interval:.0f}/min × {task_count} tasks = "
          f"{task_count/embed_interval:.0f}/min total)")

    upsert_buf: list[dict] = []
    total_upserted = 0
    skipped = 0
    errors = 0
    last_embed_time = 0.0

    for count, (global_idx, entry_name) in enumerate(my_pdfs):
        if limit and count >= limit:
            break

        try:
            data = zf.read(entry_name)
        except Exception as e:
            errors += 1
            if errors <= 5:
                print(f"  [t{task_idx}] ZIP read error {entry_name}: {e}")
            continue

        text = _pdf_text(data)
        if len(text) < 100:
            skipped += 1
            continue

        year      = _year(entry_name)
        case_name = _case_name(entry_name)
        outcome   = _outcome(text)
        doc_id    = f"sc_{year}_{global_idx:06d}"

        # Respect rate limit interval
        elapsed = time.monotonic() - last_embed_time
        if elapsed < embed_interval:
            time.sleep(embed_interval - elapsed)

        emb = _embed_one(text, task_idx)
        last_embed_time = time.monotonic()

        if emb is None:
            errors += 1
            continue

        upsert_buf.append({
            "id":     doc_id,
            "values": emb,
            "metadata": {
                "title":   case_name,
                "year":    year,
                "court":   "Supreme Court of India",
                "outcome": outcome,
                "source":  "indiankanoon",
            }
        })

        if len(upsert_buf) >= UPSERT_BATCH:
            index.upsert(vectors=upsert_buf)
            total_upserted += len(upsert_buf)
            upsert_buf.clear()
            _ckpt_save(bucket, task_idx, global_idx)
            print(f"  ✓ [t{task_idx}] {total_upserted} upserted | "
                  f"skip={skipped} err={errors} | last: {case_name[:50]}")

    # Flush remainder
    if upsert_buf:
        index.upsert(vectors=upsert_buf)
        total_upserted += len(upsert_buf)

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
    size_gb = blob.size / 1024**3
    print(f"[ingest] Zip: {size_gb:.2f} GB")

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
            class _Stub:
                def upload_from_string(self, *a, **k): pass
                def download_as_text(self, *a): raise FileNotFoundError
            return _Stub()
    _run(zf, index, _NoBucket(), task_idx, task_count, limit, resume)


def _ensure_index(pc: Pinecone):
    existing = {i.name for i in pc.list_indexes().indexes}
    if PINECONE_INDEX not in existing:
        print(f"[ingest] Creating Pinecone index '{PINECONE_INDEX}' (3072-dim, cosine)")
        pc.create_index(
            name=PINECONE_INDEX,
            dimension=3072,
            metric="cosine",
            spec=ServerlessSpec(cloud="gcp", region="us-central1"),
        )
        time.sleep(10)
    host = PINECONE_HOST or None
    idx  = pc.Index(host=host) if host else pc.Index(PINECONE_INDEX)
    stats = idx.describe_index_stats()
    print(f"[ingest] Index '{PINECONE_INDEX}' — current vectors: {stats.total_vector_count}")


def main():
    parser = argparse.ArgumentParser()
    src = parser.add_mutually_exclusive_group()
    src.add_argument("--gcs",  default=GCS_ZIP_URI)
    src.add_argument("--zip",  help="Local zip path")
    parser.add_argument("--limit",      type=int,  default=0)
    parser.add_argument("--no-resume",  action="store_true")
    args = parser.parse_args()

    task_idx   = int(os.getenv("CLOUD_RUN_TASK_INDEX", "0"))
    task_count = int(os.getenv("CLOUD_RUN_TASK_COUNT", "1"))

    print(f"[ingest] task={task_idx}/{task_count}  model={EMBED_MODEL}")

    # Stagger tasks so they don't all burst the Gemini API simultaneously
    if task_idx > 0:
        stagger = task_idx * 4 + random.randint(0, 5)
        print(f"[ingest] Staggering {stagger}s …")
        time.sleep(stagger)

    genai.configure(api_key=GEMINI_KEY)

    pc = Pinecone(api_key=PINECONE_KEY)
    if task_idx == 0:
        _ensure_index(pc)
    else:
        time.sleep(3)  # give task 0 time to create index if needed

    if args.zip:
        ingest_local(args.zip, task_idx, task_count, args.limit, not args.no_resume)
    else:
        ingest_gcs(args.gcs, task_idx, task_count, args.limit, not args.no_resume)


if __name__ == "__main__":
    main()
