"""
Auth routes — JWT registration, login, and token refresh.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from jose import jwt
from passlib.context import CryptContext

from app.dependencies import get_db, get_current_user
from app.models.user import User
from app.schemas import RegisterRequest, LoginRequest, TokenResponse, UserResponse
from app.config import get_settings
from app.utils.helpers import format_response

router = APIRouter()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
settings = get_settings()


def _create_token(user_id: str, expires_delta: timedelta) -> str:
    expire = datetime.now(timezone.utc) + expires_delta
    return jwt.encode(
        {"sub": str(user_id), "exp": expire},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


@router.post("/register")
async def register(req: RegisterRequest, db: AsyncSession = Depends(get_db)):
    """Register a new user."""
    existing = await db.execute(select(User).where(User.email == req.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")

    user = User(
        email=req.email,
        password_hash=pwd_context.hash(req.password),
        org_name=req.org_name,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    access = _create_token(user.id, timedelta(minutes=settings.access_token_expire_minutes))
    refresh = _create_token(user.id, timedelta(days=7))

    return format_response(True, {
        "user": {"id": str(user.id), "email": user.email, "org_name": user.org_name},
        "tokens": {"access_token": access, "refresh_token": refresh, "token_type": "bearer"},
    })


@router.post("/login")
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    """Login with email and password."""
    result = await db.execute(select(User).where(User.email == req.email))
    user = result.scalar_one_or_none()

    if not user or not pwd_context.verify(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    access = _create_token(user.id, timedelta(minutes=settings.access_token_expire_minutes))
    refresh = _create_token(user.id, timedelta(days=7))

    return format_response(True, {
        "user": {"id": str(user.id), "email": user.email, "org_name": user.org_name},
        "tokens": {"access_token": access, "refresh_token": refresh, "token_type": "bearer"},
    })


@router.get("/me")
async def get_me(user: User = Depends(get_current_user)):
    """Get current user profile."""
    return format_response(True, {
        "id": str(user.id),
        "email": user.email,
        "org_name": user.org_name,
        "tier": user.tier,
        "created_at": user.created_at.isoformat(),
    })
