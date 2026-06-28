# The Docket — Setup & Implementation Guide

One guide to deploy the planner from scratch **or** update an existing install to **v2**.
v2 adds **recipe import from a URL**, a **shop-day picker**, and two script-breaking **bug fixes**.

> **Already running v1?** Only `planner.html` changed. Drop in the new file (Step 2), run the checks (Step 5), commit (Step 6) — done. Skip repo creation. Everything else below is unchanged.

---

## What's in v2

### Bug fixes (these were breaking the deployed page)

1. **`renderReceipt` / `mkgrp` ternary** — `!items.length?""` was missing the `:` of its ternary. That's a JavaScript syntax error, so the **entire `<script>` block fails to parse and nothing on the page runs**. Now `!items.length?"":` …
2. **`loadDemoData`** — a demo item used a bare `e` instead of the string `"e"`, throwing `ReferenceError` whenever the demo fallback runs (any time `thisweek.json` isn't loaded, including local testing). Now `"e"`.

If you deployed v1, your live copy almost certainly has both — Step 5's checks confirm they're gone in whatever you ship.

### Recipe import from a URL

- A **“+ Add a meal to the bank”** button on the **Meals** tab opens a sheet with three tabs: **🔗 From a link**, **✍️ Type it**, **Added (n)**.
- **From a link:** paste a recipe URL → **Fetch**. A static page can't read other sites directly (browser CORS), so the page is pulled through a public CORS proxy, then the **schema.org `Recipe` JSON-LD** (the structured data behind Google's recipe cards) is parsed. A lighter DOM fallback handles pages without it.
- The result **prefills the “Type it” form for review** — a recipe page has no store, price, or FODMAP status. Ingredients arrive with store = *Either* and blank prices; the FODMAP tag is prefilled **⚠ check FODMAP** so an unverified recipe is visibly flagged until you set it.
- **Added (n)** lists recipes added on this device, lets you delete them, and offers **Copy for recipe-bank.json** (see “Making imported recipes permanent”).
- Added recipes persist in the browser and join the current week's swap pool immediately — use **↻ Swap** on a meal to put one on the menu.

### Shop-day picker

- A row of seven buttons (Mon–Sun) on the **Setup** tab, defaulting to **Sun**.
- Tapping a day updates the meal-day labels, the receipt header, and the copied list. Day 1 of the week *is* the shop day, so the whole week's labels shift with it.

### localStorage keys (reference)

| Key | Holds |
|-----|-------|
| `docket_plan` | per-slot meal / people / skipped |
| `docket_shopday` | chosen shop day, e.g. `"Sun"` |
| `docket_custom_recipes` | recipes added on this device |
| `docket_proxy` | preferred CORS proxy id |

---

## Architecture

```
┌─ GitHub Actions (Tuesday 8 PM Perth / 12 PM UTC) ─┐
│  → Fetch Coles + Woolies catalogues               │
│  → Match recipes to specials                      │
│  → Generate thisweek.json → push to repo          │
└────────────────────────────────────────────────────┘
                       ↓
         ┌─ GitHub Pages (your repo) ─┐
         │  → host planner.html        │
         │  → host thisweek.json       │
         │  → host recipe-bank.json    │
         └──────────────────────────────┘
                       ↓
         ┌─ Family (mobile browser) ─┐
         │  → open shared link        │
         │  → pick shop day           │
         │  → view / approve meals    │
         │  → add recipes from a URL  │
         │  → build shopping lists    │
         └────────────────────────────┘
```

---

## Step 1 — Create the GitHub repository

*(Skip if updating an existing install.)*

1. **github.com → New repository.**
2. Name it `docket-planner`.
3. Make it **Public** (so family can reach it via GitHub Pages).
4. Initialize with a README.
5. Clone locally:
   ```bash
   git clone https://github.com/YOUR_USERNAME/docket-planner.git
   cd docket-planner
   ```

---

## Step 2 — Add the files

Place these in the repo, matching this layout:

```
docket-planner/
├── planner.html                 ← the web app (v2)
├── recipe-bank.json             ← recipe library
├── thisweek.json                ← auto-generated each Tuesday (not committed by hand)
├── generate-thisweek.py         ← the catalogue + matching routine
├── .github/
│   └── workflows/
│       └── generate-meals.yml   ← Actions schedule
├── SETUP.md                     ← this guide
└── HANDOFF.md                   ← system overview (optional)
```

Create the workflow folder and move the file into it:

```bash
mkdir -p .github/workflows
mv generate-meals.yml .github/workflows/generate-meals.yml   # leading dot is required
```

> **Updating from v1:** keep a backup first — `cp planner.html planner.html.bak` — then overwrite `planner.html` with the v2 file.
>
> **Note:** v2 `planner.html` already loads `thisweek.json` dynamically, so the old "edit planner.html to add JSON loading" step from earlier versions is gone — don't re-add it.

---

## Step 3 — Enable GitHub Pages

1. **Settings → Pages.**
2. Source: **Deploy from a branch.**
3. Branch: **main**, folder: **/ (root)**.
4. Save.

Your planner is served at `https://YOUR_USERNAME.github.io/docket-planner/`.

---

## Step 4 — Configure GitHub Actions

1. The workflow runs **Tuesday 8 PM Perth time** (`cron: '0 12 * * 2'`) and can be triggered manually from the **Actions** tab.
2. **Optional secret:** Settings → Secrets and variables → Actions → add `COMMIT_EMAIL` (your GitHub email). `GITHUB_TOKEN` is provided automatically.
3. **Test it:** Actions tab → **Generate Weekly Meals** → **Run workflow**. Watch it fetch catalogues and push `thisweek.json`. Green check = success; red X → open the run to see the error (usually a catalogue-parsing selector that needs updating in `generate-thisweek.py`).

---

## Step 5 — Verify and test locally

### a) Confirm the right file (especially the bug fixes)

```bash
grep -n '!items.length?"":'      planner.html   # bug fix 1 present
grep -n '\["Chicken","e",10'     planner.html   # bug fix 2 present
grep -n 'data-tab="link"'        planner.html   # URL-import tab
grep -n 'function rbExtractJsonLd' planner.html # JSON-LD parser
grep -n 'id="dayRow"'            planner.html   # shop-day picker
```

(PowerShell: swap `grep -n '…'` for `Select-String -Path planner.html -Pattern '…'`.) Each should return a match. If the first two return nothing, you're on an old copy.

### b) Test the planner

`fetch()` needs **http://**, not `file://`, so serve the folder:

```bash
python3 -m http.server 8000
```

Open **http://localhost:8000/planner.html** and check:

1. **Page loads** (week line populates, or shows the demo week). A blank/dead page means the script is broken — that's what the bug fixes prevent.
2. **Setup → Shop day:** tap a few days; your pick highlights and survives a refresh.
3. **Meals → “+ Add a meal to the bank” → From a link:** paste a URL from a mainstream recipe site (taste.com.au, RecipeTin Eats, AllRecipes, BBC Good Food) → **Fetch**. It should switch to **Type it** with name, ingredients, method, and often nutrition filled in.
4. **Console (F12):** fetch/parse issues and proxy fallbacks log here.

### c) (Optional) Test the generator

```bash
pip install requests beautifulsoup4 playwright
playwright install chromium

export COLES_SALEID=66019
export WOOLIES_SALEID=66046
export GITHUB_REPO=YOUR_USERNAME/docket-planner
export GITHUB_EMAIL=your-email@example.com
export REPO_PATH=$(pwd)

python3 generate-thisweek.py
```

Expected (counts vary with the current recipe bank — ~48 recipes):

```
[1/5] Loading recipe bank...      Loaded 48 recipes
[2/5] Fetching Coles catalogue... Extracted 150+ items
[3/5] Fetching Woolworths...      Extracted 200+ items
[4/5] Matching recipes...         Selected 12 recipes for the week
[5/5] Pushing to GitHub...        [✓] Done!
```

---

## Step 6 — Deploy

```bash
git add .
git commit -m "Deploy The Docket v2 (URL import + shop-day picker + bug fixes)"
git push
```

GitHub Pages redeploys automatically (usually under a minute). **Hard-refresh** (Ctrl/Cmd-Shift-R) to bypass the cached old `planner.html`. Share `https://YOUR_USERNAME.github.io/docket-planner/` with the family.

---

## Using The Docket

### Weekly workflow

1. **Tuesday 8 PM** — Actions runs; `thisweek.json` regenerates and pushes.
2. **Wednesday morning** — open the planner, see the new week.
3. **Wed–Sun** — pick a shop day, skip/swap meals, build the shopping list.
4. **Sunday** — shop with the list (Coles in-store, Woolies online).

### Choosing your shop day

On the **Setup** tab, tap a day in the **Shop day** row. It saves to `docket_shopday` and shifts the whole week's labels (day 1 = shop day). This is the planner's *display* day only — it does **not** change the Tuesday Actions schedule (see “Keeping things in sync”).

### Adding recipes from a link

1. **Meals → “+ Add a meal to the bank” → From a link** → paste URL → **Fetch**.
2. If it fails, open **Source & proxy settings** and switch proxy (AllOrigins → corsproxy.io → codetabs), then retry.
3. Review in **Type it**: assign **stores** and **prices**, replace the **⚠ check FODMAP** tag once verified, add a waste note.
4. **Add to bank**, then **↻ Swap** a meal until your recipe appears.

### Making imported recipes permanent

Recipes added in the app live in **that browser only**. To add them to the shared bank so the Tuesday automation can pick them every week:

1. **Added (n) → Copy for recipe-bank.json** (copies your custom recipes as a JSON array).
2. Paste those objects **inside the existing `"recipes": [ … ]` array** in `recipe-bank.json` (comma-separate entries). Each already matches the schema:
   ```json
   {
     "id": "…", "name": "…", "desc": "…", "fod": "Low FODMAP · LF · GF",
     "serves": 2,
     "nut": {"kj": 0, "prot": 0, "fib": 0, "carb": 0},
     "waste": "…",
     "recipe": ["step", "step"],
     "items": [["Ingredient", "e", 0, null, "note"]]
   }
   ```
3. Validate, then commit: `python3 -m json.tool recipe-bank.json` (catches stray commas) → `git add recipe-bank.json && git commit && git push`.

### Household sharing

The planner uses **localStorage**, so approvals/skips/shop-day are shared per browser on a device. Family members visit the same link; their browser keeps the household's state. Cross-network sync (e.g. Supabase) or a URL-encoded “share plan” link are optional future additions — not built in.

---

## Troubleshooting

**Page is blank after deploy** — Run Step 5a's first two checks against the *deployed* file, and hard-refresh to clear the cached old copy. A missing-colon `mkgrp` or bare `e` will kill the whole page.

**A URL won't import** — Switch proxy under **Source & proxy settings** and retry. Sites behind a login/paywall, or that render entirely client-side, often expose no readable recipe data — use **Type it**. The proxies are free public services; any one can be rate-limited or down (the Fetch button tries your preferred one first, then the others automatically).

**Imported nutrition/serves look off** — Calories are converted to kJ (× 4.184). If a site reports per-100g rather than per-serve, the numbers reflect that — adjust before saving.

**FODMAP tag still says “⚠ check FODMAP”** — Intentional. Imports aren't FODMAP-verified; edit the `Diet tags` field in **Type it** before saving.

**Day labels look shifted** — Expected. Day 1 = shop day; the “· shop day” marker sits on day 1.

**Added recipes vanished** — They're per-browser (localStorage). A different device/browser, or cleared site data, won't have them. Use “Making imported recipes permanent” for durability.

**No items extracted from catalogues** — Coles/Woolies HTML changes periodically. Update the BeautifulSoup selectors / `parse_price()` in `generate-thisweek.py`.

**`thisweek.json` not loading** — Confirm it exists at `…/docket-planner/thisweek.json`. GitHub raw files should be CORS-accessible; if not, fall back to the GitHub API contents URL. Until the first Actions run, the planner shows demo data (now works, post-fix).

**Git push failed (Actions)** — The workflow's `GITHUB_TOKEN` is auto-provisioned with `contents: write`; no manual token setup needed.

---

## Reference

### File manifest

| File | Repo path | Edit when… |
|------|-----------|------------|
| `planner.html` | `/planner.html` | redesigning the UI / app behaviour |
| `recipe-bank.json` | `/recipe-bank.json` | adding recipes permanently |
| `generate-thisweek.py` | `/generate-thisweek.py` | catalogue parsing breaks |
| `generate-meals.yml` | `/.github/workflows/generate-meals.yml` | changing the schedule |
| `thisweek.json` | `/thisweek.json` | never — auto-generated |
| `SETUP.md` | `/SETUP.md` | this guide |
| `HANDOFF.md` | `/HANDOFF.md` | system overview |

### Keeping things in sync

The shop-day picker is the planner's **display** day, independent of the **Tuesday 8 PM** generator schedule in `.github/workflows/generate-meals.yml`. Changing the shop day in the app doesn't reschedule generation — edit the `cron` line separately if you want them aligned.

### Rollback

All v2 changes are in `planner.html`. Roll back with `git revert`, or restore `planner.html.bak` from Step 2.

---

## Future ideas (optional)

- Sync approvals/recipes across devices via a backend (Supabase) instead of per-browser localStorage.
- URL-encoded “share plan” link for cross-network household state.
- Meal-history tracking and family ratings.
- Weekly cost trends over time.
- A "manual catalogue entry" fallback for weeks the scraper fails.

---

*The Docket v2 — setup + implementation, single file. Supersedes the separate SETUP.md and IMPLEMENTATION.md.*
