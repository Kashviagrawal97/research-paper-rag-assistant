"""Ingestion pipeline: PDFs -> chunks -> embeddings -> Chroma vector DB.

Run on its own:  python3 backend/ingestion_pipeline.py
The web app (app.py) calls ingest() too.
"""
import logging
import sys
import time

from langchain_community.document_loaders import PyPDFDirectoryLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter

from config import DATA_DIR, get_vectorstore

logging.getLogger("pypdf").setLevel(logging.ERROR)  # Hide noisy PDF font warnings

BATCH_SIZE = 95         # Gemini free tier allows 100 embedding requests/min, 95 leaves a margin
WINDOW_SECONDS = 61     # Length of that rate limit window


def ingest(on_progress=None):
    """Read PDFs, split into chunks, embed them, and store them in Chroma.

    on_progress(stage, message, percent) lets the web app show progress.
    Without it, messages are just printed.
    """
    report = on_progress or (lambda stage, message, percent: print(message))

    # Step 1: Load PDFs
    report("reading", "Reading PDFs", 0)
    documents = PyPDFDirectoryLoader(DATA_DIR).load()
    if not documents:
        raise ValueError("No readable text found in the PDFs. Scanned PDFs without text can't be used.")

    # Step 2: Split into chunks
    splitter = RecursiveCharacterTextSplitter(chunk_size=1500, chunk_overlap=200)
    chunks = splitter.split_documents(documents)
    report("reading", f"Split {len(documents)} pages into {len(chunks)} passages", 0)

    # Step 3: Embed and store in batches (stays under the free tier rate limit)
    vectorstore = get_vectorstore()
    total = len(chunks)
    report("embedding", f"Embedded 0 of {total} passages", 0)

    for i in range(0, total, BATCH_SIZE):
        started = time.time()

        for attempt in range(5):
            try:
                vectorstore.add_documents(chunks[i:i + BATCH_SIZE])
                break
            except Exception as e:
                if "429" not in str(e) and "RESOURCE_EXHAUSTED" not in str(e):
                    raise
                print("Rate limit hit. Waiting 60 seconds before retrying...")
                time.sleep(60)
        else:  # all 5 attempts were rate limited
            raise RuntimeError("Still rate limited after 5 retries. Try again in a few minutes.")

        done = min(i + BATCH_SIZE, total)
        report("embedding", f"Embedded {done} of {total} passages", int(done / total * 100))

        # Wait only for the rest of the 1-minute window
        if done < total:
            time.sleep(max(0, WINDOW_SECONDS - (time.time() - started)))


if __name__ == "__main__":
    try:
        ingest()
    except ValueError as e:
        sys.exit(str(e))
    print("Done! Vector DB ready in the 'chroma_db' folder.")