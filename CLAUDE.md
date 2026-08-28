# CLAUDE.md

Guidance for Claude Code (and other AI assistants) working in this repository.

## Vad projektet gör

Daglig pipeline som skrapar konsult-/frilansuppdrag inom Data Engineering / BI / Analytics i
Stockholm, deduplicerar, klassificerar och poängsätter med en LLM, genererar en
HTML-digest i `docs/` och notifierar via e-post. Körs nattligt via GitHub Actions (`workflow_dispatch`
finns för manuella körningar) och kan köras lokalt.

## Arkitektur (dataflöde)

`main.py` orkestrerar: `run_all_scrapers()` → `deduplicate()` → `flag_new()` (jämför mot
`state/seen.json`) → `classify()` (LLM-klassificering, pipelinens beslutsgrind) →
`persist_seen()` → `generate()` (HTML) → `send_email()` (notis).

Routingen i `src/routing.py` (`is_qualified` / `disqualify_reason`) är enda sanningskällan för
vad som räknas som ett kvalificerat uppdrag: mailet skickar bara nya kvalificerade, webben visar
allt men delat i "Uppdrag" och "Osäkra / anställningar".

- `src/config.py` — all konfiguration: nyckelord, portallista (seed), env-namn, gränser
- `src/models.py` — `Assignment`-dataclass (det enda objektet som flödar genom pipelinen)
- `src/scrapers/`: en modul per källa; varje exponerar `async def scrape() -> list[Assignment]`.
  Källor: `jobtech.py` (Platsbanken/JobTech API), `broker_apis.py` (A Society, Upgraded
  People, KeyMan), `portal_llm.py`, `cinode_market.py` och `verama.py`. De handskrivna
  HTML-parsarna i `broker_portals.py` gav nästan inget och är borttagna.
- `src/scrapers/portal_llm.py`: hämtar mäklarportalerna i `state/portals.json`, reducerar
  HTML till text och låter LLM:en extrahera uppdragen som JSON. Sidhash-cache i
  `state/portal_pages.json` gör att oförändrade sidor inte kostar något LLM-anrop, och
  anropen begränsas av `PORTAL_LLM_MAX_CALLS` plus den delade `LlmBudget` som `main.py`
  skickar in med `set_budget()`
- `src/scrapers/cinode_market.py`: Cinode Market (market.cinode.com), publik serverrenderad
  HTML, cursor-paginering via `#load-more-button`, detaljsida hämtas bara för relevanta kort
- `src/scrapers/verama.py`: Verama (Ework Groups marknadsplats), öppet JSON-API utan auth,
  beskrivning hämtas per uppdrag från detaljendpointen efter land-, ort- och nyckelordsfilter
- `src/scrapers/utils.py`: delade filter (`is_relevant`, `is_in_stockholm`),
  `make_client()` (httpx) och `fetch_rendered()` (Playwright för JS-portaler)
- `src/scrapers/legacy_extract.py`: generisk HTML-extrahering som BARA används av
  `discovery.py`, tas bort när discovery byggs om
- `src/discovery.py` — engångs/sällan-körd djupskanning av Anna Leijons mäklarlista som genererar
  `state/portals.json`
- `src/classifier.py`: LLM-klassificerare (employment_type, role_match, location_ok, status,
  score, summary) med delad `LlmBudget` per körning
- `src/classify_cache.py`: cache i `state/classifications.json`, nyckel på url + content_hash +
  prompt_version
- `src/routing.py`: `is_qualified()` och `disqualify_reason()`, delade av digest och notify
- `src/digest.py`: bygger `docs/index.html` + `docs/archive/YYYY-MM-DD.html`, tvådelad sida
- `src/notify.py`: mailar nya kvalificerade uppdrag via SMTP (Gmail app-lösenord)
- `state/seen.json`: sedda URL:er som `{"url": "YYYY-MM-DD"}` med datum för senast sedd
  (spåras i git, persisteras mellan körningar). Bara klassificerade uppdrag läggs till,
  så budgetuppskjutna uppdrag förblir "nya"; kända nycklar som dyker upp igen får nytt
  datum och poster äldre än `SEEN_MAX_AGE_DAYS` rensas vid skrivning. Gamla listformatet
  läses fortfarande och konverteras vid första körningen
- `state/classifications.json`: cachade LLM-klassificeringar (spåras i git)
- `state/portals.json` — upptäckta/verifierade mäklarportaler (genereras av discovery)
- `state/portal_pages.json`: sidhash + senast extraherade uppdrag per portal-listningssida
  (spåras i git)

## Konventioner

- **Python 3.11+**. **HTTP**: `httpx` (async) för scraping. **HTML**: `BeautifulSoup4`.
  **JS-rendering**: Playwright (chromium). **LLM**: GitHub Models API (OpenAI-kompatibelt SDK),
  modell `gpt-4o-mini`.
- **Scraper-interface**: varje scraper exponerar `async def scrape() -> list[Assignment]`.
- **Felisolering**: en scraper som kastar exception måste fångas i orkestreraren — ett fel får
  aldrig stoppa övriga. Samma princip gäller notifiering.
- **Config**: lägg nya nyckelord/URL:er/inställningar i `src/config.py`, inte hårdkodat i moduler.
- **Surgical changes**: ändra bara det som behövs; ingen refaktorering av orörd kod (se
  `.github/copilot-instructions.md` för fullständiga riktlinjer — de gäller även här).

## Kör lokalt (Windows / PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m playwright install chromium      # för JS-tunga mäklarportaler

# Hemligheter (per session, eller lägg i en .env som inte committas)
# OBS: PAT:en måste vara fine-grained med behörigheten "Models: read" —
# utan den svarar GitHub Models 401. I CI behövs ingen PAT: workflowen
# använder inbyggda GITHUB_TOKEN med `models: read`-permission.
$env:GITHUB_MODELS_TOKEN = "<github-pat-med-models:read>"
# E-postnotis via SMTP (Gmail kräver app-lösenord, inte kontolösenordet)
$env:SMTP_USER = "<gmail-adress>"
$env:SMTP_PASSWORD = "<app-losenord>"

python -m src.discovery     # (sällan) bygg om state/portals.json
python main.py              # full körning → docs/ + e-post
```

Öppna `docs/index.html` i webbläsaren för att se resultatet.

## Att tänka på

- `classify()` och `send_email()` failar tyst (loggar) om token/SMTP-uppgifter saknas: körningen
  fortsätter ändå och digesten genereras.
- Kör inte `src/discovery.py` i den nattliga workflowen; den är tung (Playwright mot ~130 sajter).
  Nattliga körningen läser bara `state/portals.json`.
