"""
utils/scraper.py — Multi-tiered Scraping Core for Instagram Profile Analyser.

Contains three distinct, redundant strategies for collecting profile metrics:
  1. Instaloader Engine (Direct live fetch via official client wrapper in thread pool)
  2. DuckDuckGo SERP Snippet Parser (Queries search engine HTML to bypass Instagram rate-limits)
  3. Smart Simulation Engine (Dynamic realistic generators, ensuring 100% UI stability)
"""

import re
import random
import asyncio
import logging
from typing import Dict, Any, Optional
import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Standard mobile browser headers to mimic real search requests
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Referer": "https://duckduckgo.com/",
}

# ---------------------------------------------------------------------------
# Number Formatting Utility
# ---------------------------------------------------------------------------

def parse_formatted_number(num_str: str) -> int:
    """
    Parses a string formatted number (like '50.2M', '15.4K', '1,234') into a plain integer.
    Handles standard U.S. and European number formatting.
    """
    if not num_str:
        return 0
    
    # Strip whitespace and commas
    cleaned = num_str.strip().upper().replace(",", "")
    
    multiplier = 1
    if cleaned.endswith("M"):
        multiplier = 1_000_000
        cleaned = cleaned[:-1]
    elif cleaned.endswith("K"):
        multiplier = 1_000
        cleaned = cleaned[:-1]
    elif cleaned.endswith("B"):
        multiplier = 1_000_000_000
        cleaned = cleaned[:-1]
        
    try:
        # Cast to float, multiply, and round to integer
        return int(float(cleaned) * multiplier)
    except ValueError:
        logger.warning(f"Could not convert scraped string to int: {num_str}")
        return 0

# ---------------------------------------------------------------------------
# Tier 3: Smart Simulation Engine
# ---------------------------------------------------------------------------

def generate_simulated_profile(username: str) -> Dict[str, Any]:
    """Generates highly realistic profile statistics based on the username string."""
    uname = username.strip().lower()
    
    # Generate full name: replace underscores/dots with spaces and capitalize
    name_parts = re.split(r"[._-]", uname)
    full_name = " ".join([p.capitalize() for p in name_parts if p])
    if not full_name:
        full_name = uname.capitalize()
        
    # Seed random with username hash to ensure identical usernames produce consistent counts
    random.seed(hash(uname))
    
    # Generate realistic tiering
    tier_rand = random.random()
    if tier_rand > 0.95:  # Mega (Influencer/Celebrity)
        followers = random.randint(5_000_000, 150_000_000)
        posts = random.randint(500, 4_000)
        following = random.randint(100, 800)
    elif tier_rand > 0.75:  # Macro / Mid-tier
        followers = random.randint(100_000, 4_999_999)
        posts = random.randint(300, 3_000)
        following = random.randint(150, 1_500)
    elif tier_rand > 0.30:  # Micro / Nano
        followers = random.randint(5_000, 99_999)
        posts = random.randint(50, 1_200)
        following = random.randint(200, 2_000)
    else:  # Small / Regular account
        followers = random.randint(200, 4_999)
        posts = random.randint(10, 300)
        following = random.randint(150, 1_000)
        
    # Reset random seed
    random.seed(None)
    
    return {
        "username": uname,
        "full_name": full_name,
        "followers_count": followers,
        "following_count": following,
        "posts_count": posts,
        "status": "simulated"
    }

# ---------------------------------------------------------------------------
# Tier 2: DuckDuckGo Snippet Engine (Fallback Scraper)
# ---------------------------------------------------------------------------

async def scrape_duckduckgo_profile(username: str) -> Optional[Dict[str, Any]]:
    """
    Queries DuckDuckGo's static HTML search page for site:instagram.com/{username}
    and extracts followers, following, and post counts from search snippets.
    """
    uname = username.strip().lower()
    search_url = "https://html.duckduckgo.com/html/"
    params = {"q": f"site:instagram.com/{uname}"}
    
    try:
        logger.info(f"Attempting Tier 2 DDG Scrape for @{uname}...")
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            response = await client.post(search_url, data=params, headers=BROWSER_HEADERS)
            
            if response.status_code != 200:
                logger.warning(f"DDG request returned non-200 code: {response.status_code}")
                return None
                
            soup = BeautifulSoup(response.text, "html.parser")
            snippets = soup.select(".result__snippet")
            
            if not snippets:
                logger.warning("No search results found on DDG for this profile.")
                return None
                
            # Loop through snippets and parse metadata
            for snippet_el in snippets:
                text = snippet_el.get_text()
                
                # Check for standard Instagram search snippet formats:
                # E.g., "1.2M Followers, 300 Following, 450 Posts..." or "1,234 followers, 567 following, 89 posts"
                followers_match = re.search(r"([\d.,]+[KMB]?)\s*Followers", text, re.IGNORECASE)
                following_match = re.search(r"([\d.,]+[KMB]?)\s*Following", text, re.IGNORECASE)
                posts_match = re.search(r"([\d.,]+[KMB]?)\s*(?:Posts|Media)", text, re.IGNORECASE)
                
                # If we get at least the follower match, we can parse it
                if followers_match:
                    followers = parse_formatted_number(followers_match.group(1))
                    following = parse_formatted_number(following_match.group(1)) if following_match else 0
                    posts = parse_formatted_number(posts_match.group(1)) if posts_match else 0
                    
                    # Try to extract full name from title/snippet
                    full_name = uname
                    title_el = snippet_el.find_previous(class_="result__a")
                    if title_el:
                        title_text = title_el.get_text()
                        # E.g., "Cristiano Ronaldo (@cristiano) • Instagram..."
                        name_match = re.match(r"^([^(]+)\s+\(@", title_text)
                        if name_match:
                            full_name = name_match.group(1).strip()
                            
                    logger.info(f"✅ Successful DDG parse for @{uname}! Followers: {followers}")
                    return {
                        "username": uname,
                        "full_name": full_name,
                        "followers_count": followers,
                        "following_count": following,
                        "posts_count": posts,
                        "status": "success"
                    }
                    
        return None
    except Exception as e:
        logger.error(f"Error scraping DDG for @{uname}: {e}")
        return None

# ---------------------------------------------------------------------------
# Tier 1: Instaloader Live Engine
# ---------------------------------------------------------------------------

def _instaloader_worker(username: str) -> Optional[Dict[str, Any]]:
    """Synchronous worker that runs inside a thread pool to avoid blocking ASGI."""
    uname = username.strip().lower()
    try:
        import instaloader
        L = instaloader.Instaloader(
            download_pictures=False,
            download_videos=False,
            download_video_thumbnails=False,
            download_geotags=False,
            download_comments=False,
            save_metadata=False,
            compress_json=False,
            quiet=True,
        )
        
        # Pull profile structure anonymously
        profile = instaloader.Profile.from_username(L.context, uname)
        
        return {
            "username": uname,
            "full_name": profile.full_name or uname,
            "followers_count": profile.followers,
            "following_count": profile.followees,
            "posts_count": profile.mediacount,
            "status": "success"
        }
    except Exception as e:
        logger.error(f"Instaloader failed for @{uname}: {type(e).__name__} - {e}")
        return None

async def scrape_instaloader_profile(username: str) -> Optional[Dict[str, Any]]:
    """Runs the Instaloader worker asynchronously inside an event executor."""
    loop = asyncio.get_event_loop()
    try:
        logger.info(f"Attempting Tier 1 Instaloader Scrape for @{username}...")
        return await loop.run_in_executor(None, _instaloader_worker, username)
    except Exception as e:
        logger.error(f"Instaloader wrapper execution failed: {e}")
        return None

# ---------------------------------------------------------------------------
# Unified Scraping Pipeline Controller
# ---------------------------------------------------------------------------

async def fetch_instagram_profile(username: str, force_demo: bool = False) -> Dict[str, Any]:
    """
    Executes the multi-tiered scraping pipeline for a username:
      1. If force_demo is True, immediately returns simulated details.
      2. Tries Tier 1: Instaloader.
      3. If blocked/fails, tries Tier 2: DuckDuckGo.
      4. If both fail, falls back gracefully to Tier 3: Simulated profile.
    """
    uname = username.strip().lower()
    
    if force_demo:
        logger.info(f"Demo Mode enabled. Generating simulated stats for @{uname}...")
        return generate_simulated_profile(uname)
        
    # Step 1: Instaloader (Tier 1)
    result = await scrape_instaloader_profile(uname)
    if result:
        return result
        
    # Step 2: DuckDuckGo Fallback (Tier 2)
    result = await scrape_duckduckgo_profile(uname)
    if result:
        return result
        
    # Step 3: Simulation Fallback (Tier 3)
    logger.warning(f"All live scrapers failed for @{uname}. Falling back to Smart Simulation Mode.")
    simulated = generate_simulated_profile(uname)
    # Mark status as simulated-fallback so the user knows it's generated
    simulated["status"] = "simulated"
    return simulated
