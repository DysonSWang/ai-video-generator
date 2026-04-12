"""Auth数据库 - SQLAlchemy engine/session"""

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent.parent
AUTH_DB_PATH = os.getenv("AUTH_DB_PATH", str(BASE_DIR / "auth.db"))

engine = create_engine(
    f"sqlite:///{AUTH_DB_PATH}",
    connect_args={"check_same_thread": False}
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    """依赖注入：获取数据库会话"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_auth_db():
    """初始化Auth数据库表"""
    from app.auth import models  # noqa: import models to register them
    Base.metadata.create_all(bind=engine)
