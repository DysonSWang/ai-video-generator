#!/usr/bin/env python3
"""初始化管理员账户 - 运行一次即可"""

import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.auth.database import SessionLocal, init_auth_db
from app.auth.models import User
from app.auth.service import get_password_hash

def seed_admin():
    init_auth_db()
    db = SessionLocal()
    try:
        # 检查是否已有管理员
        admin = db.query(User).filter(User.is_admin == 1).first()
        if admin:
            print(f"管理员已存在: {admin.username} (id={admin.id})")
            return

        username = os.getenv("ADMIN_USERNAME", "admin")
        password = os.getenv("ADMIN_PASSWORD", "admin123")
        if not password or password == "admin123":
            print("WARNING: 使用默认密码！请通过 ADMIN_PASSWORD 环境变量设置强密码")

        admin = User(
            id=str(uuid.uuid4()),
            username=username,
            password_hash=get_password_hash(password),
            nickname="管理员",
            is_admin=1,
        )
        db.add(admin)
        db.commit()
        print(f"管理员创建成功: {username}")
        print(f"请登录后修改密码或创建其他管理员账户")
    finally:
        db.close()

if __name__ == "__main__":
    seed_admin()
