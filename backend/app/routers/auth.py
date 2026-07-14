"""Auth routes: login (OAuth2 password form) + current user."""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlmodel import Session

from ..auth import authenticate, create_access_token, get_current_user, hash_password, verify_password
from ..database import get_session
from ..models import User
from ..schemas import ChangePassword, LoginResponse, UserRead

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
def login(
    form: OAuth2PasswordRequestForm = Depends(),
    session: Session = Depends(get_session),
):
    user = authenticate(session, form.username, form.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
        )
    return LoginResponse(access_token=create_access_token(user), user=UserRead.model_validate(user))


@router.get("/me", response_model=UserRead)
def me(current: User = Depends(get_current_user)):
    return current


@router.post("/change-password")
def change_password(
    payload: ChangePassword,
    current: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    if not verify_password(payload.old_password, current.password_hash):
        raise HTTPException(status_code=400, detail="原密码不正确")
    if len(payload.new_password) < 6:
        raise HTTPException(status_code=422, detail="新密码至少 6 位")
    current.password_hash = hash_password(payload.new_password)
    session.add(current)
    session.commit()
    return {"ok": True}
