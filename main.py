"""
main.py — FastAPI Application for Instagram Profile Analyser.

Handles:
  - Startup database initialisation (MongoDB Atlas / local)
  - Bulk paste username routing & cleaner parsing
  - Background task worker for sequential profile crawling (with rate-limiting safeguards)
  - Server-Sent Events (SSE) progress streaming
  - Profiles cache queries (search, sorting)
  - Profile individual refresh and delete controllers
  - Dynamic CSV & JSON export formatting
"""

import re
import json
import secrets
import logging
import asyncio
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, Request, Form, BackgroundTasks, Cookie, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv

load_dotenv()

# Logger setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger(__name__)

# FastAPI Core
app = FastAPI(title="Instagram Profile Analyser")

BASE_DIR = Path(__file__).parent
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

# Startup database initialization
@app.on_event("startup")
async def startup_db():
    from utils.db import init_db
    success = await init_db()
    if not success:
        logger.warning(
            "⚠️ Supabase to MongoDB initialisation warning. Database is unreachable. "
            "Falling back to memory caches if needed, but Atlas connectivity is recommended."
        )

# Custom Jinja2 Filters for pretty displays
def fmt_large_number(value):
    try:
        v = int(value)
        if v >= 1_000_000_000: return f"{v/1_000_000_000:.1f}B".replace(".0", "")
        if v >= 1_000_000:     return f"{v/1_000_000:.1f}M".replace(".0", "")
        if v >= 1_000:         return f"{v/1_000:.1f}K".replace(".0", "")
        return str(v)
    except (ValueError, TypeError):
        return "0"

def fmt_date(dt):
    if not dt:
        return "Never"
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        except ValueError:
            return dt
    return dt.strftime("%b %d, %Y %H:%M")

templates.env.filters["fmt_number"] = fmt_large_number
templates.env.filters["fmt_date"] = fmt_date

# ---------------------------------------------------------------------------
# Background Crawler Job Worker
# ---------------------------------------------------------------------------

async def execute_bulk_scrape_job(job_id: str, usernames: List[str], force_demo: bool):
    """
    Background worker that runs sequentially.
    Uses instaloader (Tier 1), falling back to DuckDuckGo (Tier 2), and Simulation (Tier 3).
    Saves profiles in real-time, logs actions, and broadcasts progress updates.
    """
    from utils.db import update_job_progress, save_profile, complete_job
    from utils.scraper import fetch_instagram_profile
    
    logger.info(f"Starting background job {job_id} for {len(usernames)} profiles. Demo Mode: {force_demo}")
    done_count = 0
    
    # Simple delay selector
    for index, raw_uname in enumerate(usernames):
        uname = raw_uname.strip().lower()
        if not uname:
            continue
            
        log_msg = f"Fetching metrics for @{uname}..."
        await update_job_progress(job_id, uname, done_count, log_msg=log_msg)
        
        try:
            # Multi-tiered fetch
            profile_data = await fetch_instagram_profile(uname, force_demo=force_demo)
            
            # Save into MongoDB Atlas
            await save_profile(profile_data)
            
            done_count += 1
            success_log = f"Analysed @{uname} — Followers: {fmt_large_number(profile_data['followers_count'])}"
            await update_job_progress(job_id, uname, done_count, log_msg=success_log)
            
        except Exception as e:
            done_count += 1
            err_log = f"Failed scraping @{uname}: {str(e)}"
            await update_job_progress(job_id, uname, done_count, failed_username=uname, log_msg=err_log)
            
        # Respectful rate-limiting pause (between 2 to 4 seconds) if doing real live requests
        if not force_demo and index < len(usernames) - 1:
            sleep_time = random.uniform(2.0, 4.0)
            await asyncio.sleep(sleep_time)
            
    await complete_job(job_id, "completed")

# ---------------------------------------------------------------------------
# Web App & Dashboard Routes
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def index(request: Request, demo_mode: str = Cookie(default="false")):
    """Renders the comprehensive, professional analytics dashboard."""
    from utils.db import get_all_profiles, get_recent_jobs
    
    profiles = await get_all_profiles()
    recent_jobs = await get_recent_jobs(limit=5)
    
    # Calculate statistics
    total_profiles = len(profiles)
    total_followers = sum(int(p.get("followers_count") or 0) for p in profiles)
    avg_posts = sum(int(p.get("posts_count") or 0) for p in profiles) / total_profiles if total_profiles > 0 else 0
    
    # Success rate (success status count / total)
    successful_scrapes = sum(1 for p in profiles if p.get("status") in ("success", "simulated"))
    success_rate = (successful_scrapes / total_profiles * 100) if total_profiles > 0 else 0
    
    ctx = {
        "request": request,
        "profiles": profiles,
        "recent_jobs": recent_jobs,
        "total_profiles": total_profiles,
        "total_followers": total_followers,
        "avg_posts": int(avg_posts),
        "success_rate": round(success_rate, 1),
        "demo_mode": demo_mode == "true"
    }
    
    return templates.TemplateResponse("index.html", ctx)

@app.post("/analyse")
async def trigger_bulk_analyse(
    background_tasks: BackgroundTasks,
    usernames_input: str = Form(...),
    demo_mode: str = Cookie(default="false")
):
    """
    Trigger bulk profile scraper job in the background.
    Parses pasted lists (comma, space, or newline separated).
    """
    from utils.db import create_job
    
    # Clean and parse usernames: split by newline or comma or space
    lines = re.split(r"[\n,\s]+", usernames_input)
    usernames = []
    for line in lines:
        cleaned = line.strip().replace("@", "")
        if cleaned and cleaned not in usernames:
            usernames.append(cleaned)
            
    if not usernames:
        raise HTTPException(status_code=400, detail="No valid Instagram usernames provided.")
        
    job_id = secrets.token_hex(8)
    
    # Create the job in MongoDB
    await create_job(job_id, len(usernames))
    
    # Push job execution to background task queue
    force_demo = (demo_mode == "true")
    background_tasks.add_task(execute_bulk_scrape_job, job_id, usernames, force_demo)
    
    return {"status": "started", "job_id": job_id, "total": len(usernames)}

@app.get("/analyse/progress/{job_id}")
async def get_analyse_progress(job_id: str):
    """Server-Sent Events (SSE) connection streaming real-time scraping progress."""
    from utils.db import get_job_status
    
    async def progress_emitter():
        while True:
            job = await get_job_status(job_id)
            if not job:
                yield f"data: {json.dumps({'status': 'not_found'})}\n\n"
                break
                
            yield f"data: {json.dumps(job, default=str)}\n\n"
            
            # Stop streaming if job finishes
            if job.get("status") in ("completed", "failed"):
                break
                
            await asyncio.sleep(0.5)
            
    return StreamingResponse(
        progress_emitter(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive"
        }
    )

@app.post("/profile/{username}/refresh")
async def refresh_single_profile(username: str, demo_mode: str = Cookie(default="false")):
    """Force re-fetch metric updates for a single profile."""
    from utils.db import save_profile
    from utils.scraper import fetch_instagram_profile
    
    uname = username.strip().lower()
    force_demo = (demo_mode == "true")
    
    try:
        profile_data = await fetch_instagram_profile(uname, force_demo=force_demo)
        await save_profile(profile_data)
        return {"status": "success", "profile": profile_data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to refresh @{uname}: {e}")

@app.delete("/profile/{username}")
async def remove_profile(username: str):
    """Delete a profile record from the database."""
    from utils.db import delete_profile
    success = await delete_profile(username)
    if not success:
        raise HTTPException(status_code=404, detail="Profile not found in database.")
    return {"status": "success", "message": f"@{username} removed successfully."}

# ---------------------------------------------------------------------------
# Data Exports (CSV & JSON)
# ---------------------------------------------------------------------------

@app.get("/export/csv")
async def export_csv():
    """Generates and downloads a clean CSV file of all MongoDB profile data."""
    from utils.db import get_all_profiles
    import pandas as pd
    import io
    
    profiles = await get_all_profiles()
    if not profiles:
        # Return empty CSV headers
        df = pd.DataFrame(columns=["username", "full_name", "followers_count", "following_count", "posts_count", "status", "last_updated"])
    else:
        df = pd.DataFrame(profiles)
        # Drop mongo object ids
        if "_id" in df.columns:
            df = df.drop(columns=["_id"])
            
    stream = io.StringIO()
    df.to_csv(stream, index=False)
    
    response = StreamingResponse(
        iter([stream.getvalue()]),
        media_type="text/csv"
    )
    response.headers["Content-Disposition"] = "attachment; filename=instagram_profiles.csv"
    return response

@app.get("/export/json")
async def export_json():
    """Downloads a raw JSON export of all scraped database records."""
    from utils.db import get_all_profiles
    
    profiles = await get_all_profiles()
    # Serialize with ISO datetime formatting
    clean_profiles = []
    for p in profiles:
        # Strip mongo ID
        p_copy = p.copy()
        if "_id" in p_copy:
            del p_copy["_id"]
        # Format datetime if it is a datetime object
        if isinstance(p_copy.get("last_updated"), datetime):
            p_copy["last_updated"] = p_copy["last_updated"].isoformat()
        clean_profiles.append(p_copy)
        
    json_str = json.dumps(clean_profiles, indent=2, default=str)
    
    response = StreamingResponse(
        iter([json_str]),
        media_type="application/json"
    )
    response.headers["Content-Disposition"] = "attachment; filename=instagram_profiles.json"
    return response

