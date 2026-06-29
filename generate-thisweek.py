#!/usr/bin/env python3
"""
The Docket — Weekly Meal Plan Generator
Runs Tuesday night: fetches Coles + Woolies catalogues, matches recipes, 
generates thisweek.json, pushes to GitHub.

SETUP:
1. Create a GitHub personal access token (ghp_...) with repo scope
2. Set environment variables:
   - GITHUB_TOKEN: your PAT
   - GITHUB_REPO: username/docket-planner
   - GITHUB_EMAIL: your email
3. Run with saleIds: python3 thisweek.py --coles 66019 --woolies 66046

OUTPUT: thisweek.json pushed to GitHub with this week's 12-15 meals
"""

import json
import os
import sys
import subprocess
from datetime import datetime
from typing import Dict, List
import requests

# ============ CONFIG ============
COLES_SALEID = os.getenv("COLES_SALEID", "66019")
WOOLIES_SALEID = os.getenv("WOOLIES_SALEID", "66046")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "username/docket-planner")
GITHUB_EMAIL = os.getenv("GITHUB_EMAIL", "your-email@example.com")

COLES_URL = f"https://www.coles.com.au/catalogues/view#view=list&saleId={COLES_SALEID}&areaName=c-wa-met"
WOOLIES_URL = f"https://www.woolworths.com.au/shop/catalogue/view#view=list&saleId={WOOLIES_SALEID}&areaName=WA"

# ============ CATALOGUE PARSING ============
def fetch_catalogue_with_playwright(url: str, store_name: str) -> List[Dict]:
    """
    Fetch catalogue using Playwright (headless browser) to handle JavaScript rendering.
    Clicks "Load more" until all items are loaded, then extracts product + price data.
    """
    print(f"[{store_name}] Fetching catalogue with browser automation...")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(f"  [!] Playwright not installed. Install: pip install playwright")
        print(f"  [!] Then run: playwright install")
        return []
    
    items = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, wait_until="networkidle")
            
            # Click "Load more" buttons until all items loaded
            for attempt in range(50):
                try:
                    load_btn = page.query_selector('button:has-text("Load more")')
                    if not load_btn:
                        break
                    load_btn.click()
                    page.wait_for_timeout(800)  # Wait for items to render
                except:
                    break
            
            # Extract product info from the rendered page
            # This assumes a structure like:
            # <div class="product">
            #   <h3>Product Name</h3>
            #   <span class="price">$X.XX</span>
            #   <span class="was-price">Was $Y.YY</span>
            # </div>
            
            products = page.query_selector_all('[class*="product"], [data-product]')
            for prod in products:
                try:
                    name_el = prod.query_selector('h3, h4, [class*="name"]')
                    price_el = prod.query_selector('[class*="price"], span:has-text("$")')
                    was_el = prod.query_selector('[class*="was"], text=/Was|was/')
                    
                    name = name_el.text_content().strip() if name_el else ""
                    price_text = price_el.text_content().strip() if price_el else ""
                    was_text = was_el.text_content().strip() if was_el else ""
                    
                    # Parse price from text like "$7.50" or "$7.50/kg"
                    price = parse_price(price_text)
                    was_price = parse_price(was_text) if was_text else None
                    
                    if name and price:
                        items.append({
                            "product": name,
                            "price": price,
                            "was_price": was_price,
                            "price_text": price_text,
                            "unit": detect_unit(price_text),
                            "store": store_name.lower()
                        })
                except:
                    continue
            
            browser.close()
    except Exception as e:
        print(f"  [ERROR] Playwright failed: {e}")
        return []
    
    print(f"  Extracted {len(items)} items")
    return items

def fetch_catalogue_fallback(url: str, store_name: str) -> List[Dict]:
    """
    Fallback: fetch catalogue HTML and parse with regex/BeautifulSoup.
    Works for static HTML but won't handle JavaScript-rendered content.
    """
    print(f"[{store_name}] Fetching catalogue (static parsing)...")
    items = []
    try:
        resp = requests.get(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }, timeout=15)
        resp.raise_for_status()
        
        # Try to use BeautifulSoup if available
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(resp.text, "html.parser")
            
            # Look for product containers (varies by site, adjust selectors)
            products = soup.select('[class*="product"], [data-product], article')
            for prod in products:
                # Extract name
                name_tag = prod.select_one('h3, h4, [class*="title"], [class*="name"]')
                name = name_tag.get_text(strip=True) if name_tag else ""
                
                # Extract price
                price_tag = prod.select_one('[class*="price"], [class*="$"], span')
                price_text = price_tag.get_text(strip=True) if price_tag else ""
                
                if name and "$" in price_text:
                    price = parse_price(price_text)
                    if price:
                        items.append({
                            "product": name,
                            "price": price,
                            "was_price": None,
                            "price_text": price_text,
                            "unit": detect_unit(price_text),
                            "store": store_name.lower()
                        })
        except ImportError:
            print(f"  [!] BeautifulSoup not installed. Install: pip install beautifulsoup4")
            return []
    except Exception as e:
        print(f"  [ERROR] Static parsing failed: {e}")
    
    print(f"  Extracted {len(items)} items")
    return items

def parse_price(price_str: str) -> float:
    """Extract price as float from strings like '$7.50', '$7.50/kg', etc."""
    import re
    match = re.search(r'\$(\d+\.?\d*)', price_str)
    return float(match.group(1)) if match else None

def detect_unit(price_str: str):
    """
    Detect the pricing basis from the raw price text so prices can be scaled
    to a recipe's quantity. Returns 'kg', '100g', 'ea', or None (flat/pack).
    e.g. '$18.00 / kg' -> 'kg';  '$18.00kg' -> 'kg';  '$3.50 ea' -> 'ea';
         '$2.00 pkg' -> None;    '$5.00' -> None
    """
    import re
    t = (price_str or "").lower()
    if re.search(r'\b100\s*g\b', t):
        return "100g"
    if re.search(r'(?<![a-z])kg\b', t):   # lookbehind rejects 'pkg'/'package'
        return "kg"
    if re.search(r'\b(ea|each)\b', t):
        return "ea"
    return None

def fetch_catalogue(url: str, store_name: str) -> List[Dict]:
    """
    Fetch catalogue using browser automation (Playwright) if available,
    otherwise fall back to static HTML parsing.
    """
    # Try Playwright first (best for JavaScript-heavy sites)
    items = fetch_catalogue_with_playwright(url, store_name)
    if items:
        return items
    
    # Fall back to static parsing
    print(f"  [!] Playwright unavailable, trying static parsing...")
    items = fetch_catalogue_fallback(url, store_name)
    if items:
        return items
    
    print(f"  [!] Unable to fetch {store_name} catalogue automatically.")
    print(f"  [!] Falling back to recipe bank matching on generic protein types.")
    return []

def extract_specials(items: List[Dict]) -> Dict[str, List[Dict]]:
    """
    Group items by broad protein/ingredient category.
    Returns: {"chicken": [...], "beef": [...], "seafood": [...], etc.}
    """
    specials = {
        "chicken": [],
        "beef": [],
        "pork": [],
        "lamb": [],
        "seafood": [],
        "vegetables": [],
        "pantry": []
    }
    
    for item in items:
        product = item.get("product", "").lower()
        if "chicken" in product or "poultry" in product:
            specials["chicken"].append(item)
        elif "beef" in product:
            specials["beef"].append(item)
        elif "pork" in product:
            specials["pork"].append(item)
        elif "lamb" in product:
            specials["lamb"].append(item)
        elif any(x in product for x in ["salmon", "prawn", "fish", "squid", "barramundi"]):
            specials["seafood"].append(item)
        elif any(x in product for x in ["vegetable", "broccoli", "carrot", "potato"]):
            specials["vegetables"].append(item)
        else:
            specials["pantry"].append(item)
    
    return specials

# ============ RECIPE MATCHING ============
def load_recipe_bank(filepath: str) -> List[Dict]:
    """Load the recipe bank JSON."""
    with open(filepath, 'r') as f:
        data = json.load(f)
    return data.get("recipes", [])

def score_recipe(recipe: Dict, specials: Dict) -> float:
    """
    Score a recipe for this week based on specials overlap.
    Higher = better fit for this week's specials.
    
    Scoring factors:
    - Protein type matches a special
    - Overall savings potential
    - Waste score (lower waste = higher score)
    - FODMAP fit (already guaranteed by design)
    """
    score = 0.0
    recipe_name = recipe.get("name", "").lower()
    
    # Check if recipe's main protein is on special
    if "chicken" in recipe_name and specials["chicken"]:
        score += 5.0
    if "beef" in recipe_name and specials["beef"]:
        score += 5.0
    if "pork" in recipe_name and specials["pork"]:
        score += 5.0
    if "lamb" in recipe_name and specials["lamb"]:
        score += 5.0
    if any(x in recipe_name for x in ["salmon", "prawn", "fish", "squid"]) and specials["seafood"]:
        score += 5.0
    
    # Waste score: fewer items = higher score (less waste)
    items_count = len(recipe.get("items", []))
    score += max(0, 5.0 - (items_count / 3))  # Penalize recipes with many ingredients
    
    # Seasonal fit (June): root veg, citrus, hearty braises score higher
    season_keywords = ["root", "braise", "orange", "lemon", "ginger", "roast"]
    if any(kw in recipe_name.lower() for kw in season_keywords):
        score += 2.0
    
    return score

def select_weekly_meals(recipe_bank: List[Dict], specials: Dict, count: int = 12) -> List[Dict]:
    """
    Select the best `count` recipes for this week based on specials.
    Returns recipes scored and sorted highest-first.
    """
    scored = []
    for recipe in recipe_bank:
        score = score_recipe(recipe, specials)
        scored.append((score, recipe))
    
    # Sort by score, highest first; remove duplicates by id
    scored.sort(key=lambda x: x[0], reverse=True)
    seen_ids = set()
    selected = []
    for score, recipe in scored:
        if recipe.get("id") not in seen_ids:
            selected.append(recipe)
            seen_ids.add(recipe.get("id"))
            if len(selected) >= count:
                break
    
    return selected

# ============ LIVE PRICE MERGE ============
import re as _re

# words that aren't useful for matching an ingredient to a catalogue product
_STOP = set("""the a an of and or with in on for to fresh light free onion drained
weight half can pack bag bags bunch bunches head heads jar bottle tin tinned canned
roast diced minced fillet fillets piece pieces approx each whole""".split())

_QTY_TOKEN = _re.compile(r'(\d+\.?\d*\s*(kg|g|ml|l)\b|[\u00d7x]\s*\d+|\(.*?\))', _re.I)

def _content_tokens(name: str):
    """Significant words from an item/product name (drops sizes, units, fillers)."""
    s = _QTY_TOKEN.sub(' ', (name or '').lower())
    s = _re.sub(r"[^a-z ]", ' ', s)
    return {w for w in s.split() if len(w) > 2 and w not in _STOP}

def parse_item_quantity(name: str):
    """
    Pull the quantity a recipe item calls for.
    Returns {'grams': float|None, 'count': int|None, 'ml': float|None}.
    'Pork belly 500g' -> grams 500;  'Chicken drumsticks 2kg pack' -> grams 2000;
    'Carrots x4' -> count 4;  'Coconut milk 200mL' -> ml 200.
    """
    s = (name or '').lower()
    kg = _re.search(r'(\d+\.?\d*)\s*kg', s)
    g  = _re.search(r'(\d+\.?\d*)\s*g(?![a-z])', s)
    ml = _re.search(r'(\d+\.?\d*)\s*ml', s)
    cnt = _re.search(r'[\u00d7x]\s*(\d+)', s)
    grams = float(kg.group(1)) * 1000 if kg else (float(g.group(1)) if g else None)
    return {
        "grams": grams,
        "count": int(cnt.group(1)) if cnt else None,
        "ml": float(ml.group(1)) if ml else None,
    }

def _store_code(scraped_store: str) -> str:
    s = (scraped_store or '').lower()
    if s.startswith('col'): return 'c'
    if s.startswith('wool'): return 'w'
    return 'e'

def compute_scaled_price(qty: Dict, scraped: Dict):
    """
    Scale a catalogue price to the recipe's quantity.
    Returns (price, was, basis) or None if it can't be done reliably.
    """
    unit = scraped.get("unit")
    price = scraped.get("price")
    was = scraped.get("was_price")
    if price is None:
        return None
    grams = qty["grams"]

    if unit in ("kg", "100g") and grams:
        factor = grams / (1000.0 if unit == "kg" else 100.0)
        return (round(price * factor, 2),
                round(was * factor, 2) if was else None,
                f"{unit} x {grams:g}g")

    # flat price (pack) or per-each with no weight info: use as-is, best effort
    if unit in (None, "ea"):
        return (round(price, 2), round(was, 2) if was else None, unit or "pack")

    # per-kg price but the recipe is a count/volume we can't convert -> don't guess
    return None

def _set_status(item: list, status: str):
    """Append a 6th element ('live'|'est') without disturbing the 5-field shape the planner reads."""
    if len(item) >= 6:
        item[5] = status
    else:
        item.append(status)

def merge_live_prices(recipes: List[Dict], all_items: List[Dict]):
    """
    Overwrite each recipe item's price with this week's catalogue price where a
    confident match exists, scaling per-kg prices to the item's quantity. Items
    with no match keep their bank price and are flagged 'est'. Returns
    (recipes, stats).
    """
    pool = []
    for it in all_items:
        pool.append({
            "product": it.get("product", ""),
            "price": it.get("price"),
            "was_price": it.get("was_price"),
            "unit": it.get("unit"),
            "code": _store_code(it.get("store", "")),
            "toks": _content_tokens(it.get("product", "")),
        })

    stats = {"matched": 0, "total": 0, "scraped": len(all_items)}

    for r in recipes:
        specials = []
        for item in r.get("items", []):
            stats["total"] += 1
            name = item[0]
            store = item[1] if len(item) > 1 else 'e'
            rtok = _content_tokens(name)
            if not rtok:
                _set_status(item, "est")
                continue
            need = 2 if len(rtok) >= 2 else 1

            best, best_shared = None, 0
            for sc in pool:
                if store != 'e' and sc["code"] != store:
                    continue
                shared = len(rtok & sc["toks"])
                if shared >= need and shared > best_shared:
                    best, best_shared = sc, shared

            if not best:
                _set_status(item, "est")
                continue

            res = compute_scaled_price(parse_item_quantity(name), best)
            if not res:
                _set_status(item, "est")
                continue

            price, was, _basis = res
            # pad item to at least 5 fields, then update price/was
            while len(item) < 5:
                item.append(None)
            item[2] = price
            item[3] = was
            _set_status(item, "live")
            stats["matched"] += 1

            if was and price and was > price:
                specials.append({"store": store, "txt": "on special"})

        if specials:
            # de-dupe, cap to keep the planner's tag row tidy
            seen = set()
            uniq = []
            for sp in specials:
                key = (sp["store"], sp["txt"])
                if key not in seen:
                    seen.add(key)
                    uniq.append(sp)
            r["specials"] = uniq[:3]

    return recipes, stats

# ============ JSON GENERATION ============
def generate_thisweek_json(selected_recipes: List[Dict], coles_saleid: str, woolies_saleid: str, approved: bool = False, price_stats: Dict = None) -> Dict:
    """
    Generate the thisweek.json structure that the planner will load.
    
    If approved=False, includes a "review_pending" flag so the UI shows 
    "New meals generated — household review & approve below" banner.
    """
    now = datetime.now()
    week_start = "Wed 10"  # This should be computed based on actual date
    week_end = "Tue 16"
    
    # Shuffle recipes to a default order (optional: randomize or keep scored order)
    # For now, keep top 12 in scored order
    meals = selected_recipes[:12]

    ps = price_stats or {"matched": 0, "total": 0, "scraped": 0}
    if ps["scraped"] == 0:
        note = ("Catalogue scrape returned no items this week — all prices are typical "
                "bank estimates. Check the run log / selectors.")
    else:
        note = (f"Prices: {ps['matched']} of {ps['total']} items updated from this week's "
                f"catalogue ({ps['scraped']} specials scanned); the rest use typical bank "
                f"prices. Items flagged 'est' are not live.")

    return {
        "metadata": {
            "generated": now.isoformat(),
            "week_start": week_start,
            "week_end": week_end,
            "coles_saleid": coles_saleid,
            "coles_url": f"https://www.coles.com.au/catalogues/view#view=list&saleId={coles_saleid}&areaName=c-wa-met",
            "woolies_saleid": woolies_saleid,
            "woolies_url": f"https://www.woolworths.com.au/shop/catalogue/view#view=list&saleId={woolies_saleid}&areaName=WA",
            "note": note,
            "price_matched": ps["matched"],
            "price_total": ps["total"],
            "scraped_items": ps["scraped"],
            "review_pending": not approved,
            "review_message": "⚠️ New meals generated! Household can review, skip, or swap meals below. Once at least 4 meals are approved, you're ready to shop."
        },
        "recipes": meals
    }

# ============ GITHUB COMMIT & PUSH ============
def push_to_github(thisweek_json: Dict, github_token: str, github_repo: str, github_email: str) -> bool:
    """
    Commit thisweek.json to GitHub and push.
    Requires: git installed, GitHub token with repo scope, repo cloned locally.
    """
    try:
        # Assume repo is cloned at ~/docket-planner or GITHUB_REPO env var points to path
        repo_path = os.getenv("REPO_PATH", os.path.expanduser("~/docket-planner"))
        
        if not os.path.exists(repo_path):
            print(f"[ERROR] Repo not found at {repo_path}")
            print(f"  Clone it first: git clone https://{github_token}@github.com/{github_repo}.git {repo_path}")
            return False
        
        os.chdir(repo_path)
        
        # Write thisweek.json
        with open("thisweek.json", "w") as f:
            json.dump(thisweek_json, f, indent=2)
        
        # Git config
        subprocess.run(["git", "config", "user.email", github_email], check=True)
        subprocess.run(["git", "config", "user.name", "Docket Bot"], check=True)
        
        # Stage, commit, push
        subprocess.run(["git", "add", "thisweek.json"], check=True)
        subprocess.run(["git", "commit", "-m", f"Weekly update: {thisweek_json['metadata']['week_start']} – {thisweek_json['metadata']['week_end']}"], check=True)
        subprocess.run(["git", "push", "origin", "main"], check=True)
        
        print("[✓] Pushed to GitHub")
        return True
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Git operation failed: {e}")
        return False
    except Exception as e:
        print(f"[ERROR] Failed to push: {e}")
        return False

# ============ MAIN ============
def main():
    print("=" * 60)
    print("The Docket — Weekly Meal Generator")
    print("=" * 60)
    
    # Parse arguments (optional: CLI overrides env vars)
    if len(sys.argv) > 1:
        for i, arg in enumerate(sys.argv[1:]):
            if arg == "--coles" and i + 1 < len(sys.argv):
                globals()["COLES_SALEID"] = sys.argv[i + 2]
            if arg == "--woolies" and i + 1 < len(sys.argv):
                globals()["WOOLIES_SALEID"] = sys.argv[i + 2]
    
    print(f"\n[1/5] Loading recipe bank...")
    recipe_bank = load_recipe_bank("recipe-bank.json")
    print(f"  Loaded {len(recipe_bank)} recipes")
    
    print(f"\n[2/5] Fetching Coles catalogue (saleId {COLES_SALEID})...")
    coles_items = fetch_catalogue(COLES_URL, "Coles")
    
    print(f"\n[3/5] Fetching Woolworths catalogue (saleId {WOOLIES_SALEID})...")
    woolies_items = fetch_catalogue(WOOLIES_URL, "Woolworths")
    
    # Combine and extract specials by category
    all_items = coles_items + woolies_items
    specials = extract_specials(all_items)
    
    print(f"\n[4/5] Matching recipes to specials...")
    print(f"  Specials found: chicken={len(specials['chicken'])}, beef={len(specials['beef'])}, seafood={len(specials['seafood'])}, ...")
    
    selected = select_weekly_meals(recipe_bank, specials, count=12)
    print(f"  Selected {len(selected)} recipes for the week")
    for i, recipe in enumerate(selected[:5], 1):
        print(f"    {i}. {recipe.get('name')}")
    if len(selected) > 5:
        print(f"    ... and {len(selected) - 5} more")

    print(f"\n[4b/5] Merging live catalogue prices...")
    selected, price_stats = merge_live_prices(selected, all_items)
    print(f"  Updated {price_stats['matched']} of {price_stats['total']} items "
          f"from {price_stats['scraped']} scraped specials")

    thisweek_json = generate_thisweek_json(selected, COLES_SALEID, WOOLIES_SALEID, price_stats=price_stats)

    print(f"\n[5/5] Writing thisweek.json...")
    repo_path = os.getenv("REPO_PATH", ".")
    out_path = os.path.join(repo_path, "thisweek.json")
    with open(out_path, "w") as f:
        json.dump(thisweek_json, f, indent=2)
    print(f"  Wrote {out_path}")

    # In CI the workflow's "Commit and push" step handles git. The script only
    # pushes when explicitly asked (e.g. running locally with DOCKET_PUSH=1), so
    # we never have two actors committing/pushing the same file and colliding
    # with a non-fast-forward rejection.
    if os.getenv("DOCKET_PUSH") == "1":
        print("  DOCKET_PUSH=1 set — pushing from the script...")
        push_to_github(thisweek_json, GITHUB_TOKEN, GITHUB_REPO, GITHUB_EMAIL)
    else:
        print("  Skipping git push (handled by CI; set DOCKET_PUSH=1 to push from the script).")

    print(f"\n[\u2713] Done! {price_stats['matched']}/{price_stats['total']} items priced "
          f"from {price_stats['scraped']} scraped specials.")

if __name__ == "__main__":
    main()
