"""utils.crypto 包：密钥加密 + 解密工具。

设计参见 docs/specs/2026-07-19-secret-encryption-design.md（本期新建）。

复用 utils.jasypt_crypto 的 DES3 + PBKDF 算法（与现有 RLS 字段加密一致），
主密钥从 JASYPT_MASTER_KEY 环境变量读（不落盘）。

约定：
- 加密后的密文带 "enc:" 前缀，便于自动识别
- 解密时自动识别 enc: 前缀；无前缀视为明文直接返回（向下兼容）
- 空 secret 返回空字符串
"""
