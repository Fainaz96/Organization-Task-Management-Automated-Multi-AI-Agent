
from pydantic import BaseModel, EmailStr
from typing import Optional, List
class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class LoginResponse(BaseModel):
    statuscode: int
    message: str
    role:Optional[str] = None
    username: Optional[str]  = None
    token: Optional[str]  = None

class ForgotPasswordRequest(BaseModel):
    email: EmailStr

class ForgotPasswordResponse(BaseModel):
    statuscode: int
    message: str

class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str

class ChangePasswordResponse(BaseModel):
    statuscode: int
    message: str

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str