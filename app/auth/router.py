"""Auth路由 - /api/auth/* 和用户管理接口"""

import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.auth.database import get_db
from app.auth.models import User, BalanceTransaction
from app.auth import schemas as auth_schemas
from app.auth import service as auth_service
from app.auth import api_key_service
from app.auth import usage_service

router = APIRouter(prefix="/api", tags=["auth"])


# ========== 依赖项 ==========

async def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    """从 request.state 读取当前用户（由 AuthMiddleware 填充）"""
    if not hasattr(request.state, "user_id"):
        raise HTTPException(401, "未认证")
    user = db.query(User).filter(User.id == request.state.user_id).first()
    if not user:
        raise HTTPException(401, "用户不存在")
    if user.status != "active":
        raise HTTPException(403, "账户已被禁用")
    return user


async def get_current_admin(
    user: User = Depends(get_current_user),
) -> User:
    """仅限管理员"""
    if not user.is_admin:
        raise HTTPException(403, "需要管理员权限")
    return user


# ========== Auth 接口 ==========

@router.post("/auth/login", response_model=auth_schemas.LoginResponse)
def login(body: auth_schemas.LoginRequest, db: Session = Depends(get_db)):
    """用户名+密码登录"""
    user = db.query(User).filter(User.username == body.username).first()
    if not user:
        raise HTTPException(401, "用户名或密码错误")
    if not auth_service.verify_password(body.password, user.password_hash):
        raise HTTPException(401, "用户名或密码错误")
    if user.status != "active":
        raise HTTPException(403, "账户已被禁用")

    access_token = auth_service.create_access_token(user.id)
    refresh_token = auth_service.create_refresh_token(user.id)

    return auth_schemas.LoginResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=1440 * 60,  # 24小时
    )


@router.post("/auth/refresh", response_model=auth_schemas.RefreshResponse)
def refresh(body: auth_schemas.RefreshRequest, db: Session = Depends(get_db)):
    """刷新 Access Token"""
    payload = auth_service.verify_jwt_token(body.refresh_token)
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(401, "无效的 refresh token")

    user_id = payload.get("sub")
    user = db.query(User).filter(User.id == user_id).first()
    if not user or user.status != "active":
        raise HTTPException(401, "用户不可用")

    access_token = auth_service.create_access_token(user_id)
    return auth_schemas.RefreshResponse(
        access_token=access_token,
        expires_in=1440 * 60,
    )


@router.get("/auth/me", response_model=auth_schemas.MeResponse)
def get_me(user: User = Depends(get_current_user)):
    """获取当前用户信息"""
    return auth_schemas.MeResponse(
        id=user.id,
        username=user.username,
        nickname=user.nickname,
        balance=user.balance,
        status=user.status,
        is_admin=user.is_admin,
    )


# ========== 用户管理接口 (管理员) ==========

@router.get("/users", response_model=list[auth_schemas.UserResponse])
def list_users(
    skip: int = 0,
    limit: int = 20,
    search: Optional[str] = None,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """管理员：列出所有用户（分页）"""
    query = db.query(User)
    if search:
        query = query.filter(
            (User.username.contains(search)) | (User.nickname.contains(search))
        )
    return query.order_by(User.created_at.desc()).offset(skip).limit(limit).all()


@router.post("/users", response_model=auth_schemas.UserResponse)
def create_user(
    body: auth_schemas.UserCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """管理员：创建用户"""
    # 检查用户名唯一
    existing = db.query(User).filter(User.username == body.username).first()
    if existing:
        raise HTTPException(400, "用户名已存在")

    user = User(
        id=str(uuid.uuid4()),
        username=body.username,
        password_hash=auth_service.get_password_hash(body.password),
        nickname=body.nickname,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.get("/users/{user_id}", response_model=auth_schemas.UserDetailResponse)
def get_user(
    user_id: str,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """管理员：查看用户详情+用量"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "用户不存在")

    usage = usage_service.get_usage_summary(db, user_id)
    api_key_count = db.query(api_key_service.ApiKey).filter(
        api_key_service.ApiKey.user_id == user_id
    ).count()

    return auth_schemas.UserDetailResponse(
        id=user.id,
        username=user.username,
        nickname=user.nickname,
        balance=user.balance,
        status=user.status,
        is_admin=user.is_admin,
        created_at=user.created_at,
        task_count=usage["task_count"],
        video_duration_seconds=usage["video_duration_seconds"],
        api_key_count=api_key_count,
    )


@router.put("/users/{user_id}/status")
def update_user_status(
    user_id: str,
    body: dict,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """管理员：禁用/启用账户"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "用户不存在")

    new_status = body.get("status", "active")
    if new_status not in ("active", "suspended"):
        raise HTTPException(400, "无效状态")

    user.status = new_status
    db.commit()
    return {"ok": True}


@router.put("/users/{user_id}/balance")
def adjust_balance(
    user_id: str,
    body: auth_schemas.BalanceAdjustRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """管理员：调整余额"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "用户不存在")

    balance_before = user.balance
    user.balance = user.balance + body.amount
    if user.balance < 0:
        raise HTTPException(400, "余额不能为负")

    # 记录变动
    txn = BalanceTransaction(
        id=str(uuid.uuid4()),
        user_id=user_id,
        amount=body.amount,
        transaction_type="adjust",
        balance_before=balance_before,
        balance_after=user.balance,
        description=body.description or "管理员调整",
    )
    db.add(txn)
    db.commit()
    return {"balance": user.balance}


# ========== 计费配置接口 ==========

RATE_KEY = "billing_rate_per_second"
DEFAULT_RATE = 0.01  # 默认 0.01 元/秒

@router.get("/admin/config/billing", response_model=auth_schemas.BillingConfigResponse)
def get_billing_config(
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """获取计费配置"""
    from app.auth.models import SystemConfig
    cfg = db.query(SystemConfig).filter(SystemConfig.key == RATE_KEY).first()
    if cfg:
        import json
        data = json.loads(cfg.value)
        return auth_schemas.BillingConfigResponse(
            rate_per_second=data.get("rate_per_second", DEFAULT_RATE),
            updated_at=str(cfg.updated_at) if cfg.updated_at else None,
        )
    return auth_schemas.BillingConfigResponse(rate_per_second=DEFAULT_RATE)


@router.put("/admin/config/billing")
def update_billing_config(
    body: auth_schemas.BillingConfigUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """更新计费配置"""
    import json
    from app.auth.models import SystemConfig
    cfg = db.query(SystemConfig).filter(SystemConfig.key == RATE_KEY).first()
    if cfg:
        cfg.value = json.dumps({"rate_per_second": body.rate_per_second})
        cfg.updated_by = admin.id
    else:
        cfg = SystemConfig(
            key=RATE_KEY,
            value=json.dumps({"rate_per_second": body.rate_per_second}),
            updated_by=admin.id,
        )
        db.add(cfg)
    db.commit()
    return {"rate_per_second": body.rate_per_second}


# ========== API Key 接口 ==========

@router.get("/apikeys", response_model=list[auth_schemas.ApiKeyResponse])
def list_api_keys(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """列出用户的 API Key"""
    return api_key_service.get_api_keys(db, user.id)


@router.post("/apikeys", response_model=auth_schemas.ApiKeyCreateResponse)
def create_api_key(
    body: auth_schemas.ApiKeyCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """创建新的 API Key（返回完整key，仅此一次）"""
    record, raw_key = api_key_service.create_api_key(db, user.id, body.name)
    return auth_schemas.ApiKeyCreateResponse(
        id=record.id,
        api_key=raw_key,
        key_prefix=record.key_prefix,
        name=record.name,
    )


@router.delete("/apikeys/{key_id}")
def delete_api_key(
    key_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """删除 API Key"""
    ok = api_key_service.delete_api_key(db, key_id, user.id)
    if not ok:
        raise HTTPException(404, "API Key 不存在")
    return {"ok": True}


# ========== 费用估算接口 ==========

@router.post("/estimate-cost", response_model=auth_schemas.EstimateCostResponse)
def estimate_cost_api(
    body: dict,
    db: Session = Depends(get_db),
):
    """根据文案估算生成费用"""
    text = body.get("text", "")
    if not text:
        raise HTTPException(400, "文案不能为空")
    return usage_service.estimate_cost(db, text)


# ========== 用量接口 ==========

@router.get("/usage/summary", response_model=auth_schemas.UsageSummary)
def get_usage_summary(
    month: Optional[str] = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """当月用量汇总"""
    return usage_service.get_usage_summary(db, user.id, month)


@router.get("/usage/history", response_model=list[auth_schemas.UsageHistoryItem])
def get_usage_history(
    limit: int = 12,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """按月用量历史"""
    return usage_service.get_usage_history(db, user.id, limit)


# ========== 余额接口 ==========

@router.get("/billing/balance", response_model=auth_schemas.BalanceResponse)
def get_balance(
    user: User = Depends(get_current_user),
):
    """查询余额"""
    return auth_schemas.BalanceResponse(balance=user.balance)


@router.get("/billing/transactions", response_model=list[auth_schemas.BalanceTransactionResponse])
def get_transactions(
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """余额变动记录"""
    return (
        db.query(BalanceTransaction)
        .filter(BalanceTransaction.user_id == user.id)
        .order_by(BalanceTransaction.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )


# ========== 音色库接口 ==========

@router.post("/voices", response_model=auth_schemas.VoiceProfileResponse)
def create_voice(
    body: auth_schemas.VoiceCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """从已上传音频创建音色档案（克隆音色到音色库）"""
    from pathlib import Path
    from app.auth.models import VoiceProfile

    # 解析参考音频路径（UPLOAD_DIR = BASE_DIR / "assets"）
    BASE_DIR = Path(__file__).parent.parent.parent  # app/auth/router.py -> app -> 项目根
    UPLOAD_DIR = BASE_DIR / "assets"
    audio_extensions = ['.wav', '.mp3', '.m4a', '.aac']
    reference_audio = None
    for ext in audio_extensions:
        audio_path = UPLOAD_DIR / user.id / "audios" / f"{body.reference_audio_id}{ext}"
        if audio_path.exists():
            reference_audio = str(audio_path)
            break

    if not reference_audio:
        raise HTTPException(404, "参考音频不存在或已删除")

    # 检查同名音色
    existing = db.query(VoiceProfile).filter(
        VoiceProfile.user_id == user.id,
        VoiceProfile.voice_name == body.voice_name
    ).first()
    if existing:
        raise HTTPException(400, "音色名称已存在")

    profile = VoiceProfile(
        id=str(uuid.uuid4()),
        user_id=user.id,
        voice_uri=f"user_voice_{uuid.uuid4().hex[:8]}",  # OmniVoice无持久voice_uri，用自定义ID
        voice_name=body.voice_name,
        reference_audio=reference_audio,
        reference_text="",
        usage_count=0,
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


@router.get("/voices", response_model=list[auth_schemas.VoiceProfileResponse])
def list_voices(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """列出用户的音色档案"""
    from app.auth.models import VoiceProfile
    return (
        db.query(VoiceProfile)
        .filter(VoiceProfile.user_id == user.id)
        .order_by(VoiceProfile.created_at.desc())
        .all()
    )


@router.delete("/voices/{voice_id}")
def delete_voice(
    voice_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """删除音色档案"""
    from app.auth.models import VoiceProfile
    profile = (
        db.query(VoiceProfile)
        .filter(VoiceProfile.id == voice_id, VoiceProfile.user_id == user.id)
        .first()
    )
    if not profile:
        raise HTTPException(404, "音色档案不存在")
    db.delete(profile)
    db.commit()
    return {"ok": True}


@router.post("/voices/{voice_id}/synthesize")
def synthesize_with_voice(
    voice_id: str,
    body: auth_schemas.VoiceSynthesizeRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """用已存音色合成语音"""
    from app.auth.models import VoiceProfile
    import asyncio
    from app.services.voice_clone import synthesize

    profile = (
        db.query(VoiceProfile)
        .filter(VoiceProfile.id == voice_id, VoiceProfile.user_id == user.id)
        .first()
    )
    if not profile:
        raise HTTPException(404, "音色档案不存在")

    # 增加使用次数
    profile.usage_count += 1
    db.commit()

    # 同步调用synthesize（因为是快速TTS）
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        result = loop.run_until_complete(
            synthesize(body.text, profile.voice_uri, output_path=body.output_path, speed=body.speed)
        )
    finally:
        loop.close()

    return {
        "audio_path": result.audio_path,
        "duration": result.duration,
    }
