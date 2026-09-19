"""认证接口的请求模型。"""

from pydantic import BaseModel


class LoginRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str
