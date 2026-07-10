# Social Media Prediction Tool - Phase 1

## Current Status: Step 1 - Unified Sample Collection

Step 1 runs **post search** and **author profile enrichment** together on every
new collection via `processors/run_sample_collection.py` and `dashboard/app.py`.

### What's Built

```
config/settings.py              - Environment configuration loader
scrapers/base_scraper.py        - Abstract interface for future platforms
scrapers/linkedin_scraper.py    - LinkedIn post-search scraper
scrapers/linkedin_profile_scraper.py - Personal-author profile scraper
processors/run_sample_collection.py  - Unified post + profile collection
processors/profile_enricher.py  - Author classification + follower merge
storage/sample_store.py         - Raw sample persistence (timestamped JSON)
dashboard/app.py                    - Streamlit entry (sidebar: Scraper Stage, …)
dashboard/pages/1_Scraper_Stage.py - Scraper stage test harness
dashboard/pages/2_Post_Analyser.py - Streamlit Step 2 analysis harness
tests/                          - Mocked unit tests (no API cost)
```

### Quick Start

1. **Activate the virtual environment:**
   ```bash
   source .venv/bin/activate
   ```

2. **Run the test dashboard:**
   ```bash
   streamlit run dashboard/app.py
   ```

3. **Run a collection (posts + author profiles):**
   - Enter a search query (e.g., "ai marketing", "hiring software engineer")
   - Set max posts limit (start with 10-20 for testing)
   - Choose sort order (relevance or date)
   - Choose time filter if needed
   - Click **Run Collection**
   - View results in table + raw JSON format
   - Confirm files saved to `data/raw/` (posts + profiles) and `data/processed/` (enriched CSV)

4. **CLI equivalent:**
   ```bash
   python -m processors.run_sample_collection --search "ai marketing" --max-posts 20
   ```

### LinkedIn Actor Details

**Post search actor:** `harvestapi/linkedin-post-search` (`APIFY_ACTOR_ID`)

**Profile actor:** `harvestapi/linkedin-profile-scraper` (`APIFY_PROFILE_ACTOR_ID`)
- Only personal-profile authors are scraped (company follower counts come free from post data)

**Key Features:**
- Search posts by keywords (supports Boolean operators)
- No LinkedIn account/cookies required for post search
- Fast response times
- $2 per 1k posts (post search); profile scrape billed separately per author

**Input Parameters (configured in dashboard):**
- `searchQueries` - Array of search terms (required)
- `maxPosts` - Max posts per query (default: 20)
- `sortBy` - "relevance" or "date"
- `postedLimit` - Time filter (1h, 24h, week, month, etc.)

**Output Data Includes:**
- Post content and LinkedIn URL
- Author information (name, profile, company, follower count when enriched)
- Engagement metrics (likes, comments, shares, reactions)
- Posted timestamp
- Images/media

### Running Tests

```bash
pytest -q
```

All tests use mocked Apify client - no API charges.

### Next Steps

After validating collection output:
- **Step 2:** "Make sense of samples" — analysis pipeline (`dashboard/pages/2_Post_Analyser.py`)
- **Step 3+:** Pattern analysis, vectorisation, similarity search, evaluation cycle

### Architecture Notes

Everything is modular:
- Adding TikTok/Instagram/X scrapers = new `BaseScraper` subclass
- Post and profile raw files stay separate (`linkedin_*.json` vs `linkedin_profiles_*.json`) but share a timestamp when created together
- Profile-only backfill for legacy scans: `python -m processors.run_profile_enrichment`
- Config in .env, never hardcoded
