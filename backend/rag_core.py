"""Reusable RAG functions used by the web app (app.py).

The command-line scripts (ingestion_pipeline.py, retrieval_pipeline.py) still
work on their own. This module just wraps the same logic in functions so the
web server can call them and report progress.
"""
import glob
import logging
import os
import time

from langchain_chroma import Chroma
from langchain_community.document_loaders import PyPDFDirectoryLoader
from langchain_core.prompts import ChatPromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

from config import DATA_DIR, DB_DIR

logging.getLogger("pypdf").setLevel(logging.ERROR)  # Hide noisy PDF font warnings

BATCH_SIZE = 95        # Gemini free tier allows 100 embedding requests/min
WINDOW_SECONDS = 61    # Length of the rate limit window

PROMPT = ChatPromptTemplate.from_template("""
You are a helpful research assistant. Answer the question using ONLY the context below.
If the answer is not in the context, say "I don't have enough information in the provided papers."

Context:
{context}

Question: {question}

Answer:
""")

_chain = None


def _embeddings():
    # Must be the SAME embedding model for ingestion and retrieval
    return GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-2")


def _vectorstore():
    return Chroma(persist_directory=DB_DIR, embedding_function=_embeddings())


def _get_chain():
    global _chain
    if _chain is None:
        # If you get a model error, try "gemini-flash-latest" instead
        llm = ChatGoogleGenerativeAI(model="gemini-3.5-flash", temperature=0.2)
        _chain = PROMPT | llm
    return _chain


def list_papers():
    os.makedirs(DATA_DIR, exist_ok=True)
    return sorted(f for f in os.listdir(DATA_DIR) if f.lower().endswith(".pdf"))


def has_library():
    """True if a vector DB with at least one chunk already exists."""
    if not os.path.isdir(DB_DIR):
        return False
    try:
        return len(_vectorstore().get(limit=1)["ids"]) > 0
    except Exception:
        return False


def reset_library():
    """Delete all PDFs in data/ and empty the vector DB."""
    os.makedirs(DATA_DIR, exist_ok=True)
    for path in glob.glob(os.path.join(DATA_DIR, "*")):
        if os.path.isfile(path):
            os.remove(path)
    try:
        _vectorstore().delete_collection()
    except Exception:
        pass


def _add_with_retry(vectorstore, batch):
    for _ in range(5):
        try:
            vectorstore.add_documents(batch)
            return
        except Exception as e:
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                time.sleep(60)
            else:
                raise
    raise RuntimeError("Gemini rate limit reached. Please try again in a few minutes.")


def ingest(on_progress):
    """Read PDFs in data/, chunk them, embed them, store them in Chroma.

    on_progress(stage, message, percent) is called as work advances.
    """
    on_progress("reading", "Reading PDFs", 0)
    documents = PyPDFDirectoryLoader(DATA_DIR).load()
    if not documents:
        raise ValueError("No readable text was found in the PDFs. Scanned PDFs without text can't be used.")

    splitter = RecursiveCharacterTextSplitter(chunk_size=1500, chunk_overlap=200)
    chunks = splitter.split_documents(documents)

    vectorstore = _vectorstore()
    total = len(chunks)
    on_progress("embedding", f"Embedded 0 of {total} passages", 0)

    for i in range(0, total, BATCH_SIZE):
        started = time.time()
        _add_with_retry(vectorstore, chunks[i:i + BATCH_SIZE])
        done = min(i + BATCH_SIZE, total)
        on_progress("embedding", f"Embedded {done} of {total} passages", int(done / total * 100))
        if done < total:
            time.sleep(max(0, WINDOW_SECONDS - (time.time() - started)))


def ask(question):
    """Retrieve the top chunks and generate an answer with sources."""
    docs = _vectorstore().as_retriever(search_kwargs={"k": 4}).invoke(question)
    context = "\n\n".join(d.page_content for d in docs)
    response = _get_chain().invoke({"context": context, "question": question})

    sources = []
    for d in docs:
        page = d.metadata.get("page")
        sources.append({
            "file": os.path.basename(d.metadata.get("source", "Unknown")),
            "page": page + 1 if isinstance(page, int) else None,  # PyPDF pages start at 0
            "snippet": " ".join(d.page_content.split())[:280],
        })
    return {"answer": response.text, "sources": sources}