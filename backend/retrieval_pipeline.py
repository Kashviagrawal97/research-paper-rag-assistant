"""Retrieval pipeline: question -> relevant chunks -> LLM answer with sources.

Run on its own:  python3 backend/retrieval_pipeline.py
The web app (app.py) calls ask() too.
"""
import os

from langchain_core.prompts import ChatPromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI

from config import DB_DIR, get_vectorstore

prompt = ChatPromptTemplate.from_template("""
You are a helpful research assistant. Answer the question using ONLY the context below.
If the answer is not in the context, say "I don't have enough information in the provided papers."

Context:
{context}

Question: {question}

Answer:
""")


def ask(question):
    """Find the most relevant chunks and generate an answer with sources."""
    # Step 1: Retrieve the top 4 most relevant chunks
    retriever = get_vectorstore().as_retriever(search_kwargs={"k": 4})
    docs = retriever.invoke(question)
    context = "\n\n".join(doc.page_content for doc in docs)

    # Step 2: Generate the answer (if you get a model error, try "gemini-flash-latest")
    llm = ChatGoogleGenerativeAI(model="gemini-3.5-flash", temperature=0.2)
    response = (prompt | llm).invoke({"context": context, "question": question})

    # Step 3: Collect the sources
    sources = []
    for doc in docs:
        page = doc.metadata.get("page")
        sources.append({
            "file": os.path.basename(doc.metadata.get("source", "Unknown")),
            "page": page + 1 if isinstance(page, int) else None,  # PyPDF pages start at 0
            "snippet": " ".join(doc.page_content.split())[:280],
        })
    return {"answer": response.text, "sources": sources}


if __name__ == "__main__":
    if not os.path.isdir(DB_DIR):
        raise SystemExit("No library found. Run ingestion first (python3 backend/ingestion_pipeline.py).")

    while True:
        q = input("\nAsk a question (or 'exit' to quit): ")
        if q.lower() == "exit":
            break
        result = ask(q)

        print("\n--- ANSWER ---")
        print(result["answer"])

        print("\n--- SOURCES ---")
        for i, s in enumerate(result["sources"], start=1):
            print(f"{i}. {s['file']} (page {s['page']})")