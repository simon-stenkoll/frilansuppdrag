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
- `src/discovery.py`: djupskanning av Anna Leijons mäklarlista som genererar
  `state/portals.json`. Kandidatsidor bedöms med samma LLM-extrahering som nattkörningen
  (`portal_llm.reduce_html` + `extract_listings_llm` + `validate_items`): minst ett validerat
  uppdrag ger status "working", 0 items men listningssignaler ger "listing", annars "empty".
  Den billiga `listing_score`-heuristiken är gratis försortering, bara sidor med signaler
  kostar ett LLM-anrop. Egen budget `DISCOVERY_LLM_BUDGET`; portaler som inte hann få sin
  probe behåller sin tidigare status i stället för att nedgraderas. `--limit N` kör bara de
  N första mäklarna. Körs månadsvis av `.github/workflows/discovery.yml`
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
  **JS-rendering**: Playwright (chromium). **LLM**: Google Gemini via det OpenAI-kompatibla
  endpointet, modell `gemini-2.5-flash-lite` (GitHub Models pensionerades 2026-07-30 och
  svarar 410; byt aldrig tillbaka).
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
# Gratis nyckel skapas på https://aistudio.google.com/apikey.
# I CI ligger samma värde som repo-secreten GEMINI_API_KEY.
$env:GEMINI_API_KEY = "<google-ai-studio-nyckel>"
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
- Kör inte `src/discovery.py` i den nattliga workflowen; den är tung (Playwright plus LLM-probe
  mot ~130 sajter). Den har en egen månadsworkflow, "Monthly Portal Discovery", som kör den
  första i månaden och committar `state/portals.json`. Nattliga körningen läser bara filen.
