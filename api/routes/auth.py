"""api/routes/auth.py"""
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession

from auth.security import (hash_password, verify_password,
                             create_access_token, generate_reset_token)
from database.connection import (get_db, get_user_by_email, create_presales_user,
                                   set_user_password, set_reset_token, clear_reset_token,
                                   update_last_login)
from config.settings import settings

router = APIRouter(prefix="/auth", tags=["Auth"])


class CheckEmailRequest(BaseModel):
    email: EmailStr


class SetPasswordRequest(BaseModel):
    email: EmailStr
    password: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    email: str
    full_name: str | None
    is_first_login: bool = False


@router.post("/check-email")
async def check_email(payload: CheckEmailRequest, db: AsyncSession = Depends(get_db)):
    """Check if email exists and if password has been set (first-time flow)."""
    user = await get_user_by_email(db, payload.email)
    if not user:
        raise HTTPException(status_code=404, detail="Email not registered in the system")
    return {"exists": True, "password_set": user.password_set, "user_id": user.id}


@router.post("/set-password", response_model=TokenResponse)
async def set_password(payload: SetPasswordRequest, db: AsyncSession = Depends(get_db)):
    """First-time password creation for a new presales agent."""
    user = await get_user_by_email(db, payload.email)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.password_set:
        raise HTTPException(status_code=400,
                             detail="Password already set. Use login instead.")
    if len(payload.password) < 8:
        raise HTTPException(status_code=422, detail="Password must be at least 8 characters")

    hashed = hash_password(payload.password)
    await set_user_password(db, user.id, hashed)
    await update_last_login(db, user.id)

    token = create_access_token({"sub": user.id, "email": user.email})
    return TokenResponse(access_token=token, user_id=user.id,
                          email=user.email, full_name=user.full_name, is_first_login=True)


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)):
    """Login with email and password."""
    user = await get_user_by_email(db, payload.email)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not user.password_set or not user.hashed_password:
        raise HTTPException(status_code=400,
                             detail="Password not set. Please complete first-time setup.")
    if not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account disabled")

    await update_last_login(db, user.id)
    token = create_access_token({"sub": user.id, "email": user.email})
    return TokenResponse(access_token=token, user_id=user.id,
                          email=user.email, full_name=user.full_name)


@router.post("/forgot-password")
async def forgot_password(payload: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)):
    """Initiate password reset. In production, sends email."""
    user = await get_user_by_email(db, payload.email)
    if not user:
        # Don't reveal if email exists
        return {"message": "If the email is registered, a reset link has been sent."}

    token = generate_reset_token()
    expiry = datetime.utcnow() + timedelta(hours=1)
    await set_reset_token(db, user.id, token, expiry)

    # TODO: Send email in production via SMTP/SendGrid
    # For dev: return token directly
    return {"message": "Reset token generated.", "reset_token": token,
             "note": "In production this would be sent via email."}


@router.post("/reset-password")
async def reset_password(payload: ResetPasswordRequest, db: AsyncSession = Depends(get_db)):
    """Reset password using a valid token."""
    from sqlalchemy import select
    from database.models import PresalesUser
    r = await db.execute(select(PresalesUser).where(
        PresalesUser.reset_token == payload.token))
    user = r.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=400, detail="Invalid reset token")
    if user.reset_token_expiry and datetime.utcnow() > user.reset_token_expiry:
        raise HTTPException(status_code=400, detail="Reset token has expired")
    if len(payload.new_password) < 8:
        raise HTTPException(status_code=422, detail="Password must be at least 8 characters")

    hashed = hash_password(payload.new_password)
    await set_user_password(db, user.id, hashed)
    await clear_reset_token(db, user.id)
    return {"message": "Password reset successfully. You can now log in."}


@router.post("/register-agent")
async def register_agent(payload: CheckEmailRequest, db: AsyncSession = Depends(get_db)):
    """Admin endpoint to register a new presales agent (email only, no password yet)."""
    existing = await get_user_by_email(db, payload.email)
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")
    user = await create_presales_user(db, payload.email)
    return {"user_id": user.id, "email": user.email,
             "message": "Agent registered. They can now set their password on first login."}
