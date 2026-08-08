"""认证安全配置校验（#17 加固）。

启动期校验 auth 配置，生产模式拒绝"裸奔"配置：
- enable_permission_check=false → 所有请求获得 admin 权限（无权限隔离）
- default_token 非空 → 无鉴权后门 token（任何人可冒充）

上述任一不安全配置存在且未显式 auth.allow_no_auth_in_production=true 时，
raise RuntimeError 阻止 server 启动（对齐 JWT secret 生产保护策略）。

设计：纯函数 + 关键字参数注入配置，便于单元测试（不依赖全局 config/DB）。
"""

from loguru import logger


def assert_auth_safety(
    *,
    enable_permission_check: bool,
    default_token: str,
    allow_no_auth_in_production: bool = False,
    jwt_secret: str = "",
    jwt_provider: str = "",
) -> None:
    """启动期认证安全配置校验：生产模式拒绝裸奔配置，不满足则 raise RuntimeError。

    Args:
        enable_permission_check: 是否开启权限校验（false=全员 admin）
        default_token: 无登录模式默认 token（非空=后门）
        allow_no_auth_in_production: 显式允许生产关闭鉴权（开发者明确确认，默认 false）
        jwt_secret: JWT 签名密钥（standalone provider 用；空/弱密钥=可伪造 token）
        jwt_provider: 认证 provider 名（standalone 时校验 jwt_secret）

    Raises:
        RuntimeError: 存在不安全配置且未显式 allow 时
    """
    issues = []
    if not enable_permission_check and not allow_no_auth_in_production:
        issues.append(
            "auth.enable_permission_check=false 会让所有请求获得 admin 权限；"
            "生产必须设为 true，开发环境若确需关闭鉴权请显式设 "
            "auth.allow_no_auth_in_production=true"
        )
    if default_token and not allow_no_auth_in_production:
        issues.append(
            "auth.default_token 已配置：这是无鉴权后门 token，生产环境禁止使用；"
            "若为开发环境请显式设 auth.allow_no_auth_in_production=true"
        )
    # standalone provider 用默认/空 jwt_secret → 攻击者可伪造任意 token
    if jwt_provider == "standalone" and not allow_no_auth_in_production:
        weak = {"", "change-me-in-production", "secret", "jwt_secret"}
        if jwt_secret in weak:
            issues.append(
                "auth.jwt_secret 为空或弱密钥：攻击者可伪造任意 token，"
                "生产必须设置高强度随机密钥（建议 >=32 字节）"
            )
    if issues:
        msg = "[Security] 认证安全配置不安全，拒绝启动：\n" + "\n".join(issues)
        logger.error(msg)
        raise RuntimeError(msg)


def assert_auth_safety_from_config() -> None:
    """从项目 config 读取认证配置并校验（server.py lifespan 启动期调用入口）。

    config 缺失/读取异常时不阻塞（由调用方 try/except 决定），仅当配置不安全时 raise。
    """
    from utils.config.config_loader import get_config

    enable_permission_check = bool(get_config("auth.enable_permission_check", True))
    default_token = str(get_config("auth.default_token", "") or "")
    allow_no_auth_in_production = bool(get_config("auth.allow_no_auth_in_production", False))
    jwt_secret = str(get_config("auth.jwt_secret", "") or "")
    jwt_provider = str(get_config("auth.provider", "") or "").lower()
    assert_auth_safety(
        enable_permission_check=enable_permission_check,
        default_token=default_token,
        allow_no_auth_in_production=allow_no_auth_in_production,
        jwt_secret=jwt_secret,
        jwt_provider=jwt_provider,
    )
