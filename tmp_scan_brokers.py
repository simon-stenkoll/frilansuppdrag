"""Scan Anna Leijon's broker list for assignment pages.

1. Fetch the broker list page and extract website URLs from the table.
2. Visit each website and look for nav links indicating assignment listings.
"""

import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import re
import time

LEIJON_URL = "https://annaleijon.se/lista-pa-konsultmaklare-i-stockholm.html"

# Keywords that indicate an assignment listing page
ASSIGNMENT_KEYWORDS = [
    "uppdrag", "konsultuppdrag", "lediga uppdrag", "assignments",
    "lediga konsultuppdrag", "freelance", "frilans", "kontraktsuppdrag",
    "hitta uppdrag", "aktuella uppdrag", "våra uppdrag",
]

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


def extract_brokers_from_leijon():
    """Parse the broker table and extract name + website URL pairs."""
    resp = requests.get(LEIJON_URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    brokers = []
    seen = set()

    # Find all tables on the page
    for table in soup.select("table"):
        for row in table.select("tr"):
            cells = row.select("td")
            if len(cells) < 4:
                continue

            # First cell typically contains the broker name and link
            first_cell = cells[0]
            name_tag = first_cell.find("a")
            if not name_tag:
                # Try getting text as name
                name = first_cell.get_text(strip=True)
                if not name or len(name) < 2:
                    continue
                # Look for website link in other cells
                website = None
                for cell in cells[1:]:
                    for a in cell.find_all("a"):
                        href = a.get("href", "")
                        if href.startswith("http") and "annaleijon" not in href and "linkedin" not in href:
                            website = href
                            break
                    if website:
                        break
                if not website:
                    continue
            else:
                name = name_tag.get_text(strip=True)
                href = name_tag.get("href", "")
                if href.startswith("http"):
                    website = href
                else:
                    # Look in other cells
                    website = None
                    for cell in cells:
                        for a in cell.find_all("a"):
                            h = a.get("href", "")
                            text = a.get_text(strip=True).lower()
                            if h.startswith("http") and "annaleijon" not in h and "linkedin" not in h and text == "länk":
                                website = h
                                break
                        if website:
                            break

            if not website or not name:
                continue

            key = name.strip().lower()
            if key in seen:
                continue
            seen.add(key)

            # Get the sector from the second cell if available
            sector = cells[1].get_text(strip=True) if len(cells) > 1 else ""

            brokers.append({
                "name": name.strip(),
                "website": website.strip(),
                "sector": sector,
            })

    return brokers


def find_assignment_links(url, name):
    """Visit a website and look for nav links that suggest assignment listings."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15, allow_redirects=True)
        if resp.status_code >= 400:
            return {"status": resp.status_code, "links": [], "error": f"HTTP {resp.status_code}"}
    except Exception as e:
        return {"status": 0, "links": [], "error": type(e).__name__}

    soup = BeautifulSoup(resp.text, "html.parser")
    found = []

    # Look through all anchor tags
    for a in soup.find_all("a", href=True):
        href = a.get("href", "").strip()
        text = a.get_text(strip=True).lower()
        href_lower = href.lower()

        # Check text content and href for assignment keywords
        combined = text + " " + href_lower
        for kw in ASSIGNMENT_KEYWORDS:
            if kw in combined:
                full_url = urljoin(url, href)
                found.append({"text": a.get_text(strip=True), "url": full_url})
                break

    # Deduplicate by URL
    seen_urls = set()
    unique = []
    for item in found:
        if item["url"] not in seen_urls:
            seen_urls.add(item["url"])
            unique.append(item)

    return {"status": resp.status_code, "links": unique[:8], "error": None}


def main():
    print("=== Fetching broker list from Anna Leijon ===")
    brokers = extract_brokers_from_leijon()
    print(f"Found {len(brokers)} brokers with website URLs\n")

    # Filter to IT-relevant brokers only
    it_keywords = {"it", "tech", "alla", "mgmt", "teknik"}
    it_brokers = [
        b for b in brokers
        if any(k in b["sector"].lower() for k in it_keywords) or not b["sector"]
    ]
    print(f"Filtered to {len(it_brokers)} IT-relevant brokers\n")

    results_with_assignments = []
    results_no_assignments = []
    results_error = []

    for i, broker in enumerate(it_brokers):
        name = broker["name"]
        url = broker["website"]
        print(f"[{i+1}/{len(it_brokers)}] {name}: {url}")

        result = find_assignment_links(url, name)
        time.sleep(0.8)  # polite delay

        if result["error"]:
            print(f"  ERROR: {result['error']}")
            results_error.append({"name": name, "url": url, "error": result["error"]})
        elif result["links"]:
            print(f"  FOUND {len(result['links'])} assignment link(s):")
            for link in result["links"][:4]:
                print(f"    - [{link['text']}] -> {link['url']}")
            results_with_assignments.append({
                "name": name,
                "url": url,
                "links": result["links"],
            })
        else:
            print(f"  No assignment links found")
            results_no_assignments.append({"name": name, "url": url})

    print("\n" + "=" * 70)
    print(f"\n=== SUMMARY ===")
    print(f"\nBrokers WITH assignment pages ({len(results_with_assignments)}):")
    for r in results_with_assignments:
        best = r["links"][0]
        print(f"  {r['name']:30s} -> {best['url']}")

    print(f"\nBrokers WITHOUT assignment links ({len(results_no_assignments)}):")
    for r in results_no_assignments:
        print(f"  {r['name']:30s}    {r['url']}")

    print(f"\nBrokers with ERRORS ({len(results_error)}):")
    for r in results_error:
        print(f"  {r['name']:30s}    {r['error']}")


if __name__ == "__main__":
    main()
