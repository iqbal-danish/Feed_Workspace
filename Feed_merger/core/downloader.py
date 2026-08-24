"""Streaming download helpers for remote XML and SFTP feeds."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import ssl
from pathlib import Path
from urllib.parse import urlparse

import aiohttp

from config import MergerConfig

logger = logging.getLogger(__name__)


class DownloadError(RuntimeError):
    """Raised when a feed cannot be downloaded after retries."""


class FeedDownloader:
    """Download remote feeds (HTTP/HTTPS/SFTP) to disk with persistent connection pooling."""

    def __init__(self, config: MergerConfig) -> None:
        self.config = config
        self._session: aiohttp.ClientSession | None = None

    async def __aenter__(self) -> "FeedDownloader":
        await self.get_session()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def get_session(self) -> aiohttp.ClientSession:
        """Get or initialize the shared persistent aiohttp ClientSession."""
        if self._session is None or self._session.closed:
            # Configure high-performance connector with SSL fallback
            ssl_ctx = ssl.create_default_context()
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = ssl.CERT_NONE

            connector = aiohttp.TCPConnector(
                limit=100,
                limit_per_host=20,
                ttl_dns_cache=600,
                ssl=ssl_ctx,
            )
            timeout = aiohttp.ClientTimeout(
                total=self.config.timeout_seconds,
                connect=15,
                sock_read=self.config.timeout_seconds,
            )
            self._session = aiohttp.ClientSession(
                connector=connector,
                timeout=timeout,
                headers=self.config.request_headers,
                auto_decompress=False,
            )
        return self._session

    async def close(self) -> None:
        """Close the persistent session and release connector resources."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def download(self, source_cfg: dict, session: aiohttp.ClientSession | None = None) -> Path:
        """Stream a remote source into a temporary file and return its path."""
        self.config.temp_dir.mkdir(parents=True, exist_ok=True)

        src_type = source_cfg.get("type", "url")
        if src_type == "url":
            return await self._download_http(source_cfg.get("url", ""), {}, src_type, session)
        elif src_type == "secure_api":
            headers = await self._build_api_headers(source_cfg)
            return await self._download_http(source_cfg.get("url", ""), headers, src_type, session)
        elif src_type == "sftp":
            return await self._download_sftp_with_retry(source_cfg)
        else:
            raise ValueError(f"Unsupported feed download source type: {src_type}")

    async def _build_api_headers(self, source_cfg: dict) -> dict[str, str]:
        headers = {}
        auth_type = source_cfg.get("auth_type", "none")

        if auth_type == "bearer":
            token = source_cfg.get("auth_token", "")
            if token:
                headers["Authorization"] = f"Bearer {token}"
        elif auth_type == "api_key":
            key_header = source_cfg.get("api_key_header", "X-API-Key")
            key_val = source_cfg.get("api_key_value", "")
            if key_header and key_val:
                headers[key_header] = key_val
        elif auth_type == "oauth2":
            token_url = source_cfg.get("oauth2_token_url", "")
            client_id = source_cfg.get("oauth2_client_id", "")
            client_secret = source_cfg.get("oauth2_client_secret", "")
            if token_url and client_id and client_secret:
                try:
                    logger.info("Retrieving OAuth2 Access Token from: %s", token_url)
                    token = await self._fetch_oauth2_token(token_url, client_id, client_secret)
                    headers["Authorization"] = f"Bearer {token}"
                except Exception as exc:
                    logger.error("Failed to retrieve OAuth2 token: %s", exc)
                    raise exc
        return headers

    async def _fetch_oauth2_token(self, token_url: str, client_id: str, client_secret: str) -> str:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            payload = {
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
            }
            async with session.post(token_url, data=payload) as resp:
                resp.raise_for_status()
                data = await resp.json()
                return data["access_token"]

    async def _download_http(
        self,
        url: str,
        extra_headers: dict[str, str],
        type_name: str,
        session: aiohttp.ClientSession | None = None,
    ) -> Path:
        target = self._target_path(type_name, url)
        last_error: Exception | None = None
        sess = session or await self.get_session()
        headers = {**self.config.request_headers, **extra_headers}

        for attempt in range(1, self.config.retry_count + 1):
            partial = target.with_suffix(f"{target.suffix}.part{attempt}")
            try:
                async with sess.get(url, headers=headers, allow_redirects=True) as response:
                    if response.status >= 400:
                        raise aiohttp.ClientResponseError(
                            request_info=response.request_info,
                            history=response.history,
                            status=response.status,
                            message=f"HTTP {response.status} {response.reason}",
                        )

                    bytes_written = 0
                    with partial.open("wb") as file:
                        async for chunk in response.content.iter_chunked(self.config.chunk_size):
                            if not chunk:
                                continue
                            file.write(chunk)
                            bytes_written += len(chunk)

                # Rename partial file to final target with retry for Windows file locks
                for rename_attempt in range(15):
                    try:
                        os.replace(partial, target)
                        break
                    except OSError as rename_err:
                        if rename_attempt == 14:
                            raise rename_err
                        await asyncio.sleep(0.1)

                logger.info(
                    "Download completed: %s -> %s (%s bytes)",
                    url,
                    target.name,
                    bytes_written,
                )
                return target
            except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as exc:
                last_error = exc
                try:
                    partial.unlink(missing_ok=True)
                except Exception:
                    pass
                logger.warning(
                    "Download attempt %s/%s failed for %s: %s",
                    attempt,
                    self.config.retry_count,
                    url,
                    exc,
                )
                if attempt < self.config.retry_count:
                    await asyncio.sleep(min(1.5 ** attempt, 5))

        raise DownloadError(f"Failed to download {url}: {last_error}") from last_error

    async def _download_sftp_with_retry(self, source_cfg: dict) -> Path:
        host = source_cfg.get("host")
        remote_path = source_cfg.get("remote_path")
        target = self._target_path("sftp", f"{host}:{remote_path}")
        last_error: Exception | None = None

        for attempt in range(1, self.config.retry_count + 1):
            partial = target.with_suffix(f"{target.suffix}.part{attempt}")
            try:
                logger.info("SFTP Download started: sftp://%s%s", host, remote_path)

                loop = asyncio.get_running_loop()
                bytes_written = await loop.run_in_executor(
                    None, self._download_sftp_sync, source_cfg, partial
                )

                # Retry rename on Windows to handle antivirus/indexing locks
                for rename_attempt in range(15):
                    try:
                        os.replace(partial, target)
                        break
                    except OSError as rename_err:
                        if rename_attempt == 14:
                            raise rename_err
                        await asyncio.sleep(0.1)

                logger.info(
                    "SFTP Download completed: sftp://%s%s -> %s (%s bytes)",
                    host,
                    remote_path,
                    target.name,
                    bytes_written,
                )
                return target
            except Exception as exc:
                last_error = exc
                try:
                    partial.unlink(missing_ok=True)
                except Exception:
                    pass
                logger.warning(
                    "SFTP Download attempt %s/%s failed for sftp://%s%s: %s",
                    attempt,
                    self.config.retry_count,
                    host,
                    remote_path,
                    exc,
                )
                if attempt < self.config.retry_count:
                    await asyncio.sleep(min(1.5 ** attempt, 5))

        raise DownloadError(f"Failed to download from SFTP sftp://{host}{remote_path}: {last_error}") from last_error

    def _download_sftp_sync(self, source_cfg: dict, partial_path: Path) -> int:
        import paramiko

        host = source_cfg.get("host")
        port = int(source_cfg.get("port", 22))
        username = source_cfg.get("username")
        password = source_cfg.get("password")
        remote_path = source_cfg.get("remote_path")

        transport = paramiko.Transport((host, port))
        transport.connect(username=username, password=password)

        sftp = paramiko.SFTPClient.from_transport(transport)
        bytes_written = 0

        try:
            with sftp.file(remote_path, "rb") as remote_file:
                with partial_path.open("wb") as local_file:
                    while True:
                        chunk = remote_file.read(self.config.chunk_size)
                        if not chunk:
                            break
                        local_file.write(chunk)
                        bytes_written += len(chunk)
            return bytes_written
        finally:
            sftp.close()
            transport.close()

    def _target_path(self, type_name: str, key_str: str) -> Path:
        parsed = urlparse(key_str)
        path_str = parsed.path if type_name != "sftp" else key_str
        suffixes = "".join(Path(path_str).suffixes)
        suffix = suffixes if suffixes.lower().endswith((".xml", ".xml.gz", ".gz", ".json", ".jsonl")) else ".xml"
        digest = hashlib.sha256(f"{type_name}:{key_str}".encode("utf-8")).hexdigest()[:16]
        return self.config.temp_dir / f"{digest}{suffix}"
