"""Central configuration for the contract assignment scraper."""

# Keywords to match against job titles and descriptions (case-insensitive)
KEYWORDS = [
    "data engineer",
    "data engineering",
    "bi developer",
    "bi konsult",
    "business intelligence",
    "data analytics",
    "data analyst",
    "power bi",
    "microsoft fabric",
    "fabric",
    "sql",
    "etl",
    "data warehouse",
    "azure data factory",
    "databricks",
    "dbt",
    "data platform",
    "analytics engineer",
    "lakehouse",
    "synapse",
    "pyspark",
    "snowflake",
    "dax",
    "spark",
    "data modellering",
    "data modeling",
    "azure devops",
]

# Location filter terms (case-insensitive, any match = include)
LOCATION_KEYWORDS = ["stockholm", "sthlm", "remote", "hybrid"]

# GitHub Models API settings
GITHUB_MODELS_MODEL = "openai/gpt-4o-mini"  # new endpoint requires publisher prefix
GITHUB_MODELS_ENDPOINT = "https://models.github.ai/inference"

# LLM scoring behaviour
LLM_MAX_RETRIES = 3        # attempts per assignment before giving up
LLM_RETRY_BACKOFF = 5.0    # seconds before first retry; doubles per retry
LLM_REQUEST_DELAY = 4.0    # pause between calls (GitHub Models free tier is ~15 req/min)
LLM_RUN_BUDGET = 120       # max LLM calls per pipeline run, shared by all LLM consumers

# LLM classification (src/classifier.py + src/classify_cache.py)
CLASSIFY_STATE_FILE = "state/classifications.json"  # cached url -> classification record
CLASSIFY_MAX_AGE_DAYS = 90        # drop cached classifications older than this
CLASSIFIER_PROMPT_VERSION = 1     # bump to invalidate every cached classification

# Seen-state (src/state.py): url -> date last seen
SEEN_MAX_AGE_DAYS = 180           # drop seen entries not observed for this long

# Email notification settings (SMTP)
EMAIL_TO = "simon.stenlund@northintelligence.se"  # recipient of the daily digest
EMAIL_TO_ENV = "EMAIL_TO"          # optional override of the recipient
EMAIL_FROM_ENV = "EMAIL_FROM"      # optional sender address (defaults to SMTP_USER)
SMTP_HOST_ENV = "SMTP_HOST"
SMTP_PORT_ENV = "SMTP_PORT"
SMTP_USER_ENV = "SMTP_USER"
SMTP_PASSWORD_ENV = "SMTP_PASSWORD"
SMTP_HOST_DEFAULT = "smtp.gmail.com"
SMTP_PORT_DEFAULT = 587            # 587 = STARTTLS, 465 = implicit TLS
EMAIL_SUBJECT_PREFIX = "Konsultuppdrag"
EMAIL_MAX_ITEMS = 40               # cap assignments listed in the mail body
EMAIL_MIN_SCORE = 0                # 0 = no score threshold; >0 filters out lower-scored items
NOTIFY_WHEN_EMPTY = True           # send a short "no new assignments" message
# Fallback published-digest URL used when not running in GitHub Actions
PAGE_URL_FALLBACK = ""

# Scraper request timeout in seconds
REQUEST_TIMEOUT = 20

# Polite delay between requests to same domain (seconds)
SCRAPE_DELAY = 1.5

# ─── Broker discovery (src/discovery.py) ─────────────────────────────────────
# Anna Leijon's curated list of Swedish consultant brokers.
LEIJON_URL = "https://annaleijon.se/lista-pa-konsultmaklare-i-stockholm.html"
# Generated file recording which broker portals actually show assignments.
PORTALS_STATE_FILE = "state/portals.json"
# Sectors considered IT/tech-relevant when filtering the broker list.
DISCOVERY_IT_KEYWORDS = {
    "it", "tech", "data", "digital", "teknik", "system", "utveckl", "mgmt", "alla",
}
# Link text / href fragments that signal an assignment-listing page.
ASSIGNMENT_NAV_KEYWORDS = [
    "konsultuppdrag", "lediga uppdrag", "lediga konsultuppdrag", "aktuella uppdrag",
    "hitta uppdrag", "öppna uppdrag", "open-assignments", "assignments", "uppdrag",
    "frilans", "freelance",
]
# Max candidate listing pages to follow per broker during deep discovery.
DISCOVERY_MAX_LISTING_LINKS = 6
# How many brokers to investigate concurrently.
DISCOVERY_CONCURRENCY = 4
# Headless-browser navigation timeout (milliseconds).
PLAYWRIGHT_TIMEOUT_MS = 25000

# Temporarily disabled top-level scrapers due repeatable blocking/auth walls.
# Re-enable when source access is stable again. Empty for now: the scrapers that
# were parked here (Ework, Brainville, Indeed, LinkedIn) are removed.
DISABLED_SCRAPERS: set[str] = set()

# Temporarily disabled broker portals due repeatable HTTP blocking/errors.
DISABLED_BROKER_PORTALS = {
    "Interim Marketing",  # 404
}

# Cinode Market (src/scrapers/cinode_market.py)
# Public server-rendered marketplace; cursor pagination via #load-more-button.
CINODE_LIST_URL = "https://market.cinode.com/requests"
CINODE_MAX_PAGES = 15              # ~20 cards per page, ~110 assignments today

# Verama (src/scrapers/verama.py)
# Ework Group's marketplace; open JSON API, no auth. The platform is moving to
# an eworkgroup domain, so keep the endpoints configurable.
VERAMA_API_URL = "https://app.verama.com/api/public/job-requests"
VERAMA_DETAIL_URL = "https://app.verama.com/api/public/job-requests/{id}"
VERAMA_JOB_URL = "https://app.verama.com/en/job-requests/{id}"
VERAMA_PAGE_SIZE = 300             # whole catalogue (~200 items) fits in one page
VERAMA_MAX_PAGES = 5

# Broker portals with verified public assignment pages
# Source: scan of https://annaleijon.se/lista-pa-konsultmaklare-i-stockholm.html (2026-05-27)
BROKER_PORTALS = [
    # --- Konsultmäklare (verified assignment URLs) ---
    {
        "name": "A Society",
        "url": "https://www.asocietygroup.com/sv/uppdrag",
        "search_param": "q",
    },
    {
        "name": "Afry",
        "url": "https://afry.com/sv/bli-en-del-av-afry/afry-partner-network/Lediga-uppdrag",
        "search_param": "q",
    },
    {
        "name": "Aliant",
        "url": "https://aliant.recman.page/",
        "search_param": "q",
    },
    {
        "name": "Alphadev",
        "url": "https://assignments.alphadev.se",
        "search_param": "q",
    },
    {
        "name": "Biolit",
        "url": "https://www.biolit.se/uppdrag/",
        "search_param": "q",
    },
    {
        "name": "Brainville",
        "url": "https://www.brainville.com/HittaKonsultuppdrag",
        "search_param": "q",
    },
    {
        "name": "Donald Davis & Partners",
        "url": "https://ddp.se/sok-uppdrag/",
        "search_param": "q",
    },
    {
        "name": "House of Skills",
        "url": "https://www.houseofskills.se/konsultuppdrag/",
        "search_param": "q",
    },
    {
        "name": "Interim Search",
        "url": "https://www.interimsearch.com/publika-uppdrag/",
        "search_param": "q",
    },
    {
        "name": "Interim Marketing",
        "url": "https://interimmarketing.se/uppdrag",
        "search_param": "q",
    },
    {
        "name": "ITC Network",
        "url": "https://itcnetwork.se/oppna-uppdrag/",
        "search_param": "q",
    },
    {
        "name": "Jappa",
        "url": "https://www.jappa.jobs/jobb",
        "search_param": "q",
    },
    {
        "name": "KeyMan",
        "url": "https://www.keyman.se/sv/uppdrag/",
        "search_param": "q",
    },
    {
        "name": "Konsultfabriken",
        "url": "https://www.konsultfabriken.se/assignments/",
        "search_param": "q",
    },
    {
        "name": "Konsultkooperativet",
        "url": "https://konsult.coop/konsultuppdrag",
        "search_param": "q",
    },
    {
        "name": "Levigo",
        "url": "https://levigo.se/sv/assignments/",
        "search_param": "q",
    },
    {
        "name": "Nikita",
        "url": "https://www.nikita.se/jobs",
        "search_param": "q",
    },
    {
        "name": "Paventia",
        "url": "https://jobs.paventia.se/jobs/open",
        "search_param": "q",
    },
    {
        "name": "Pro4u",
        "url": "https://uppdrag.pro4u.se/",
        "search_param": "q",
    },
    {
        "name": "Profinder",
        "url": "https://www.profinder.se/lediga-uppdrag",
        "search_param": "q",
    },
    {
        "name": "Randstad",
        "url": "https://www.randstad.se/jobb/jt-konsultuppdrag/",
        "search_param": "q",
    },
    {
        "name": "Regent",
        "url": "https://regent.se/uppdrag/",
        "search_param": "q",
    },
    {
        "name": "Resursbrist",
        "url": "https://resursbrist.se/aktuella-uppdrag/",
        "search_param": "q",
    },
    {
        "name": "Right People Group",
        "url": "https://rightpeoplegroup.com/sv/open-assignments",
        "search_param": "q",
    },
    {
        "name": "Seequaly",
        "url": "https://seequaly.com/uppdrag",
        "search_param": "q",
    },
    {
        "name": "Senterprise",
        "url": "https://jobb.senterprise.se/departments/jobba-hos-oss",
        "search_param": "q",
    },
    {
        "name": "Sigma",
        "url": "https://www.sigma.se/sv/karriar/partner-uppdrag/",
        "search_param": "q",
    },
    {
        "name": "Tech Relations",
        "url": "https://www.techrelations.se/konsultuppdrag",
        "search_param": "q",
    },
    {
        "name": "Upgraded People",
        "url": "https://upgraded.se/lediga-uppdrag/",
        "search_param": "q",
    },
    {
        "name": "Wetal",
        "url": "https://wetal.com/sv/jobs",
        "search_param": "q",
    },
    {
        "name": "GetWiser",
        "url": "https://getwiser.se/",
        "search_param": "q",
    },
    {
        "name": "WiseOne",
        "url": "https://datakonsulter.info/WiseDki/StartController?assignments=on",
        "search_param": "q",
    },
]
