"""
MongoDB connection and collection setup using Motor (async driver).
Supports MongoDB Atlas or local MongoDB instance.
Falls back to in-memory storage if MongoDB is unavailable.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv()

MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
DB_NAME = os.getenv("DB_NAME", "sales_intelligence")

# Global client and database references
_client: AsyncIOMotorClient = None
_db = None

# In-memory fallback storage
_memory_store = {"jobs": {}, "leads": {}, "icp_profiles": {}, "chat_sessions": {}}
_use_memory = False


async def connect_db():
    """Initialize MongoDB connection. Falls back to in-memory if unavailable."""
    global _client, _db, _use_memory

    try:
        _client = AsyncIOMotorClient(MONGODB_URI, serverSelectionTimeoutMS=3000)
        # Test the connection
        await _client.admin.command("ping")
        _db = _client[DB_NAME]
        _use_memory = False
        print(f"[DB] Connected to MongoDB: {DB_NAME}")
    except Exception as e:
        print(f"[DB] MongoDB unavailable ({e}). Using in-memory storage.")
        _use_memory = True


async def close_db():
    """Close MongoDB connection."""
    global _client
    if _client:
        _client.close()
        print("[DB] MongoDB connection closed.")


def generate_id() -> str:
    """Generate a unique job/lead ID."""
    return str(uuid.uuid4())[:8]


# ---------------------
# Job Operations
# ---------------------

async def create_job(lead_count: int) -> str:
    """Create a new analysis job. Returns the job ID."""
    job_id = generate_id()
    job_doc = {
        "job_id": job_id,
        "status": "processing",
        "lead_count": lead_count,
        "completed_count": 0,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    if _use_memory:
        _memory_store["jobs"][job_id] = job_doc
    else:
        await _db.jobs.insert_one(job_doc)

    return job_id


async def get_job(job_id: str) -> dict | None:
    """Get job by ID."""
    if _use_memory:
        return _memory_store["jobs"].get(job_id)
    else:
        return await _db.jobs.find_one({"job_id": job_id}, {"_id": 0})


async def update_job(job_id: str, updates: dict):
    """Update job fields."""
    if _use_memory:
        if job_id in _memory_store["jobs"]:
            _memory_store["jobs"][job_id].update(updates)
    else:
        await _db.jobs.update_one({"job_id": job_id}, {"$set": updates})


async def increment_job_completed(job_id: str):
    """Increment the completed lead count for a job."""
    if _use_memory:
        if job_id in _memory_store["jobs"]:
            _memory_store["jobs"][job_id]["completed_count"] += 1
            job = _memory_store["jobs"][job_id]
            if job["completed_count"] >= job["lead_count"]:
                job["status"] = "completed"
    else:
        result = await _db.jobs.find_one_and_update(
            {"job_id": job_id},
            {"$inc": {"completed_count": 1}},
            return_document=True,
        )
        if result and result["completed_count"] >= result["lead_count"]:
            await _db.jobs.update_one(
                {"job_id": job_id}, {"$set": {"status": "completed"}}
            )


# ---------------------
# Lead Operations
# ---------------------

async def create_lead(lead_doc: dict) -> str:
    """Insert a new lead document. Returns the lead ID."""
    lead_id = generate_id()
    lead_doc["lead_id"] = lead_id

    if _use_memory:
        _memory_store["leads"][lead_id] = lead_doc
    else:
        await _db.leads.insert_one(lead_doc)

    return lead_id


async def update_lead(lead_id: str, updates: dict):
    """Update lead fields."""
    if _use_memory:
        if lead_id in _memory_store["leads"]:
            _memory_store["leads"][lead_id].update(updates)
    else:
        await _db.leads.update_one({"lead_id": lead_id}, {"$set": updates})


async def get_leads_by_job(job_id: str) -> list[dict]:
    """Get all leads for a job."""
    if _use_memory:
        return [
            lead
            for lead in _memory_store["leads"].values()
            if lead.get("job_id") == job_id
        ]
    else:
        cursor = _db.leads.find({"job_id": job_id}, {"_id": 0})
        return await cursor.to_list(length=100)


async def get_lead(lead_id: str) -> dict | None:
    """Get a single lead by ID."""
    if _use_memory:
        return _memory_store["leads"].get(lead_id)
    else:
        return await _db.leads.find_one({"lead_id": lead_id}, {"_id": 0})


async def search_leads(query: str, limit: int = 5) -> list[dict]:
    """
    Search for completed leads by company name (case-insensitive substring match).
    Used by the messaging agent to find leads from WhatsApp.
    """
    query_lower = query.lower().strip()
    if not query_lower:
        return []

    if _use_memory:
        results = []
        for lead in _memory_store["leads"].values():
            if lead.get("status") != "completed":
                continue
            name = (lead.get("company_name") or "").lower()
            if query_lower in name:
                results.append(lead)
            if len(results) >= limit:
                break
        return results
    else:
        import re
        cursor = _db.leads.find(
            {
                "status": "completed",
                "company_name": {"$regex": re.escape(query), "$options": "i"},
            },
            {"_id": 0},
        ).limit(limit)
        return await cursor.to_list(length=limit)


# ---------------------
# ICP Profile Operations
# ---------------------

async def save_icp_profile(profile_doc: dict) -> str:
    """Save or update an ICP profile. Returns the profile_id."""
    profile_id = profile_doc.get("profile_id", generate_id())
    profile_doc["profile_id"] = profile_id

    if _use_memory:
        _memory_store["icp_profiles"][profile_id] = profile_doc
    else:
        await _db.icp_profiles.replace_one(
            {"profile_id": profile_id},
            profile_doc,
            upsert=True,
        )

    return profile_id


async def get_icp_profile(profile_id: str) -> dict | None:
    """Get an ICP profile by ID."""
    if _use_memory:
        return _memory_store["icp_profiles"].get(profile_id)
    else:
        return await _db.icp_profiles.find_one({"profile_id": profile_id}, {"_id": 0})


async def list_icp_profiles() -> list[dict]:
    """List all saved ICP profiles."""
    if _use_memory:
        return list(_memory_store["icp_profiles"].values())
    else:
        cursor = _db.icp_profiles.find({}, {"_id": 0})
        return await cursor.to_list(length=50)


async def delete_icp_profile(profile_id: str) -> bool:
    """Delete an ICP profile. Returns True if found."""
    if _use_memory:
        return _memory_store["icp_profiles"].pop(profile_id, None) is not None
    else:
        result = await _db.icp_profiles.delete_one({"profile_id": profile_id})
        return result.deleted_count > 0


# ---------------------
# Chat Session Operations (Phase 4 — RAG)
# ---------------------

async def save_chat_message(lead_id: str, role: str, content: str):
    """Append a chat message to a lead's conversation history."""
    from datetime import datetime, timezone
    msg = {"role": role, "content": content, "ts": datetime.now(timezone.utc).isoformat()}

    if _use_memory:
        if lead_id not in _memory_store["chat_sessions"]:
            _memory_store["chat_sessions"][lead_id] = []
        _memory_store["chat_sessions"][lead_id].append(msg)
    else:
        await _db.chat_sessions.update_one(
            {"lead_id": lead_id},
            {"$push": {"messages": msg}},
            upsert=True,
        )


async def get_chat_history(lead_id: str) -> list[dict]:
    """Get all chat messages for a lead."""
    if _use_memory:
        return list(_memory_store["chat_sessions"].get(lead_id, []))
    else:
        doc = await _db.chat_sessions.find_one({"lead_id": lead_id})
        return doc.get("messages", []) if doc else []
