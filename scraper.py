"""
KoeGuide Scraper - Municipal garbage collection page scraper.

Fetches municipal garbage pages, extracts clean text via BeautifulSoup,
and optionally uses Claude API for structured extraction.
Falls back to markdown-formatted text if no API key is available.

Usage:
    python scraper.py add "渋谷区" "https://www.city.shibuya.tokyo.jp/..."
    python scraper.py list
    python scraper.py scrape shibuya
    python scraper.py scrape-all
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

BASE_DIR = Path(__file__).parent
MUNICIPALITIES_FILE = BASE_DIR / "municipalities.json"
DATA_DIR = BASE_DIR / "municipality_data"

DATA_DIR.mkdir(exist_ok=True)


# ===========================================
# Municipality Registry
# ===========================================

def load_municipalities():
    if MUNICIPALITIES_FILE.exists():
        with open(MUNICIPALITIES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"municipalities": []}


def save_municipalities(data):
    with open(MUNICIPALITIES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def make_id(name):
    """Generate a filesystem-safe ID from a municipality name."""
    # Use romanized form or sanitized original
    import unicodedata
    normalized = unicodedata.normalize("NFKC", name)
    # Remove special chars, keep alphanumeric and some Japanese chars
    safe = re.sub(r'[^\w]', '_', normalized).strip('_').lower()
    return safe or "municipality"


def add_municipality(name, garbage_url, name_en=""):
    """Add a municipality to the registry."""
    data = load_municipalities()
    municipality_id = make_id(name)

    # Check for duplicate
    existing = [m for m in data["municipalities"] if m["id"] == municipality_id]
    if existing:
        existing[0]["garbage_url"] = garbage_url
        if name_en:
            existing[0]["name_en"] = name_en
        print(f"Updated: {name} ({municipality_id})")
    else:
        data["municipalities"].append({
            "id": municipality_id,
            "name": name,
            "name_en": name_en,
            "garbage_url": garbage_url,
            "last_scraped": None,
            "enabled": True,
        })
        print(f"Added: {name} ({municipality_id})")

    save_municipalities(data)
    return municipality_id


# ===========================================
# Web Scraping
# ===========================================

def fetch_page(url, timeout=30):
    """Fetch a page with encoding auto-detection (handles Shift_JIS, EUC-JP)."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) KoeGuide/1.0"
    }
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()

    # Auto-detect encoding (important for Japanese municipal sites)
    if resp.encoding and resp.encoding.lower() == "iso-8859-1":
        resp.encoding = resp.apparent_encoding
    return resp.text, resp.url


def extract_text(html, base_url=""):
    """Extract clean text content from HTML, removing navigation/boilerplate."""
    soup = BeautifulSoup(html, "html.parser")

    # Remove non-content elements
    for tag in soup(["script", "style", "nav", "header", "footer",
                     "iframe", "noscript", "aside"]):
        tag.decompose()

    # Remove elements commonly used for navigation
    for selector in [".nav", ".menu", ".sidebar", ".breadcrumb",
                     ".footer", ".header", "#nav", "#menu", "#sidebar",
                     '[role="navigation"]', '[role="banner"]']:
        for el in soup.select(selector):
            el.decompose()

    # Try to find main content area
    main = (
        soup.find("main")
        or soup.find("article")
        or soup.find(id=re.compile(r"content|main|body", re.I))
        or soup.find(class_=re.compile(r"content|main|body", re.I))
    )
    target = main if main else soup.body if soup.body else soup

    # Convert to structured text preserving some formatting
    lines = []
    for element in target.descendants:
        if element.name in ("h1", "h2", "h3", "h4"):
            text = element.get_text(strip=True)
            if text:
                level = int(element.name[1])
                lines.append(f"\n{'#' * level} {text}")
        elif element.name == "li":
            text = element.get_text(strip=True)
            if text:
                lines.append(f"- {text}")
        elif element.name == "tr":
            cells = [td.get_text(strip=True) for td in element.find_all(["td", "th"])]
            if any(cells):
                lines.append(" | ".join(cells))
        elif element.name == "p":
            text = element.get_text(strip=True)
            if text:
                lines.append(text)
        elif element.name == "br":
            lines.append("")

    # Deduplicate consecutive empty lines
    result = []
    prev_empty = False
    for line in lines:
        if not line.strip():
            if not prev_empty:
                result.append("")
            prev_empty = True
        else:
            result.append(line)
            prev_empty = False

    return "\n".join(result).strip()


def extract_links(html, base_url):
    """Extract sub-page links that might contain more garbage info."""
    soup = BeautifulSoup(html, "html.parser")
    links = []
    garbage_keywords = ["ゴミ", "ごみ", "ゴミ", "資源", "リサイクル", "粗大", "分別",
                        "収集", "廃棄", "trash", "garbage", "waste", "recycle"]

    for a in soup.find_all("a", href=True):
        text = a.get_text(strip=True)
        href = a["href"]
        if any(kw in text or kw in href for kw in garbage_keywords):
            full_url = urljoin(base_url, href)
            if urlparse(full_url).netloc == urlparse(base_url).netloc:
                links.append({"text": text, "url": full_url})

    # Deduplicate by URL
    seen = set()
    unique = []
    for link in links:
        if link["url"] not in seen:
            seen.add(link["url"])
            unique.append(link)
    return unique[:10]  # Limit to 10 sub-pages


# ===========================================
# LLM Extraction (optional, with Anthropic API)
# ===========================================

def get_anthropic_key():
    """Try to get Anthropic API key from Keychain."""
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-s", "anthropic", "-a", "api-key", "-w"],
            capture_output=True, text=True, check=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return None


def extract_via_llm(page_text, municipality_name):
    """Use Claude API to extract structured garbage collection info."""
    api_key = get_anthropic_key()
    if not api_key:
        return None

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)

        prompt = f"""以下は「{municipality_name}」のゴミ収集に関するウェブページの内容です。
この情報から、ゴミの分別・収集に関する情報を構造化JSONで抽出してください。

ページ内容:
{page_text[:8000]}

以下のJSON形式で出力してください（日本語と英語を併記）:
{{
  "municipality": "{municipality_name}",
  "categories": [
    {{
      "name": "燃えるゴミ",
      "name_en": "Burnable waste",
      "schedule": "月曜・木曜",
      "items": ["生ゴミ", "紙くず", ...],
      "bag_type": "指定ゴミ袋（黄色）",
      "rules": "朝8:00までに出す"
    }}
  ],
  "general_rules": "収集日の朝8:00までに指定場所に出してください",
  "oversized_items": {{
    "how_to": "電話予約が必要",
    "phone": "03-xxxx-xxxx",
    "fee": "品目により200〜2000円"
  }},
  "contact": "環境部清掃課 03-xxxx-xxxx",
  "notes": "年末年始は収集スケジュールが変更になります"
}}

ページに情報がない項目はnullにしてください。JSONのみ出力してください。"""

        response = client.messages.create(
            model="claude-sonnet-4-5-20250514",
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )

        # Parse JSON from response
        text = response.content[0].text
        # Extract JSON block
        json_match = re.search(r'\{[\s\S]*\}', text)
        if json_match:
            return json.loads(json_match.group())
    except Exception as e:
        print(f"LLM extraction failed: {e}")

    return None


# ===========================================
# Main Scrape Pipeline
# ===========================================

def scrape_municipality(municipality_id):
    """Full scrape pipeline for a municipality."""
    data = load_municipalities()
    municipality = next(
        (m for m in data["municipalities"] if m["id"] == municipality_id), None
    )
    if not municipality:
        raise ValueError(f"Municipality not found: {municipality_id}")

    url = municipality["garbage_url"]
    name = municipality["name"]
    print(f"Scraping {name}: {url}")

    # Fetch main page
    html, final_url = fetch_page(url)
    main_text = extract_text(html, final_url)
    sub_links = extract_links(html, final_url)

    # Fetch sub-pages (up to 5 for speed)
    sub_texts = []
    for link in sub_links[:5]:
        try:
            print(f"  Sub-page: {link['text']}")
            sub_html, sub_url = fetch_page(link["url"])
            sub_text = extract_text(sub_html, sub_url)
            if sub_text:
                sub_texts.append(f"## {link['text']}\n{sub_text}")
        except Exception as e:
            print(f"  Failed: {e}")

    # Combine all text
    all_text = main_text
    if sub_texts:
        all_text += "\n\n" + "\n\n".join(sub_texts)

    # Try LLM extraction first
    structured = extract_via_llm(all_text, name)

    # Build result
    result = {
        "municipality_id": municipality_id,
        "municipality": name,
        "municipality_en": municipality.get("name_en", ""),
        "source_url": url,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "structured": structured,  # None if LLM not available
        "raw_text": all_text[:15000],  # Keep raw text as fallback
        "sub_pages_scraped": len(sub_texts),
    }

    # Save cache
    cache_path = DATA_DIR / f"{municipality_id}.json"
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    # Update last_scraped
    municipality["last_scraped"] = result["scraped_at"]
    save_municipalities(data)

    print(f"Saved: {cache_path} ({len(all_text)} chars)")
    return result


def scrape_all():
    """Scrape all enabled municipalities."""
    data = load_municipalities()
    results = []
    for m in data["municipalities"]:
        if m.get("enabled", True):
            try:
                result = scrape_municipality(m["id"])
                results.append(result)
            except Exception as e:
                print(f"Failed to scrape {m['name']}: {e}")
    return results


def get_cached_data(municipality_id):
    """Load cached scrape data."""
    cache_path = DATA_DIR / f"{municipality_id}.json"
    if cache_path.exists():
        with open(cache_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def get_all_cached_data():
    """Load all cached data for enabled municipalities."""
    data = load_municipalities()
    results = []
    for m in data["municipalities"]:
        if m.get("enabled", True):
            cached = get_cached_data(m["id"])
            if cached:
                results.append(cached)
    return results


# ===========================================
# CLI
# ===========================================

def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python scraper.py add <name> <url> [name_en]")
        print("  python scraper.py list")
        print("  python scraper.py scrape <id>")
        print("  python scraper.py scrape-all")
        return

    cmd = sys.argv[1]

    if cmd == "add":
        if len(sys.argv) < 4:
            print("Usage: python scraper.py add <name> <url> [name_en]")
            return
        name = sys.argv[2]
        url = sys.argv[3]
        name_en = sys.argv[4] if len(sys.argv) > 4 else ""
        mid = add_municipality(name, url, name_en)
        print(f"Now scraping...")
        scrape_municipality(mid)

    elif cmd == "list":
        data = load_municipalities()
        for m in data["municipalities"]:
            status = "enabled" if m.get("enabled", True) else "disabled"
            scraped = m.get("last_scraped", "never")
            print(f"  {m['id']}: {m['name']} ({status}, last scraped: {scraped})")

    elif cmd == "scrape":
        if len(sys.argv) < 3:
            print("Usage: python scraper.py scrape <id>")
            return
        scrape_municipality(sys.argv[2])

    elif cmd == "scrape-all":
        scrape_all()

    else:
        print(f"Unknown command: {cmd}")


if __name__ == "__main__":
    main()
