# rag/rag_system/doc_parser.py
# 文档解析（MinerU API v4）：签名上传→自动解析→轮询→下载 zip→保存 JSON/MD 到 persist_directory
import os
import time
import io
import zipfile
import requests
from loguru import logger


class DocParser:
    """MinerU 文档解析器（在线 API v4，签名上传模式）。

    流程：file-urls/batch(获取签名URL) → PUT 上传文件 → 系统自动解析
          → 轮询 extract-results/batch/{batch_id} → 下载 zip → 解压保存 md+json。
    """

    def __init__(self, base_url: str, api_key: str, timeout: int = 600, poll_interval: int = 5):
        # base_url 是 task 端点（/api/v4/extract/task），推导 api_base（/api/v4）
        self._task_url = base_url
        self._api_base = base_url.replace("/extract/task", "").rstrip("/")
        self._batch_upload_url = f"{self._api_base}/file-urls/batch"
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._timeout = timeout
        self._poll_interval = poll_interval

    def parse(self, file_path: str, persist_dir: str, model_version: str = "vlm",
              filename: str = None) -> dict:
        """解析文档，保存 JSON + MD 到 persist_dir。

        Args:
            filename: 原始文件名（用于保存文件名，None 时用 file_path basename）
        Returns: {md_path, json_path, md_content, json_content}
        """
        filename = filename or os.path.basename(file_path)
        # 1. 获取签名上传 URL（同时提交解析任务）
        batch_id, upload_url = self._get_upload_url(filename, model_version)
        # 2. PUT 上传文件（上传后系统自动开始解析）
        self._upload_file(file_path, filename, upload_url)
        # 3. 轮询批量结果
        result_url = self._poll_batch(batch_id)
        # 4. 下载结果 zip，解压保存 md + json
        return self._download_and_save(result_url, persist_dir, filename)

    def _get_upload_url(self, filename: str, model_version: str) -> tuple:
        """获取签名上传 URL + batch_id。返回 (batch_id, upload_url)。"""
        headers = {**self._headers, "Content-Type": "application/json"}
        resp = requests.post(
            self._batch_upload_url, headers=headers,
            json={
                "files": [{"name": filename, "data_id": filename}],
                "model_version": model_version,
            },
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json().get("data", {})
        batch_id = data.get("batch_id")
        file_urls = data.get("file_urls", [])
        if not batch_id or not file_urls:
            raise RuntimeError(f"[DocParser] 获取上传URL失败: {resp.json()}")
        logger.info(f"[DocParser] batch_id={batch_id}, upload URL acquired")
        return batch_id, file_urls[0]

    def _upload_file(self, file_path: str, filename: str, upload_url: str):
        """PUT 上传文件到签名 URL。"""
        with open(file_path, "rb") as f:
            put_resp = requests.put(upload_url, data=f, timeout=120)
        if put_resp.status_code not in (200, 201):
            raise RuntimeError(f"[DocParser] 上传失败 {put_resp.status_code}: {put_resp.text[:200]}")
        logger.info(f"[DocParser] uploaded {filename}")

    def _poll_batch(self, batch_id: str) -> str:
        """轮询批量任务结果。返回结果 zip URL。"""
        poll_url = f"{self._api_base}/extract-results/batch/{batch_id}"
        start = time.time()
        while time.time() - start < self._timeout:
            resp = requests.get(poll_url, headers=self._headers, timeout=30)
            resp.raise_for_status()
            data = resp.json().get("data", {})
            results = data.get("extract_result", [])
            if results:
                r = results[0]
                state = r.get("state", "")
                elapsed = int(time.time() - start)
                if state == "done":
                    result_url = r.get("full_zip_url") or r.get("full_result_url")
                    if not result_url:
                        raise RuntimeError(f"[DocParser] done 但无结果URL: {r}")
                    logger.info(f"[DocParser] done {elapsed}s → {result_url[:60]}...")
                    return result_url
                elif state == "failed":
                    raise RuntimeError(f"[DocParser] 解析失败: {r.get('err_msg', '未知')}")
                else:
                    logger.info(f"[DocParser] poll {elapsed}s state={state}")
            time.sleep(self._poll_interval)
        raise TimeoutError(f"[DocParser] 轮询超时 {self._timeout}s")

    def _download_and_save(self, result_url: str, persist_dir: str, filename: str) -> dict:
        """下载结果 zip，解压保存 md + json 到 persist_dir。"""
        resp = requests.get(result_url, timeout=120)
        resp.raise_for_status()
        os.makedirs(persist_dir, exist_ok=True)
        stem = os.path.splitext(filename)[0]
        saved = {"md_path": None, "json_path": None, "md_content": "", "json_content": ""}
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            for name in zf.namelist():
                content = zf.read(name)
                lower = name.lower()
                # 保存第一个 .md 和第一个 .json（MinerU zip 含 full.md + layout.json 等）
                if lower.endswith(".md") and not saved["md_path"]:
                    md_path = os.path.join(persist_dir, f"{stem}.md")
                    with open(md_path, "wb") as f:
                        f.write(content)
                    saved["md_path"] = md_path
                    saved["md_content"] = content.decode("utf-8", errors="replace")
                elif lower.endswith(".json") and not saved["json_path"]:
                    json_path = os.path.join(persist_dir, f"{stem}.json")
                    with open(json_path, "wb") as f:
                        f.write(content)
                    saved["json_path"] = json_path
                    saved["json_content"] = content.decode("utf-8", errors="replace")
        logger.info(f"[DocParser] saved md={saved['md_path']} json={saved['json_path']}")
        return saved
