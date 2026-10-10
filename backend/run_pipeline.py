"""Terminal version: enter a topic, fetch papers, index them, then ask questions.

Run:  python3 backend/run_pipeline.py
"""
import os
import shutil
import subprocess
import sys

from config import DATA_DIR, DB_DIR
from fetch_papers import fetch_papers
from ingestion_pipeline import ingest

topic = input("Enter topic to research: ")

# Remove old papers and the old vector DB so topics don't get mixed
fresh = input("Remove old papers and database for a fresh start? (y/n, default y): ").strip().lower()
if fresh != "n":
    shutil.rmtree(DATA_DIR, ignore_errors=True)
    shutil.rmtree(DB_DIR, ignore_errors=True)
os.makedirs(DATA_DIR, exist_ok=True)

fetch_papers(topic, max_results=10)   # Step 1: fetch papers
ingest()                              # Step 2: ingestion

# Step 3: ask questions
here = os.path.dirname(os.path.abspath(__file__))
subprocess.run([sys.executable, os.path.join(here, "retrieval_pipeline.py")])