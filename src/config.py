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

# Number of top assignments to include in the digest (0 = all)
MAX_RESULTS = 30

# GitHub Models API settings
GITHUB_MODELS_MODEL = "gpt-4o-mini"
GITHUB_MODELS_ENDPOINT = "https://models.inference.ai.azure.com"

# Scraper request timeout in seconds
REQUEST_TIMEOUT = 20

# Polite delay between requests to same domain (seconds)
SCRAPE_DELAY = 1.5

# Temporarily disabled top-level scrapers due repeatable blocking/auth walls.
# Re-enable when source access is stable again.
DISABLED_SCRAPERS = {
    "Ework",
    "Brainville",
    "Indeed",
    "LinkedIn (Google)",
}

# Temporarily disabled broker portals due repeatable HTTP blocking/errors.
DISABLED_BROKER_PORTALS = {
    "Interim Marketing",  # 404
}

# Indeed search config
INDEED_BASE_URL = "https://se.indeed.com"
INDEED_SEARCH_QUERIES = [
    "data+engineer+konsult",
    "BI+developer+konsult",
    "data+analytics+konsult",
    "microsoft+fabric+konsult",
]
INDEED_LOCATION = "Stockholm"

# Ework search config
EWORK_SEARCH_URL = "https://www.ework.se/uppdrag"
EWORK_SEARCH_PARAMS = {"query": "data", "location": "Stockholm"}

# Brainville search config
BRAINVILLE_SEARCH_URL = "https://www.brainville.com/assignments"

# Cinode Market search config
CINODE_SEARCH_URL = "https://app.cinode.com/market/assignments"

# Keywords that indicate a freelance / contract assignment (vs permanent employment)
CONTRACT_KEYWORDS = [
    "konsultuppdrag",
    "uppdrag",
    "freelance",
    "frilans",
    "frilansuppdrag",
    "contract",
    "contractor",
    "interim",
    "interimsuppdrag",
    "underkonsult",
    "konsult",
    "kontrakts",
    "uppdragsperiod",
    "uppdragsstart",
    "timpris",
]

# Keywords that indicate a permanent job (used to exclude non-contract listings)
PERMANENT_KEYWORDS = [
    "tillsvidareanställning",
    "fast anställning",
    "fast tjänst",
    "permanent",
    "anställning",
    "provanställning",
    "rekrytering",
    "heltidstjänst",
    "tills vidare",
]

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

# Google search for LinkedIn jobs (via scraping search results)
GOOGLE_LINKEDIN_QUERIES = [
    'site:linkedin.com/jobs "data engineer" "Stockholm"',
    'site:linkedin.com/jobs "BI developer" "Stockholm"',
    'site:linkedin.com/jobs "Microsoft Fabric" "Stockholm"',
    'site:linkedin.com/jobs "data analytics" "Stockholm" konsult',
]
