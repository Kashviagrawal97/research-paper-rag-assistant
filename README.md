# Research Paper Assistant

A RAG web app for asking questions about research papers. Every answer shows the passages it came from, with the paper name and page number.

Build your library in one of two ways:

- **Search by topic:** finds papers on arXiv and Semantic Scholar and downloads the ones with a free PDF
- **Upload PDFs:** add up to 8 papers of your own

## How it works

**Ingestion:** PDFs → chunks → Gemini embeddings → Chroma vector DB

**Retrieval:** question → top 4 similar chunks → Gemini → answer with sources

**Stack:** FastAPI, LangChain, Gemini (embeddings and LLM), Chroma, HTML/CSS/JS

## Project structure

```
backend/
  app.py                  FastAPI server
  config.py               Paths and shared vector store
  fetch_papers.py         Finds and downloads papers
  ingestion_pipeline.py   PDFs to vector DB
  retrieval_pipeline.py   Question to answer
frontend/                
  index.html
  style.css
  script.js
```

## Getting started

You need Python 3.10+ and a free Gemini API key from [Google AI Studio](https://aistudio.google.com/apikey).

```bash
git clone https://github.com/<your-username>/research-paper-rag-assistant.git
cd research-paper-rag-assistant
pip install -r requirements.txt
```

Create a `.env` file in the project folder with your key:

```
GOOGLE_API_KEY=your_key_here
```

Run the app and open **http://127.0.0.1:8000**:

```bash
python3 backend/app.py
```