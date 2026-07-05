# Social Media Prediction Tool - Phase 1

## Current Status: Step 1 - Sample Collection Module

This is a modular LinkedIn post scraper using Apify's `harvestapi/linkedin-post-search` actor.

### What's Built

```
config/settings.py        - Environment configuration loader
scrapers/base_scraper.py  - Abstract interface for future platforms
scrapers/linkedin_scraper.py - LinkedIn scraper implementation
storage/sample_store.py   - Raw sample persistence (timestamped JSON)
dashboard/app.py          - Streamlit visual test harness
tests/                    - Mocked unit tests (no API cost)
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

3. **Test the scraper:**
   - Enter a search query (e.g., "ai marketing", "hiring software engineer")
   - Set max posts limit (start with 10-20 for testing)
   - Choose sort order (relevance or date)
   - Choose time filter if needed
   - Click "Run Scraper"
   - View results in table + raw JSON format
   - Confirm file saved to `data/raw/`

### LinkedIn Actor Details

**Actor:** `harvestapi/linkedin-post-search`

**Key Features:**
- Search posts by keywords (supports Boolean operators)
- No LinkedIn account/cookies required
- Fast response times
- $2 per 1k posts
- Can filter by author companies, profiles, time ranges

**Input Parameters (configured in dashboard):**
- `searchQueries` - Array of search terms (required)
- `maxPosts` - Max posts per query (default: 20)
- `sortBy` - "relevance" or "date"
- `postedLimit` - Time filter (1h, 24h, week, month, etc.)

**Output Data Includes:**
- Post content and LinkedIn URL
- Author information (name, profile, company)
- Engagement metrics (likes, comments, shares, reactions)
- Posted timestamp
- Images/media
- Optionally: reactions and comments (costs extra)

### Running Tests

```bash
pytest -q
```

All tests use mocked Apify client - no API charges.

### Next Steps

After validating scraper output:
- **Step 2:** "Make sense of samples" - AI pipeline to detect trends/patterns
- **Step 3:** Convert to structured dataset (CSV)
- **Step 4:** Personalization/fine-tuning
- **Step 5:** Client post evaluation

### Architecture Notes

Everything is modular:
- Adding TikTok/Instagram/X scrapers = new `BaseScraper` subclass
- No downstream code needs to change when platforms are added
- Raw samples stored untouched - normalization is Step 2's job
- Config in .env, never hardcoded
