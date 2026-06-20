# NI - Contracts

Automatisk daglig sammanställning av Data Engineering / BI / Analytics-konsultuppdrag i Stockholm.

Python + GitHub Actions. Körs varje vardag kl. 16:00 CEST.

---

## Pipeline-flöde

```mermaid
flowchart TD
    A([Cron 16:00 CEST]) --> B[run_all_scrapers]

    B --> C["Platsbanken<br/>JobTech API"]
    B --> D["Broker Portals<br/>32 svenska IT-bolag"]

    C --> E["list[Assignment]"]
    D --> E

    E --> F["deduplicate<br/>URL + fuzzy-titel 80%"]
    F --> G["is_contract filter<br/>utesluter fasta tjänster"]
    G --> H["mark_new<br/>jämför mot seen.json"]
    H --> I["summarize<br/>LLM-scoring 1-10"]
    I --> J["generate<br/>HTML-digest"]

    J --> K[(docs/index.html)]
    J --> L[(docs/archive/YYYY-MM-DD.html)]
    H --> M[(state/seen.json)]
```

---

## Arkitektur

```mermaid
graph LR
    subgraph Repo
        main["main.py<br/>orkestrerare"]
        config["src/config.py<br/>nyckelord, inställningar"]
        models["src/models.py<br/>Assignment"]
        dedup["src/dedup.py"]
        state["src/state.py"]
        summarizer["src/summarizer.py"]
        digest["src/digest.py"]
        scrapers["src/scrapers/"]
    end

    subgraph Externa
        jobtechAPI["JobTech API<br/>platsbanken"]
        brokers["Broker-webbsidor<br/>32 portaler"]
        llm["GitHub Models API<br/>gpt-4o-mini"]
    end

    subgraph Output
        html["docs/index.html<br/>docs/archive/"]
        json["state/seen.json"]
    end

    main --> scrapers
    scrapers --> jobtechAPI
    scrapers --> brokers
    main --> dedup
    main --> state
    main --> summarizer
    summarizer --> llm
    main --> digest
    digest --> html
    state --> json
    config -.-> main
    models -.-> scrapers
```

---

## Scraper-karta

```mermaid
flowchart LR
    subgraph Aktiva["Aktiva"]
        PB["Platsbanken<br/>JobTech REST API"]
        BP["Broker Portals<br/>32 portaler"]
    end

    subgraph Avstangda["Avstängda"]
        EW["Ework<br/>HTTP-blockering"]
        BV["Brainville<br/>HTTP-blockering"]
        IN["Indeed<br/>Kräver auth"]
        LI["LinkedIn via Google<br/>Opålitlig"]
    end

    subgraph BrokerMetoder["Broker-metoder"]
        API1["A Society - JSON API"]
        API2["KeyMan - WordPress REST"]
        API3["Upgraded People - WordPress REST"]
        HTML["Övriga - HTML-scraping"]
        SKIP["Unscrapable<br/>JS SPA / login-wall"]
    end

    BP --> API1
    BP --> API2
    BP --> API3
    BP --> HTML
    BP --> SKIP
```

---

## GitHub Actions

```mermaid
flowchart TD
    T(["Cron: 0 14 * * 1-5<br/>eller manuell trigger"]) --> A

    A["Checkout repo"] --> B["Setup Python 3.11<br/>+ pip cache"]
    B --> C["pip install -r requirements.txt"]
    C --> D["python main.py<br/>GITHUB_MODELS_TOKEN från secret"]
    D --> E{"Ändringar?"}
    E -- Ja --> F["git commit & push<br/>docs/ + state/seen.json"]
    E -- Nej --> G([Klar - inga nya uppdrag])
    F --> G
```

---

## Setup

### 1. Lägg till secret

**Settings → Secrets → Actions:**

| Secret | Värde |
|---|---|
| `GITHUB_MODELS_TOKEN` | GitHub PAT med `models:read`-scope |

### 2. Aktivera GitHub Pages (valfritt)

**Settings → Pages** → källa: `docs/`-mappen på `main`.  
Digest publiceras på `https://<username>.github.io/<repo>/`.

### 3. Kör lokalt

```bash
pip install -r requirements.txt
set GITHUB_MODELS_TOKEN=<din_token>   # Windows
python main.py
# Öppna docs/index.html i webbläsaren
```

### 4. Trigga manuellt

**Actions → Daily Contract Digest → Run workflow**

---

## Projektstruktur

```
main.py                  # orkestrerare
src/
  config.py              # nyckelord, URL:er, inställningar
  models.py              # Assignment-dataclass
  dedup.py               # deduplicering över källor
  state.py               # hanterar state/seen.json
  summarizer.py          # LLM-scoring + sammanfattning
  digest.py              # HTML-generator → docs/
  scrapers/
    jobtech.py           # Platsbanken (JobTech API)
    broker_portals.py    # Svenska IT-brokers (32 portaler)
    ework.py             # ework.se (avstängd)
    brainville.py        # brainville.com (avstängd)
    indeed.py            # se.indeed.com (avstängd)
    linkedin_google.py   # LinkedIn via Google (avstängd)
    utils.py             # is_relevant, is_contract, is_in_stockholm
docs/
  index.html             # senaste digest
  archive/               # dagligt arkiv YYYY-MM-DD.html
state/
  seen.json              # sedda URL:er (persisteras i Git)
```

---

## Konfiguration

Allt i `src/config.py`:

- **`KEYWORDS`** — 28 tekniktermer som triggar ett uppdrag (data engineer, power bi, dbt, etc.)
- **`CONTRACT_KEYWORDS`** / **`PERMANENT_KEYWORDS`** — avgör om ett jobb är konsultuppdrag
- **`LOCATION_KEYWORDS`** — stockholm, remote, hybrid
- **`DISABLED_SCRAPERS`** — scrapers som inte körs (Ework, Brainville, Indeed, LinkedIn)
- **`DISABLED_BROKER_PORTALS`** — enskilda portaler som är 404 eller blockerade
- **`MAX_RESULTS`** — max antal uppdrag som skickas till LLM (standard: 30)
- **`LLM_MODEL`** — `gpt-4o-mini` via GitHub Models API

---

## Lägga till en ny scraper

1. Skapa `src/scrapers/min_scraper.py` med signaturen:
   ```python
   async def scrape() -> list[Assignment]:
       ...
   ```
2. Registrera i `SCRAPERS`-listan i `main.py`.
3. Använd `is_relevant()`, `is_contract()`, `is_in_stockholm()` från `scrapers/utils.py` för filtrering.
