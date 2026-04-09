"""auth/dependencies.py"""
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from auth.security import decode_token
from database.connection import get_db, get_user_by_id
from database.models import PresalesUser

security = OAuth2PasswordBearer(tokenUrl="api/v1/auth/token")


async def get_current_user(
    token: str = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> PresalesUser:
    payload = decode_token(token)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                             detail="Invalid or expired token",
                             headers={"WWW-Authenticate": "Bearer"})
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Token missing subject")
    user = await get_user_by_id(db, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")
    return user
