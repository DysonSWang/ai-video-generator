"""Auth中间件 - JWT + API Key 认证"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.auth.database import SessionLocal
from app.auth.models import User
from app.auth import service as auth_service
from app.auth import api_key_service


class AuthMiddleware(BaseHTTPMiddleware):
    """认证中间件：填充 request.state.user_id"""

    # 不需要认证的路径
    PUBLIC_PATHS = {
        "/",
        "/api/auth/login",
        "/api/auth/refresh",
        "/static",
        "/templates",
        "/health",
    }

    def _is_public(self, path: str) -> bool:
        if path.startswith("/static"):
            return True
        for p in self.PUBLIC_PATHS:
            if path == p or path.startswith(p + "/"):
                return True
        return False

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # 公开路径直接过
        if self._is_public(path):
            return await call_next(request)

        user_id = None
        is_admin = False

        # 1. 尝试 Bearer JWT
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            payload = auth_service.verify_jwt_token(token)
            if payload and payload.get("type") == "access":
                user_id = payload.get("sub")

        # 2. 尝试 X-API-Key
        if not user_id:
            api_key = request.headers.get("X-API-Key", "")
            if api_key:
                db = SessionLocal()
                try:
                    user_id = api_key_service.verify_api_key(db, api_key)
                finally:
                    db.close()

        # 未认证
        if not user_id:
            return JSONResponse(
                status_code=401,
                content={"detail": "未认证"},
            )

        # 填充 user_id 到 request.state
        request.state.user_id = user_id

        # 检查是否为管理员
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == user_id).first()
            if user:
                is_admin = bool(user.is_admin)
        finally:
            db.close()

        request.state.is_admin = is_admin

        return await call_next(request)
