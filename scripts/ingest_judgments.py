"""
Stream-ingest Indian SC judgments from GCS zip into Pinecone.

Key design:
- Zero disk space: reads zip entries via GCS byte-range requests (no full download)
- Batch embedding: up to 10 texts per Gemini embed call
- Parallel: Cloud Run Job --tasks N runs shards in parallel (CLOUD_RUN_TASK_INDEX)
- Idempotent: upsert overwrites same vector ID; checkpoint resumes on restart

Usage:
  python scripts/ingest_judgments.py                        # GCS zip (default)
  python scripts/ingest_judgments.py --zip path/to/file.zip # local zip
  python scripts/ingest_judgments.py --limit 1000           # test run
"""
import argparse
import io
import json
import os
import re
import sys
import time
import zipfile
from pathlib import Path
from typing import Optional

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

EMBED_MODEL    = "models/gemini-embedding-001"
EMBED_BATCH    = 10     # texts per Gemini embed call
UPSERT_BATCH   = 50     # vectors per Pinecone upsert
MAX_CHARS      = 2000   # chars of text to embed per PDF
CHECKPOINT_KEY = "ingest_checkpoint.json"


# ── GCS seekable wrapper ──────────────────────────────────────────────────────

class _GCSSeekable:
    """Wrap a GCS blob as a seekable file-like object via range reads.
    zipfile reads the central directory (end of file) once, then fetches
    individual entries by offset — so we only download what we actually need.
    """
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

    def tell(self):       return self._pos
    def seekable(self):   return True
    def readable(self):   return True

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

def _extract_text(data: bytes) -> str:
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


# ── Embedding ─────────────────────────────────────────────────────────────────

def _embed_batch(texts: list[str]) -> list[list[float]]:
    """Embed up to EMBED_BATCH texts in one Gemini call. Returns list of vectors."""
    for attempt in range(4):
        try:
            result = genai.embed_content(
                model=EMBED_MODEL,
                content=texts,
                task_type="retrieval_document",
            )
            emb = result["embedding"] if isinstance(result, dict) else result.get("embedding", [])
            # Single text returns flat list; multiple returns list-of-lists
            if emb and isinstance(emb[0], (int, float)):
                return [emb]
            return emb
        except Exception as e:
            err = str(e)
            if "429" in err or "quota" in err.lower() or "RESOURCE_EXHAUSTED" in err:
                wait = 60 * (2 ** attempt)
                print(f"  Rate limit hit, sleeping {wait}s …")
                time.sleep(wait)
            else:
                print(f"  Embed error (attempt {attempt+1}): {e}")
                if attempt == 3:
                    return []
                time.sleep(5)
    return []


# ── Checkpoint (GCS) ──────────────────────────────────────────────────────────

def _save_ckpt(bucket, task_idx: int, last_global: int):
    try:
        key = f"ingest_ckpt_{task_idx}.json"
        bucket.blob(key).upload_from_string(
            json.dumps({"last_global": last_global}),
            content_type="application/json"
        )
    except Exception:
        pass

def _load_ckpt(bucket, task_idx: int) -> int:
    try:
        key = f"ingest_ckpt_{task_idx}.json"
        data = bucket.blob(key).download_as_text()
        return json.loads(data).get("last_global", 0)
    except Exception:
        return 0


# ── Core ingestion ────────────────────────────────────────────────────────────

def _run(zf: zipfile.ZipFile, index, bucket, task_idx: int, task_count: int,
         limit: int, resume: bool):

    all_entries = [e for e in zf.namelist() if e.lower().endswith('.pdf')]
    print(f"[task {task_idx}/{task_count}] Total PDFs in zip: {len(all_entries)}")

    # Shard by modulo so each task processes a disjoint set
    my_entries = [(g, all_entries[g]) for g in range(len(all_entries))
                  if g % task_count == task_idx]
    print(f"[task {task_idx}] My shard: {len(my_entries)} PDFs")

    start_from = 0
    if resume:
        start_from = _load_ckpt(bucket, task_idx)
        if start_from:
            print(f"[task {task_idx}] Resuming from global index {start_from}")
            my_entries = [(g, e) for g, e in my_entries if g > start_from]

    total_upserted = 0
    skipped = 0
    errors = 0
    # Rolling buffers for batched embed + upsert
    embed_texts: list[str] = []
    embed_meta:  list[dict] = []
    embed_ids:   list[str]  = []
    upsert_vectors: list[dict] = []

    def _flush_embed():
        nonlocal errors
        if not embed_texts:
            return
        vecs = _embed_batch(embed_texts)
        if len(vecs) != len(embed_texts):
            nonlocal errors
            errors += len(embed_texts)
            embed_texts.clear(); embed_meta.clear(); embed_ids.clear()
            return
        for i, vec in enumerate(vecs):
            upsert_vectors.append({
                "id": embed_ids[i],
                "values": vec,
                "metadata": embed_meta[i],
            })
        embed_texts.clear(); embed_meta.clear(); embed_ids.clear()

    def _flush_upsert(force=False):
        nonlocal total_upserted
        if len(upsert_vectors) >= UPSERT_BATCH or (force and upsert_vectors):
            index.upsert(vectors=upsert_vectors[:UPSERT_BATCH])
            total_upserted += min(len(upsert_vectors), UPSERT_BATCH)
            del upsert_vectors[:UPSERT_BATCH]

    for count, (global_idx, entry_name) in enumerate(my_entries):
        if limit and count >= limit:
            break

        try:
            data = zf.read(entry_name)
            text = _extract_text(data)
            if len(text) < 100:
                skipped += 1
                continue

            year      = _year(entry_name)
            case_name = _case_name(entry_name)
            outcome   = _outcome(text)
            doc_id    = f"sc_{year}_{global_idx:06d}"

            embed_texts.append(text[:MAX_CHARS])
            embed_ids.append(doc_id)
            embed_meta.append({
                "title":   case_name,
                "year":    year,
                "court":   "Supreme Court of India",
                "outcome": outcome,
                "source":  "indiankanoon",
            })

            # Flush embed batch
            if len(embed_texts) >= EMBED_BATCH:
                _flush_embed()
                _flush_upsert()

                if total_upserted % 500 == 0 and total_upserted:
                    _save_ckpt(bucket, task_idx, global_idx)
                    print(f"  ✓ [{task_idx}] {total_upserted} upserted | "
                          f"skip={skipped} err={errors} | {case_name[:50]}")

                time.sleep(0.15)  # ~400 embed calls/min per task, 10 tasks = 4000/min

        except Exception as e:
            errors += 1
            if errors <= 10:
                print(f"  ✗ [{task_idx}] {entry_name}: {e}")

    # Final flush
    _flush_embed()
    while upsert_vectors:
        _flush_upsert(force=True)

    _save_ckpt(bucket, task_idx, my_entries[-1][0] if my_entries else 0)
    print(f"\n[task {task_idx}] DONE — upserted={total_upserted} skipped={skipped} errors={errors}")
    return total_upserted


# ── Entry points ──────────────────────────────────────────────────────────────

def ingest_gcs(gcs_uri: str, task_idx: int, task_count: int,
               limit: int, resume: bool):
    from google.cloud import storage as _gcs

    parts       = gcs_uri.replace("gs://", "").split("/", 1)
    bucket_name = parts[0]
    blob_path   = parts[1] if len(parts) > 1 else "archive.zip"

    print(f"[ingest] Opening GCS zip via seekable stream (no download): {gcs_uri}")
    client = _gcs.Client()
    bucket = client.bucket(bucket_name)
    blob   = bucket.blob(blob_path)
    blob.reload()
    print(f"[ingest] Zip size: {blob.size / 1024**3:.2f} GB")

    seekable = _GCSSeekable(blob)
    zf = zipfile.ZipFile(seekable, 'r')
    pc    = Pinecone(api_key=PINECONE_KEY)
    index = pc.Index(host=PINECONE_HOST) if PINECONE_HOST else pc.Index(PINECONE_INDEX)
    return _run(zf, index, bucket, task_idx, task_count, limit, resume)


def ingest_local(zip_path: str, task_idx: int, task_count: int,
                 limit: int, resume: bool):
    from google.cloud import storage as _gcs
    print(f"[ingest] Opening local zip: {zip_path}")
    zf    = zipfile.ZipFile(zip_path, 'r')
    pc    = Pinecone(api_key=PINECONE_KEY)
    index = pc.Index(host=PINECONE_HOST) if PINECONE_HOST else pc.Index(PINECONE_INDEX)
    # For local runs, use a dummy bucket object that skips checkpointing
    class _NoBucket:
        def blob(self, *_): return type('', (), {'upload_from_string': lambda *a, **k: None,
                                                   'download_as_text':  lambda *a: (_ for _ in ()).throw(Exception)})()
    return _run(zf, index, _NoBucket(), task_idx, task_count, limit, resume)


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
    stats = pc.Index(host=PINECONE_HOST).describe_index_stats() if PINECONE_HOST \
            else pc.Index(PINECONE_INDEX).describe_index_stats()
    print(f"[ingest] Index '{PINECONE_INDEX}' — current vectors: {stats.total_vector_count}")


def main():
    parser = argparse.ArgumentParser(description="Ingest Indian SC judgments into Pinecone")
    src = parser.add_mutually_exclusive_group()
    src.add_argument("--gcs",  default=GCS_ZIP_URI, help="GCS URI of zip file")
    src.add_argument("--zip",  help="Local zip file path")
    parser.add_argument("--limit",      type=int, default=0,     help="Max PDFs per task (0=all)")
    parser.add_argument("--no-resume",  action="store_true",     help="Ignore checkpoint, start fresh")
    args = parser.parse_args()

    # Cloud Run Job injects these automatically
    task_idx   = int(os.getenv("CLOUD_RUN_TASK_INDEX", "0"))
    task_count = int(os.getenv("CLOUD_RUN_TASK_COUNT", "1"))

    print(f"[ingest] task {task_idx}/{task_count}  model={EMBED_MODEL}")
    genai.configure(api_key=GEMINI_KEY)

    pc = Pinecone(api_key=PINECONE_KEY)
    if task_idx == 0:
        _ensure_index(pc)

    if args.zip:
        ingest_local(args.zip, task_idx, task_count, args.limit, not args.no_resume)
    else:
        ingest_gcs(args.gcs, task_idx, task_count, args.limit, not args.no_resume)


if __name__ == "__main__":
    main()
