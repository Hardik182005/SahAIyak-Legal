"""
Stream-ingest Indian SC judgments from GCS zip into Pinecone.

Design:
- Zero disk space: GCSSeekable wraps a GCS blob via byte-range reads so
  Python's zipfile reads only the central directory + requested entries.
- OpenAI text-embedding-3-large (3072-dim): 3000 RPM limit, supports true
  batch embedding (up to 2048 inputs per call), ~$0.00013/1k tokens.
  Cost for full 26k judgment run: ~$1.30.
- Parallel shards: Cloud Run Job --tasks N splits entries by modulo via
  CLOUD_RUN_TASK_INDEX / CLOUD_RUN_TASK_COUNT env vars.
- Rate limit budget: 3000 RPM / task_count per task → sleep accordingly.
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

from openai import OpenAI
from pinecone import Pinecone, ServerlessSpec
from pypdf import PdfReader
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

OPENAI_KEY     = os.getenv("OPENAI_API_KEY", "")
PINECONE_KEY   = os.getenv("PINECONE_API_KEY", "")
PINECONE_HOST  = os.getenv("PINECONE_HOST", "")
PINECONE_INDEX = os.getenv("PINECONE_INDEX", "sahayak-judgments")
GCS_ZIP_URI    = os.getenv("GCS_ZIP_URI", "gs://sahaiyak/archive.zip")

EMBED_MODEL   = "text-embedding-3-small"   # 1536-dim, $0.00002/1k tokens (~$0.20 total)
PINECONE_DIM  = 1536
EMBED_BATCH   = 50     # texts per OpenAI embed call (supports up to 2048)
UPSERT_BATCH  = 100    # vectors per Pinecone upsert call
MAX_CHARS     = 1000   # chars of PDF text to embed
EMBED_RPM     = 3000   # OpenAI tier-1 limit


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


# ── Embedding (OpenAI — true batch, 3000 RPM, $0.00002/1k tokens) ─────────────

_oai_client: OpenAI | None = None

def _get_oai() -> OpenAI:
    global _oai_client
    if _oai_client is None:
        _oai_client = OpenAI(api_key=OPENAI_KEY)
    return _oai_client


def _embed_batch_oai(texts: list[str], task_idx: int = 0) -> list[list[float]]:
    """Embed a batch of texts via OpenAI. Returns one vector per text."""
    for attempt in range(5):
        try:
            resp = _get_oai().embeddings.create(
                model=EMBED_MODEL,
                input=texts,
            )
            # Sort by index to preserve order
            return [e.embedding for e in sorted(resp.data, key=lambda x: x.index)]
        except Exception as e:
            err = str(e)
            if "429" in err or "rate" in err.lower():
                wait = min(30 * (2 ** attempt), 120) + random.randint(0, 10)
                print(f"  [t{task_idx}] Rate limit (attempt {attempt+1}), sleeping {wait}s")
                time.sleep(wait)
            else:
                print(f"  [t{task_idx}] Embed error: {e}")
                if attempt >= 2:
                    return []
                time.sleep(3)
    return []


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

    # OpenAI: 3000 RPM / task_count per task; with batch=50, need ~53 API calls per task
    embed_interval = (task_count / float(EMBED_RPM)) * 60.0
    embed_interval = max(embed_interval, 0.02)
    print(f"[t{task_idx}] OpenAI embed: batch={EMBED_BATCH}, interval={embed_interval:.2f}s")

    # Accumulate PDFs; flush as embed batches
    pdf_buf_texts:  list[str]  = []
    pdf_buf_meta:   list[dict] = []
    pdf_buf_ids:    list[str]  = []
    upsert_buf:     list[dict] = []
    total_upserted = 0
    skipped = 0
    errors  = 0
    last_embed_time = 0.0

    def _flush_embed_buf(force: bool = False):
        nonlocal errors, last_embed_time
        if not pdf_buf_texts:
            return
        if not force and len(pdf_buf_texts) < EMBED_BATCH:
            return
        # Process in EMBED_BATCH chunks
        while pdf_buf_texts:
            chunk_texts = pdf_buf_texts[:EMBED_BATCH]
            chunk_meta  = pdf_buf_meta[:EMBED_BATCH]
            chunk_ids   = pdf_buf_ids[:EMBED_BATCH]
            del pdf_buf_texts[:EMBED_BATCH]
            del pdf_buf_meta[:EMBED_BATCH]
            del pdf_buf_ids[:EMBED_BATCH]

            elapsed = time.monotonic() - last_embed_time
            if elapsed < embed_interval:
                time.sleep(embed_interval - elapsed)

            vecs = _embed_batch_oai(chunk_texts, task_idx)
            last_embed_time = time.monotonic()

            if len(vecs) != len(chunk_texts):
                errors += len(chunk_texts)
                continue
            for i, vec in enumerate(vecs):
                upsert_buf.append({
                    "id":     chunk_ids[i],
                    "values": vec,
                    "metadata": chunk_meta[i],
                })
            if not force and pdf_buf_texts:
                break  # only one chunk per call unless force-flushing

    def _flush_upsert_buf(final: bool = False):
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

        pdf_buf_texts.append(text)
        pdf_buf_ids.append(doc_id)
        pdf_buf_meta.append({
            "title":   case_name,
            "year":    year,
            "court":   "Supreme Court of India",
            "outcome": outcome,
            "source":  "indiankanoon",
        })

        if len(pdf_buf_texts) >= EMBED_BATCH:
            _flush_embed_buf()
            _flush_upsert_buf()
            if total_upserted and total_upserted % 500 == 0:
                _ckpt_save(bucket, task_idx, global_idx)
                print(f"  ✓ [t{task_idx}] {total_upserted} upserted | "
                      f"skip={skipped} err={errors} | {case_name[:50]}")

    # Final flush
    _flush_embed_buf(force=True)
    _flush_upsert_buf(final=True)

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
    existing = {i.name: i for i in pc.list_indexes().indexes}
    if PINECONE_INDEX in existing:
        current_dim = existing[PINECONE_INDEX].dimension
        if current_dim != PINECONE_DIM:
            print(f"[ingest] Recreating index: {current_dim}-dim → {PINECONE_DIM}-dim")
            pc.delete_index(PINECONE_INDEX)
            time.sleep(5)
        else:
            idx = pc.Index(host=PINECONE_HOST) if PINECONE_HOST else pc.Index(PINECONE_INDEX)
            stats = idx.describe_index_stats()
            print(f"[ingest] Index '{PINECONE_INDEX}' ({PINECONE_DIM}-dim) — vectors: {stats.total_vector_count}")
            return

    print(f"[ingest] Creating Pinecone index '{PINECONE_INDEX}' ({PINECONE_DIM}-dim, cosine)")
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
    parser.add_argument("--limit",      type=int,  default=0)
    parser.add_argument("--no-resume",  action="store_true")
    args = parser.parse_args()

    task_idx   = int(os.getenv("CLOUD_RUN_TASK_INDEX", "0"))
    task_count = int(os.getenv("CLOUD_RUN_TASK_COUNT", "1"))

    print(f"[ingest] task={task_idx}/{task_count}  model={EMBED_MODEL}  dim={PINECONE_DIM}")
    print(f"[ingest] Est. cost: {26688 * 250 / 1_000_000 * 0.00002:.4f} USD (text-embedding-3-small)")

    # Stagger tasks so they don't all burst the OpenAI API simultaneously
    if task_idx > 0:
        stagger = task_idx * 3 + random.randint(0, 5)
        print(f"[ingest] Staggering {stagger}s …")
        time.sleep(stagger)

    if not OPENAI_KEY:
        print("ERROR: OPENAI_API_KEY not set")
        sys.exit(1)

    pc = Pinecone(api_key=PINECONE_KEY)
    if task_idx == 0:
        _ensure_index(pc)
    else:
        time.sleep(5)  # give task 0 time to create/verify index

    if args.zip:
        ingest_local(args.zip, task_idx, task_count, args.limit, not args.no_resume)
    else:
        ingest_gcs(args.gcs, task_idx, task_count, args.limit, not args.no_resume)


if __name__ == "__main__":
    main()
