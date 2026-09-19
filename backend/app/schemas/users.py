"""用户管理接口的请求模型。"""

from pydantic import BaseModel


class CreateUserRequest(BaseModel):
    username: str
    password: str
    display_name: str = ""
    role: str = "viewer"


class UpdateUserRequest(BaseModel):
    role: str | None = None
    is_active: bool | None = None
    display_name: str | None = None
    reset_password: str | None = None
