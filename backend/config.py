"""Shared paths, settings and the vector store used by both pipelines."""
from pathlib import Path

from dotenv import load_dotenv
from langchain_chroma import Chroma
from langchain_google_genai import GoogleGenerativeAIEmbeddings

ROOT = Path(__file__).resolve().parent.parent   # research-paper-rag-assistant/
DATA_DIR = str(ROOT / "data")                   # downloaded / uploaded PDFs
DB_DIR = str(ROOT / "chroma_db")                # Chroma vector database
FRONTEND_DIR = str(ROOT / "frontend")           # index.html, style.css, script.js

load_dotenv(ROOT / ".env")                      # reads GOOGLE_API_KEY


def get_vectorstore():
    # Ingestion and retrieval both call this, so they always use the same embedding model.
    embeddings = GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-2")
    return Chroma(persist_directory=DB_DIR, embedding_function=embeddings)