"""secret 加密/解密 CLI 工具。

用于将明文敏感配置（LLM api_key / DB password 等）加密为 enc: 密文，
贴回 agent_config.json 对应字段；运行时由 config_loader / llm_factory 自动解密。

用法：
  # 加密明文（输出 enc: 密文，贴回 agent_config.json 的 api_key 等字段）
  python command/encrypt_secret.py encrypt "sk-your-plain-api-key"

  # 解密 enc: 密文（验证用）
  python command/encrypt_secret.py decrypt "enc:xxxxx"

需先设置环境变量 JASYPT_MASTER_KEY（主密钥，不落盘）：
  # Linux/macOS
  export JASYPT_MASTER_KEY="your-master-key"
  # Windows PowerShell
  $env:JASYPT_MASTER_KEY="your-master-key"

设计参见 docs/specs/2026-07-19-secret-encryption-design.md。
"""
import os
import sys
from pathlib import Path

# 确保项目根在 sys.path（从 command/ 直接运行时也能 import utils）
_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from utils.crypto.secret_store import decrypt_secret, encrypt_secret  # noqa: E402


def encrypt(plain: str) -> str:
    """加密明文 → enc: 密文。需 JASYPT_MASTER_KEY，未设抛 RuntimeError。"""
    return encrypt_secret(plain)


def decrypt(cipher: str) -> str:
    """解密 enc: 密文 → 明文。无 enc: 前缀则原样返回（向下兼容）。"""
    return decrypt_secret(cipher)


def main() -> None:
    if len(sys.argv) < 3:
        print("用法: python command/encrypt_secret.py <encrypt|decrypt> <value>")
        print("  encrypt: 明文 → enc: 密文（贴回 agent_config.json）")
        print("  decrypt: enc: 密文 → 明文（验证用）")
        print("需先设置 JASYPT_MASTER_KEY 环境变量")
        sys.exit(1)

    action = sys.argv[1].lower()
    value = sys.argv[2]

    if not os.getenv("JASYPT_MASTER_KEY"):
        print("错误: JASYPT_MASTER_KEY 环境变量未设置")
        print("  Linux/macOS: export JASYPT_MASTER_KEY=\"your-master-key\"")
        print("  Windows:     $env:JASYPT_MASTER_KEY=\"your-master-key\"")
        sys.exit(1)

    if action == "encrypt":
        result = encrypt(value)
        print("密文（贴回 agent_config.json 的敏感字段）:")
        print(result)
    elif action == "decrypt":
        result = decrypt(value)
        print("明文:")
        print(result)
    else:
        print(f"未知操作: {action}（支持: encrypt / decrypt）")
        sys.exit(1)


if __name__ == "__main__":
    main()
