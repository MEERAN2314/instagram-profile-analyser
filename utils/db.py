"""
utils/db.py — Asynchronous MongoDB Database Integration for Instagram Profile Analyser.

Handles:
  - Motor client connection to MongoDB Atlas / Local MongoDB
  - Indexes creation for fast lookups
  - Storing and retrieving scraped profile metrics (username, followers, following, posts)
  - Tracking background bulk scraping job progress (SSE pipeline)
"""

import os
import logging
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import UpdateOne
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# Load Connection String
MONGODB_URI = os.environ.get("MONGODB_URI", "mongodb://localhost:27017").strip()

# Database and collection names
DB_NAME = "instagram_analyser"
PROFILES_COLLECTION = "profiles"
JOBS_COLLECTION = "jobs"

# Global Motor Client
client: Optional[AsyncIOMotorClient] = None
db = None

async def init_db() -> bool:
    """Initialize the MongoDB client and ensure indexes are created."""
    global client, db
    try:
        logger.info("Initializing MongoDB Client...")
        client = AsyncIOMotorClient(MONGODB_URI)
        db = client[DB_NAME]
        
        # Ping the database to verify credentials/connectivity
        await db.command("ping")
        logger.info("✅ Successfully connected to MongoDB Atlas/Instance!")
        
        # Ensure unique index on username in the profiles collection
        await db[PROFILES_COLLECTION].create_index("username", unique=True)
        # Ensure index on jobs for fast lookups
        await db[JOBS_COLLECTION].create_index("job_id", unique=True)
        await db[JOBS_COLLECTION].create_index("started_at")
        
        return True
    except Exception as e:
        logger.error(f"❌ Failed to connect to MongoDB: {e}")
        return False

def get_db():
    """Get database instance. If not initialized, tries to do so."""
    global db
    if db is None:
        client = AsyncIOMotorClient(MONGODB_URI)
        db = client[DB_NAME]
    return db

# ---------------------------------------------------------------------------
# Profiles Operations
# ---------------------------------------------------------------------------

def format_followers(count: int) -> str:
    """Helper to format large numbers beautifully (e.g. 1.2M, 45K)."""
    if count >= 1_000_000:
        return f"{count / 1_000_000:.1f}M".replace(".0", "")
    elif count >= 1_000:
        return f"{count / 1_000:.1f}K".replace(".0", "")
    return str(count)

async def save_profile(profile_data: Dict[str, Any]) -> bool:
    """
    Upsert profile information. Strips bio and avatar for privacy and simplicity.
    Expects profile_data containing: username, full_name, followers_count, following_count, posts_count, status
    """
    try:
        database = get_db()
        username = profile_data["username"].lower().strip()
        followers = int(profile_data.get("followers_count") or 0)
        
        upsert_payload = {
            "username": username,
            "full_name": profile_data.get("full_name") or username,
            "followers_count": followers,
            "followers_formatted": format_followers(followers),
            "following_count": int(profile_data.get("following_count") or 0),
            "posts_count": int(profile_data.get("posts_count") or 0),
            "status": profile_data.get("status") or "success",
            "last_updated": datetime.now(timezone.utc)
        }
        
        await database[PROFILES_COLLECTION].update_one(
            {"username": username},
            {"$set": upsert_payload},
            upsert=True
        )
        return True
    except Exception as e:
        logger.error(f"Failed to save profile {profile_data.get('username')}: {e}")
        return False

async def get_profile(username: str) -> Optional[Dict[str, Any]]:
    """Fetch a single profile from the cache."""
    try:
        database = get_db()
        return await database[PROFILES_COLLECTION].find_one({"username": username.lower().strip()})
    except Exception as e:
        logger.error(f"Failed to get profile {username}: {e}")
        return None

async def get_all_profiles() -> List[Dict[str, Any]]:
    """Retrieve all profiles, sorted by followers count descending."""
    try:
        database = get_db()
        cursor = database[PROFILES_COLLECTION].find({}).sort("followers_count", -1)
        profiles = await cursor.to_list(length=1000)
        # Convert ObjectId to string for JSON serialization compatibility
        for p in profiles:
            p["_id"] = str(p["_id"])
        return profiles
    except Exception as e:
        logger.error(f"Failed to retrieve all profiles: {e}")
        return []

async def delete_profile(username: str) -> bool:
    """Delete a profile from the cached profiles collection."""
    try:
        database = get_db()
        result = await database[PROFILES_COLLECTION].delete_one({"username": username.lower().strip()})
        return result.deleted_count > 0
    except Exception as e:
        logger.error(f"Failed to delete profile {username}: {e}")
        return False

# ---------------------------------------------------------------------------
# Background Scraping Jobs Operations (for real-time progress)
# ---------------------------------------------------------------------------

async def create_job(job_id: str, total_count: int) -> bool:
    """Create a new job tracker row in MongoDB."""
    try:
        database = get_db()
        job_payload = {
            "job_id": job_id,
            "total": total_count,
            "done": 0,
            "current": "",
            "status": "processing", # processing, completed, failed
            "failed_usernames": [],
            "logs": ["Job created. Preparing queue..."],
            "started_at": datetime.now(timezone.utc),
            "completed_at": None
        }
        await database[JOBS_COLLECTION].insert_one(job_payload)
        return True
    except Exception as e:
        logger.error(f"Failed to create job {job_id}: {e}")
        return False

async def update_job_progress(
    job_id: str, 
    current_username: str, 
    done_count: int, 
    failed_username: Optional[str] = None, 
    log_msg: Optional[str] = None
) -> bool:
    """Dynamically update job progress, logs, and current item."""
    try:
        database = get_db()
        update_op = {
            "$set": {
                "current": current_username,
                "done": done_count
            }
        }
        
        push_op = {}
        if failed_username:
            push_op["failed_usernames"] = failed_username.lower().strip()
        if log_msg:
            push_op["logs"] = log_msg
            
        if push_op:
            update_op["$push"] = push_op
            
        await database[JOBS_COLLECTION].update_one({"job_id": job_id}, update_op)
        return True
    except Exception as e:
        logger.error(f"Failed to update job {job_id} progress: {e}")
        return False

async def complete_job(job_id: str, status: str = "completed") -> bool:
    """Mark a background job as finished."""
    try:
        database = get_db()
        await database[JOBS_COLLECTION].update_one(
            {"job_id": job_id},
            {
                "$set": {
                    "status": status,
                    "completed_at": datetime.now(timezone.utc),
                    "current": ""
                },
                "$push": {
                    "logs": f"Job finished with status: {status.upper()}"
                }
            }
        )
        return True
    except Exception as e:
        logger.error(f"Failed to complete job {job_id}: {e}")
        return False

async def get_job_status(job_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve the current state of a scraping job."""
    try:
        database = get_db()
        job = await database[JOBS_COLLECTION].find_one({"job_id": job_id})
        if job:
            job["_id"] = str(job["_id"])
        return job
    except Exception as e:
        logger.error(f"Failed to get job {job_id}: {e}")
        return None

async def get_recent_jobs(limit: int = 5) -> List[Dict[str, Any]]:
    """Retrieve recently triggered scraping jobs."""
    try:
        database = get_db()
        cursor = database[JOBS_COLLECTION].find({}).sort("started_at", -1).limit(limit)
        jobs = await cursor.to_list(length=limit)
        for j in jobs:
            j["_id"] = str(j["_id"])
        return jobs
    except Exception as e:
        logger.error(f"Failed to retrieve recent jobs: {e}")
        return []
