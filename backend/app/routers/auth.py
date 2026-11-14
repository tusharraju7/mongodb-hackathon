from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core import security
from app.models import Identity

router = APIRouter(tags=["auth"])


class LoginBody(BaseModel):
    email: str
    password: str


@router.post("/auth/login")
def login(body: LoginBody) -> dict:
    identity = security.authenticate(body.email, body.password)
    if identity is None:
        raise HTTPException(status_code=401, detail="Wrong email or password")
    return {"token": security.issue_token(identity), "user": identity.model_dump()}


@router.get("/me")
def me(identity: Identity = Depends(security.current_identity)) -> dict:
    return identity.model_dump()
