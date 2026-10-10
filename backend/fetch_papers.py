import os
import requests
import arxiv

from config import DATA_DIR


def safe_name(title):
    name = "".join(c for c in title if c.isalnum() or c in (" ", "-")).strip()
    return name[:80]


def download_pdf(url, filepath):
    """PDF download karo, aur check karo ki sach mein PDF hai."""
    response = requests.get(url, timeout=20)
    if response.status_code != 200:
        return False
    if not response.content.startswith(b"%PDF"):
        return False  # kabhi kabhi HTML page aa jata hai, PDF nahi
    with open(filepath, "wb") as f:
        f.write(response.content)
    return True


def fetch_from_semantic_scholar(topic, max_results=10):
    print(f"Searching Semantic Scholar for: {topic}")

    url = "https://api.semanticscholar.org/graph/v1/paper/search"
    params = {
        "query": topic,
        "limit": max_results,
        "fields": "title,abstract,openAccessPdf,year,authors",
    }

    response = requests.get(url, params=params, timeout=20)

    if response.status_code != 200:
        print(f"Semantic Scholar ne error diya (status {response.status_code}). "
              f"Rate limit ho sakta hai, thodi der baad try karo. Skipping.")
        return

    papers = response.json().get("data", [])
    print(f"Found {len(papers)} papers on Semantic Scholar")

    downloaded = 0
    for i, paper in enumerate(papers):
        pdf_info = paper.get("openAccessPdf")

        if not pdf_info or not pdf_info.get("url"):
            print(f"{i+1}. No free PDF available: {paper['title']}")
            continue

        name = safe_name(paper["title"])
        filepath = os.path.join(DATA_DIR, f"{name}.pdf")

        if os.path.exists(filepath):
            print(f"{i+1}. Already exists: {name}")
            continue

        try:
            if download_pdf(pdf_info["url"], filepath):
                print(f"{i+1}. Downloaded: {name}")
                downloaded += 1
            else:
                print(f"{i+1}. Failed (not a valid PDF): {name}")
        except Exception as e:
            print(f"{i+1}. Error downloading {name}: {e}")

    print(f"Semantic Scholar: {downloaded} PDFs downloaded.")


def fetch_from_arxiv(topic, max_results=5):
    print(f"\nSearching ArXiv for: {topic}")

    search = arxiv.Search(
        query=topic,
        max_results=max_results,
        sort_by=arxiv.SortCriterion.Relevance,
    )
    client = arxiv.Client()
    results = list(client.results(search))

    downloaded = 0
    for i, paper in enumerate(results):
        name = safe_name(paper.title)
        filepath = os.path.join(DATA_DIR, f"{name}.pdf")

        if os.path.exists(filepath):
            print(f"{i+1}. Already exists: {name}")
            continue

        try:
            if download_pdf(paper.pdf_url, filepath):
                print(f"{i+1}. Downloaded: {name}")
                downloaded += 1
            else:
                print(f"{i+1}. Failed (not a valid PDF): {name}")
        except Exception as e:
            print(f"{i+1}. Error downloading {name}: {e}")

    print(f"ArXiv: {downloaded} papers downloaded.")


def fetch_papers(topic, max_results=10):
    os.makedirs(DATA_DIR, exist_ok=True)
    fetch_from_semantic_scholar(topic, max_results=max_results)
    fetch_from_arxiv(topic, max_results=5)
    print("\nAll done! Check 'data' folder.")


if __name__ == "__main__":
    topic = input("Enter topic to search papers on: ")
    fetch_papers(topic)