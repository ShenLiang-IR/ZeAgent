import base64
import hashlib
import os
from Crypto.Cipher import DES3
BLOCK_SIZE = 8
KEY_ITERATIONS = 1000
SALT_SIZE = 8
DERIVED_KEY_LEN = 24
DERIVED_IV_LEN = 8
def _pkcs7_pad(data: bytes) -> bytes:
    pad_len = BLOCK_SIZE - (len(data) % BLOCK_SIZE)
    return data + bytes([pad_len]) * pad_len
def _pkcs7_unpad(data: bytes) -> bytes:
    if not data:
        raise ValueError("解密失败: 数据为空")
    pad_len = data[-1]
    if pad_len < 1 or pad_len > BLOCK_SIZE:
        raise ValueError(f"无效的填充长度: {pad_len}")
    if data[-pad_len:] != bytes([pad_len]) * pad_len:
        raise ValueError("解密失败: 填充校验不通过")
    return data[:-pad_len]
def _derive_key_and_iv(password: str, salt: bytes) -> tuple[bytes, bytes]:
    pwd = password.encode('utf-8')
    if salt[:4] == salt[4:]:
        salt = salt[3::-1] + salt[4:]
    left = salt[:4]
    for _ in range(KEY_ITERATIONS):
        left = hashlib.md5(left + pwd).digest()
    right = salt[4:]
    for _ in range(KEY_ITERATIONS):
        right = hashlib.md5(right + pwd).digest()
    derived = left + right
    return derived[:DERIVED_KEY_LEN], derived[DERIVED_KEY_LEN:]
def jasypt_encrypt(password: str, plaintext: str) -> str:
    if not password:
        raise ValueError("")
    if not plaintext:
        raise ValueError("")
    salt = os.urandom(SALT_SIZE)
    key, iv = _derive_key_and_iv(password, salt)
    cipher = DES3.new(key, DES3.MODE_CBC, iv)
    encrypted = cipher.encrypt(_pkcs7_pad(plaintext.encode('utf-8')))
    return base64.b64encode(salt + encrypted).decode('utf-8')
def jasypt_decrypt(password: str, ciphertext_b64: str) -> str:
    if not password:
        raise ValueError("")
    if not ciphertext_b64:
        raise ValueError("")
    try:
        data = base64.b64decode(ciphertext_b64)
    except Exception as e:
        raise ValueError(f"Base64 : {e}") from e
    if len(data) <= SALT_SIZE:
        raise ValueError(f"{len(data)}  {SALT_SIZE + 1} ")
    salt = data[:SALT_SIZE]
    encrypted = data[SALT_SIZE:]
    key, iv = _derive_key_and_iv(password, salt)
    cipher = DES3.new(key, DES3.MODE_CBC, iv)
    return _pkcs7_unpad(cipher.decrypt(encrypted)).decode('utf-8')
if __name__ == "__main__":
    import sys
    if len(sys.argv) >= 4:
        mode = sys.argv[1]
        key = sys.argv[2]
        text = sys.argv[3]
        if mode == "0":
            print(f": {jasypt_encrypt(key, text)}")
        elif mode == "1":
            print(f": {jasypt_decrypt(key, text)}")
        else:
            print(": 0=, 1=")
    else:
        print(": python jasypt_crypto.py <0|1> <> <>")
        print("  0: , 1: ")