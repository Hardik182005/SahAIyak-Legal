"""
Ingest Indian Kanoon Supreme Court judgments from GCS bucket or local zip into Pinecone.

Usage (GCS — recommended for production):
  python scripts/ingest_judgments.py --gcs gs://sahaiyak/archive/

Usage (local zip):
  python scripts/ingest_judgments.py --zip C:/Users/hardi/Downloads/archive.zip

Options:
  --limit N   Process at most N PDFs (0 = all)
  --skip  N   Skip first N PDFs
  --batch N   Upsert batch size (default 50)
"""
import argparse
import io
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
import os

load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

GEMINI_KEY = os.getenv("GEMINI_API_KEY", "")
PINECONE_KEY = os.getenv("PINECONE_API_KEY", "")
PINECONE_HOST = os.getenv("PINECONE_HOST", "")
PINECONE_INDEX = os.getenv("PINECONE_INDEX", "sahayak-judgments")
EMBED_MODEL = "models/gemini-embedding-001"
BATCH_SIZE = 50
MAX_TEXT_CHARS = 3000


def extract_year(filename: str) -> str:
    m = re.search(r'(\d{4})', filename)
    return m.group(1) if m else "unknown"


def extract_case_name(filename: str) -> str:
    name = Path(filename).stem
    name = re.sub(r'_on_\d.*', '', name)
    name = name.replace('_', ' ').strip()
    return name[:120]


def detect_outcome(text: str) -> str:
    t = text.lower()
    if any(w in t for w in ['dismissed', 'petition dismissed', 'appeal dismissed', 'case dismissed']):
        return 'DISMISSED'
    if any(w in t for w in ['allowed', 'appeal allowed', 'petition allowed', 'granted']):
        return 'ALLOWED'
    if any(w in t for w in ['upheld', 'affirmed', 'confirmed']):
        return 'UPHELD'
    if any(w in t for w in ['partly allowed', 'partly dismissed', 'modified']):
        return 'PARTIAL'
    return 'UNKNOWN'


def extract_pdf_text(data: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(data))
        text = ""
        for page in reader.pages[:5]:
            text += page.extract_text() or ""
            if len(text) > MAX_TEXT_CHARS:
                break
        return text[:MAX_TEXT_CHARS].strip()
    except Exception:
        return ""


def embed_texts(texts: list) -> list:
    result = genai.embed_content(
        model=EMBED_MODEL,
        content=texts,
        task_type="retrieval_document",
    )
    emb = result["embedding"]
    # embed_content returns a single list when content is a list of strings in some SDK versions
    if emb and isinstance(emb[0], (int, float)):
        return [emb]  # single embedding returned
    return emb


def _upsert_batch(index, ids, texts, metas):
    embeddings = embed_texts(texts)
    vectors = [
        {"id": ids[i], "values": embeddings[i], "metadata": metas[i]}
        for i in range(len(ids))
    ]
    index.upsert(vectors=vectors)


def _process_pdf(entry_name: str, data: bytes, idx: int, batch_texts, batch_meta, batch_ids):
    """Process a single PDF and add to batch. Returns True if added, False if skipped."""
    filename = Path(entry_name).name
    year = extract_year(entry_name)
    case_name = extract_case_name(filename)
    text = extract_pdf_text(data)
    if len(text) < 100:
        return False
    outcome = detect_outcome(text)
    doc_id = f"sc_{year}_{idx:06d}"
    batch_texts.append(text[:1500])
    batch_meta.append({
        "title": case_name,
        "year": year,
        "court": "Supreme Court of India",
        "outcome": outcome,
        "amount": "",
        "source": "indiankanoon",
    })
    batch_ids.append(doc_id)
    return True


def ingest_from_zip(zip_path: str, index, limit: int = 0, skip: int = 0, batch_size: int = BATCH_SIZE):
    print(f"[ingest] Reading local zip: {zip_path}")
    batch_texts, batch_meta, batch_ids = [], [], []
    total_upserted = 0
    skipped = 0
    errors = 0

    with zipfile.ZipFile(zip_path, 'r') as zf:
        entries = [e for e in zf.namelist() if e.lower().endswith('.pdf')]
        print(f"[ingest] Found {len(entries)} PDFs in zip")

        for i, entry in enumerate(entries):
            if skip and i < skip:
                continue
            if limit and (i - skip) >= limit:
                break
            try:
                data = zf.read(entry)
                added = _process_pdf(entry, data, i, batch_texts, batch_meta, batch_ids)
                if not added:
                    skipped += 1
                    continue

                if len(batch_texts) >= batch_size:
                    _upsert_batch(index, batch_ids, batch_texts, batch_meta)
                    total_upserted += len(batch_texts)
                    print(f"  ✓ {total_upserted} upserted (last: {batch_meta[-1]['title'][:50]})")
                    batch_texts, batch_meta, batch_ids = [], [], []
                    time.sleep(1)
            except Exception as e:
                errors += 1
                if errors < 5:
                    print(f"  ✗ Error on {entry}: {e}")

    if batch_texts:
        _upsert_batch(index, batch_ids, batch_texts, batch_meta)
        total_upserted += len(batch_texts)

    return total_upserted, skipped, errors


def ingest_from_gcs(gcs_uri: str, index, limit: int = 0, skip: int = 0, batch_size: int = BATCH_SIZE):
    """Read PDFs from GCS bucket (e.g. gs://sahaiyak/archive/) and ingest into Pinecone."""
    try:
        from google.cloud import storage as gcs
    except ImportError:
        print("[ingest] ERROR: google-cloud-storage not installed. Run: pip install google-cloud-storage")
        sys.exit(1)

    # Parse gs://bucket/prefix
    gcs_uri = gcs_uri.rstrip('/')
    if gcs_uri.startswith("gs://"):
        parts = gcs_uri[5:].split('/', 1)
        bucket_name = parts[0]
        prefix = (parts[1] + '/') if len(parts) > 1 else ''
    else:
        print(f"[ingest] Invalid GCS URI: {gcs_uri}")
        sys.exit(1)

    print(f"[ingest] Reading from GCS: bucket={bucket_name}, prefix={prefix}")
    client = gcs.Client()
    bucket = client.bucket(bucket_name)
    blobs = list(bucket.list_blobs(prefix=prefix))
    pdf_blobs = [b for b in blobs if b.name.lower().endswith('.pdf')]
    print(f"[ingest] Found {len(pdf_blobs)} PDFs in GCS")

    batch_texts, batch_meta, batch_ids = [], [], []
    total_upserted = 0
    skipped = 0
    errors = 0

    for i, blob in enumerate(pdf_blobs):
        if skip and i < skip:
            continue
        if limit and (i - skip) >= limit:
            break
        try:
            data = blob.download_as_bytes()
            added = _process_pdf(blob.name, data, i, batch_texts, batch_meta, batch_ids)
            if not added:
                skipped += 1
                continue

            if len(batch_texts) >= batch_size:
                _upsert_batch(index, batch_ids, batch_texts, batch_meta)
                total_upserted += len(batch_texts)
                print(f"  ✓ {total_upserted} upserted (last: {batch_meta[-1]['title'][:50]})")
                batch_texts, batch_meta, batch_ids = [], [], []
                time.sleep(1)
        except Exception as e:
            errors += 1
            if errors < 5:
                print(f"  ✗ Error on {blob.name}: {e}")

    if batch_texts:
        _upsert_batch(index, batch_ids, batch_texts, batch_meta)
        total_upserted += len(batch_texts)

    return total_upserted, skipped, errors


def main():
    parser = argparse.ArgumentParser(description="Ingest Indian Kanoon judgments into Pinecone")
    src = parser.add_mutually_exclusive_group(required=False)
    src.add_argument("--gcs", default="gs://sahaiyak/archive/", help="GCS URI (gs://bucket/prefix)")
    src.add_argument("--zip", help="Local zip file path")
    parser.add_argument("--limit", type=int, default=0, help="Max PDFs to process (0=all)")
    parser.add_argument("--skip", type=int, default=0, help="Skip first N PDFs")
    parser.add_argument("--batch", type=int, default=BATCH_SIZE, help="Upsert batch size")
    args = parser.parse_args()

    print(f"[ingest] Gemini embedding model: {EMBED_MODEL}")
    genai.configure(api_key=GEMINI_KEY)
    pc = Pinecone(api_key=PINECONE_KEY)

    # Ensure index exists
    existing = [idx.name for idx in pc.list_indexes().indexes]
    if PINECONE_INDEX not in existing:
        print(f"[ingest] Creating Pinecone index: {PINECONE_INDEX} (3072-dim)")
        pc.create_index(
            name=PINECONE_INDEX,
            dimension=3072,
            metric="cosine",
            spec=ServerlessSpec(cloud="gcp", region="us-central1"),
        )
        time.sleep(5)

    index = pc.Index(host=PINECONE_HOST) if PINECONE_HOST else pc.Index(PINECONE_INDEX)

    if args.zip:
        total, skipped, errors = ingest_from_zip(args.zip, index, args.limit, args.skip, args.batch)
    else:
        total, skipped, errors = ingest_from_gcs(args.gcs, index, args.limit, args.skip, args.batch)

    print(f"\n[ingest] Done. Upserted: {total}, Skipped: {skipped}, Errors: {errors}")


if __name__ == "__main__":
    main()
