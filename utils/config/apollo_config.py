from typing import Dict, Any, List
import os
import json
import re
from loguru import logger
from utils.config.config_loader import get_config
from utils.jasypt_crypto import jasypt_decrypt
try:
    from pyapollo.client import ApolloClient
except ImportError:
    ApolloClient = None  # pyapollo 未安装时降级（LOCAL_TEST_MODE=True 走本地，不需要它）
JASYPT_KEY = get_config("apollo.encrypt_key", "")
ENC_PATTERN = re.compile(r"^ENC\((.+)\)$")
def _decrypt_if_encrypted(value: str) -> str:
    if not value or not JASYPT_KEY:
        return value
    match = ENC_PATTERN.match(value)
    if match:
        try:
            return jasypt_decrypt(JASYPT_KEY, match.group(1))
        except Exception as e:
            logger.error(f"Jasypt : {e}")
            return value
    return value
LOCAL_TEST_MODE = get_config("apollo.local_test_mode", True)
APOLLO_CONFIG = {
    "app_id": get_config("apollo.app_id", "smart-agent-llm-admin"),
    "cluster": get_config("apollo.cluster", "default"),
    "meta_server_address": get_config("apollo.meta_server_address"),
    "local_config_path": get_config("apollo.local_config_path", "config/application.properties"),
    "namespaces": get_config("apollo.namespaces", ["invres.pub"]),
    "cache_file_dir_path": get_config("apollo.cache_file_dir_path", "./apollo_cache"),
}
class LocalApolloClient:
    def __init__(self):
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        local_config_path = os.path.join(project_root, "config/application.properties")
        self.config = self._load_local_config(local_config_path)
    def _load_local_config(self, file_path: str) -> Dict[str, Any]:
        config = {}
        if not os.path.exists(file_path):
            logger.warning(f"[Apollo] {file_path} 不存在，LocalApolloClient 返回空配置（application.properties 已移除）")
            return config
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f.readlines():
                line = line.strip()
                if line.startswith("data.browsing.agent.config"):
                    config_str = line.split("=", 1)[1].strip().replace("\\n", "")
                    config["data.browsing.agent.config"] = json.loads(config_str)
                    break
        return config
    def get_value(self, key: str, default: Any = None) -> Any:
        return self.config.get(key, default)
if LOCAL_TEST_MODE:
    client = LocalApolloClient()
else:
    client = ApolloClient(
        app_id=APOLLO_CONFIG["app_id"],
        cluster=APOLLO_CONFIG["cluster"],
        meta_server_address=APOLLO_CONFIG["meta_server_address"],
        namespaces=APOLLO_CONFIG["namespaces"],
        cache_file_dir_path=APOLLO_CONFIG["cache_file_dir_path"]
    )


def reset_apollo_config() -> None:
    """重置 Apollo 配置缓存（热重载时调用）。

    重新从 agent_config.json 读取 apollo.* 配置段并重建 client。
    """
    global JASYPT_KEY, LOCAL_TEST_MODE, APOLLO_CONFIG, client
    JASYPT_KEY = get_config("apollo.encrypt_key", "")
    LOCAL_TEST_MODE = get_config("apollo.local_test_mode", True)
    APOLLO_CONFIG = {
        "app_id": get_config("apollo.app_id", "smart-agent-llm-admin"),
        "cluster": get_config("apollo.cluster", "default"),
        "meta_server_address": get_config("apollo.meta_server_address"),
        "local_config_path": get_config("apollo.local_config_path", "config/application.properties"),
        "namespaces": get_config("apollo.namespaces", ["invres.pub"]),
        "cache_file_dir_path": get_config("apollo.cache_file_dir_path", "./apollo_cache"),
    }
    if LOCAL_TEST_MODE:
        client = LocalApolloClient()
    elif ApolloClient is not None:
        client = ApolloClient(
            app_id=APOLLO_CONFIG["app_id"],
            cluster=APOLLO_CONFIG["cluster"],
            meta_server_address=APOLLO_CONFIG["meta_server_address"],
            namespaces=APOLLO_CONFIG["namespaces"],
            cache_file_dir_path=APOLLO_CONFIG["cache_file_dir_path"]
        )
    else:
        client = LocalApolloClient()
    logger.debug("[Apollo] 配置已重置，client 已重建")
def get_all_db_names() -> List[str]:
    config_raw = client.get_value("data.browsing.agent.config")
    if isinstance(config_raw, str):
        config_list: List[Dict[str, Any]] = json.loads(config_raw)
    else:
        config_list = config_raw or []
    if not config_list:
        return []
    db_names = []
    for item in config_list:
        classfy = item.get("classfy", "")
        if classfy:
            db_names.append(classfy)
    return db_names
def get_db_config(db_name: str) -> Dict[str, Any]:
    config_raw = client.get_value("data.browsing.agent.config")
    if isinstance(config_raw, str):
        config_list: List[Dict[str, Any]] = json.loads(config_raw)
    else:
        config_list = config_raw or []
    if not config_list:
        raise ValueError("")
    target_config = None
    for item in config_list:
        classfy = item.get("classfy", "")
        if classfy == db_name:
            target_config = item
            break
    if not target_config:
        raise ValueError(f"数据库配置不存在: {db_name}")
    url = target_config["url"]
    dbtype = target_config.get("dbtype", "").lower()
    if dbtype == "elasticsearch" or dbtype == "es" or dbtype == "elastic":
        url_pattern = re.compile(r"(https?)://([^:]+):(\d+)(?:/(.+))?")
        match = url_pattern.match(url)
        if not match:
            raise ValueError(f"ESURL{url}")
        host = match.group(2)
        port = int(match.group(3))
        database = match.group(4) or db_name
        use_ssl = match.group(1) == "https"
        result = {
            "host": host,
            "port": port,
            "database": database,
            "username": target_config.get("username", ""),
            "pwd": _decrypt_if_encrypted(target_config.get("pwd", "")),
            "dbtype": dbtype,
            "use_ssl": use_ssl,
            "verify_certs": False,
            "index_pattern": database,
        }
        return result
    url_pattern = re.compile(r"jdbc:.+?://([^:]+):(\d+)/.+")
    match = url_pattern.match(url)
    if not match:
        raise ValueError(f"URL{url}")
    host = match.group(1)
    port = int(match.group(2))
    database = url.split("/")[-1] if "/" in url else db_name
    result = {
        "host": host,
        "port": port,
        "database": database,
        "username": target_config.get("username", ""),
        "pwd": _decrypt_if_encrypted(target_config.get("pwd", "")),
        "dbtype": target_config.get("dbtype", ""),
        "schema": target_config.get("schema", "public")
    }
    return result
if __name__ == '__main__':
    try:
        db_name = "ODS_INVRES"
        db_config = get_db_config(db_name)
        print(f"===  {db_name}  ===")
        print(f"{type(db_config)}")
        for key, value in db_config.items():
            print(f"{key}: {value}")
    except Exception as e:
        print(f"{e}")