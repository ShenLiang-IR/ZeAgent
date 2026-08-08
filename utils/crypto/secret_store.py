"""Secret 加密 + 解密工具。

设计参见 docs/specs/2026-07-19-secret-encryption-design.md。

核心 API：
- encrypt_secret(plain: str) -> str  # 返回 "enc:xxx" 格式密文
- decrypt_secret(cipher: str) -> str  # 自动识别 enc: 前缀；无前缀视为明文（向下兼容）

主密钥：从 JASYPT_MASTER_KEY 环境变量读（不落盘）。
复用 utils.jasypt_crypto 的 DES3 + PBKDF 算法（与现有 RLS 字段加密一致）。

兼容性：
- 旧明文 secret（无 enc: 前缀）直接返回，不抛异常
- 空 secret 返回空字符串
- 错误主密钥解密失败时返回原 cipher（认作明文）+ 记日志，不抛异常
"""
import os

from loguru import logger

# 加密密文前缀，用于自动识别（避免误把明文当密文）
ENC_PREFIX = "enc:"


def _get_master_key() -> str:
    """从环境变量读主密钥。

    Returns:
        主密钥字符串
    Raises:
        RuntimeError: JASYPT_MASTER_KEY 未设置（加密时需要）
    """
    key = os.getenv("JASYPT_MASTER_KEY", "")
    if not key:
        # 兼容老变量名（如果用户已配置）
        key = os.getenv("JASYPT_ENCRYPTION_PASSWORD", "")
    return key


def encrypt_secret(plain: str) -> str:
    """加密 secret，返回 "enc:xxx" 格式密文。

    Args:
        plain: 明文 secret

    Returns:
        "enc:" + base64 密文；空字符串返回空字符串

    Raises:
        RuntimeError: JASYPT_MASTER_KEY 未设置
    """
    if not plain:
        return ""
    master_key = _get_master_key()
    if not master_key:
        raise RuntimeError(
            "JASYPT_MASTER_KEY 环境变量未设置；无法加密 secret。"
            "请设置后重启（export JASYPT_MASTER_KEY=xxx）"
        )
    from utils.jasypt_crypto import jasypt_encrypt
    cipher_b64 = jasypt_encrypt(master_key, plain)
    return ENC_PREFIX + cipher_b64


def decrypt_secret(cipher: str) -> str:
    """解密 secret。

    自动识别 enc: 前缀：
    - 有 enc: 前缀：解密返回明文
    - 无前缀：视为明文直接返回（向下兼容旧明文）
    - 空字符串：返回空字符串

    解密失败（key 缺失 / 错误主密钥 / 损坏密文）时 raise RuntimeError，
    拒绝静默 fallback（不返回 cipher 当明文，避免拿密文当 API key 静默失败）。

    Args:
        cipher: 密文（"enc:xxx"）或明文

    Returns:
        解密后的明文；失败返回原值
    """
    if not cipher:
        return ""
    if not cipher.startswith(ENC_PREFIX):
        # 无 enc: 前缀，视为明文直接返回（向下兼容）
        return cipher
    # 有 enc: 前缀，解密
    master_key = _get_master_key()
    if not master_key:
        # 生产安全：enc: 密文存在但 key 缺失 → 拒绝静默 fallback（不返回 cipher 当明文）
        raise RuntimeError(
            "JASYPT_MASTER_KEY 未设置，无法解密 enc: 密文；"
            "请设置环境变量 JASYPT_MASTER_KEY 后重启"
        )
    cipher_b64 = cipher[len(ENC_PREFIX):]
    try:
        from utils.jasypt_crypto import jasypt_decrypt
        return jasypt_decrypt(master_key, cipher_b64)
    except Exception as e:
        # 解密失败：主密钥不匹配或密文损坏 → 拒绝静默 fallback（不返回 cipher 当明文）
        logger.error(f"[secret_store] decrypt failed (master key 不匹配或密文损坏): {e}")
        raise RuntimeError(
            f"decrypt failed: enc: 密文解密失败（主密钥不匹配或密文损坏）: {e}"
        ) from e
