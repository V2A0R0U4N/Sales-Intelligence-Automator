"""
Chatbot routes — placeholder for RAG chatbot (Phase 2).
"""
from fastapi import APIRouter
from app.utils.helpers import format_response

router = APIRouter()


@router.post("/query")
async def chatbot_query():
    """RAG chatbot query — to be implemented with Qdrant integration."""
    return format_response(True, {
        "message": "RAG chatbot will be implemented in the next phase",
        "status": "not_implemented",
    })
