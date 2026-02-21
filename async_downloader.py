# async_downloader.py
# Main script for asynchronous file downloading

import asyncio
import aiohttp
import os
import logging
import json
from datetime import datetime
from urllib.parse import urlparse, unquote
import argparse
from tqdm import tqdm
import uuid
from typing import Tuple
import threading


def sanitize_filename(name: str) -> str:
    """Sanitize a filename: strip directories, unquote, replace separators, and fallback to uuid."""
    if not name:
        return f"download_{uuid.uuid4().hex[:8]}"
    # unquote URL-encoded names
    name = unquote(name)
    # take basename to remove any directories
    name = os.path.basename(name)
    # replace any path separators with underscore
    name = name.replace(os.path.sep, "_")
    if os.path.altsep:
        name = name.replace(os.path.altsep, "_")
    # remove any remaining suspicious parts
    name = name.strip().strip('. ')
    if not name:
        return f"download_{uuid.uuid4().hex[:8]}"
    return name
import logging
import json
from datetime import datetime

# structured logger
logger = logging.getLogger("async_downloader")
if not logger.handlers:
    handler = logging.StreamHandler()
    logger.addHandler(handler)
logger.setLevel(logging.INFO)


def struct_log(level: str, message: str, **extra):
    payload = {"ts": datetime.utcnow().isoformat() + "Z", "level": level, "message": message}
    payload.update(extra)
    line = json.dumps(payload, ensure_ascii=False)
    if level == "info":
        logger.info(line)
    elif level == "warning":
        logger.warning(line)
    elif level == "error":
        logger.error(line)
    else:
        logger.debug(line)


# Optional remote log sender (runs a background thread with an asyncio loop)
class _LogSender:
    def __init__(self, url: str):
        self.url = url
        self._thread = None
        self._loop = None
        self._queue = None
        self._stopping = False
        self._spool_path = os.path.abspath(".log_spool.jsonl")

    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._run_loop, daemon=True)
            self._thread.start()

    def _run_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._queue = asyncio.Queue()
        try:
            self._loop.run_until_complete(self._consumer())
        finally:
            self._loop.close()

    async def _consumer(self):
        async with aiohttp.ClientSession() as session:
            while True:
                # first, try to send persisted spool entries
                if os.path.exists(self._spool_path):
                    try:
                        with open(self._spool_path, 'r', encoding='utf-8') as f:
                            lines = [l.strip() for l in f if l.strip()]
                    except Exception:
                        lines = []
                    remaining = []
                    for line in lines:
                        try:
                            payload = json.loads(line)
                        except Exception:
                            continue
                        sent = False
                        for attempt in range(3):
                            try:
                                await session.post(self.url, json=payload, timeout=5)
                                sent = True
                                break
                            except Exception:
                                await asyncio.sleep(0.5 * (2 ** attempt))
                        if not sent:
                            remaining.append(line)
                    # rewrite spool with remaining
                    try:
                        if remaining:
                            with open(self._spool_path + '.tmp', 'w', encoding='utf-8') as f:
                                f.write('\n'.join(remaining) + '\n')
                            os.replace(self._spool_path + '.tmp', self._spool_path)
                        else:
                            os.remove(self._spool_path)
                    except Exception:
                        pass

                msg = await self._queue.get()
                if msg is None:
                    break
                try:
                    await session.post(self.url, json=msg, timeout=5)
                except Exception:
                    # persist to spool on failure
                    try:
                        with open(self._spool_path, 'a', encoding='utf-8') as f:
                            f.write(json.dumps(msg, ensure_ascii=False) + '\n')
                    except Exception:
                        pass

    def enqueue(self, payload: dict):
        if self._loop is None or self._queue is None:
            return
        asyncio.run_coroutine_threadsafe(self._queue.put(payload), self._loop)

    def stop(self):
        if self._loop and self._queue:
            asyncio.run_coroutine_threadsafe(self._queue.put(None), self._loop)
        if self._thread:
            self._thread.join(timeout=1)


# global logging config
_LOG_SENDER = None

def configure_logging(level: str = "info", log_file: str = None, remote_url: str = None):
    global _LOG_SENDER
    lvl = logging.INFO
    if level:
        level = level.lower()
        if level == 'debug':
            lvl = logging.DEBUG
        elif level == 'warning':
            lvl = logging.WARNING
        elif level == 'error':
            lvl = logging.ERROR
        else:
            lvl = logging.INFO
    logger.setLevel(lvl)

    # file handler
    if log_file:
        fh = logging.FileHandler(log_file)
        fh.setLevel(lvl)
        logger.addHandler(fh)

    # remote sender
    if remote_url:
        try:
            _LOG_SENDER = _LogSender(remote_url)
            _LOG_SENDER.start()
        except Exception:
            struct_log('warning', 'log_sender_failed', url=remote_url)

DEFAULT_DOWNLOAD_DIR = "downloads"
download_dir_global = DEFAULT_DOWNLOAD_DIR
# Hosts that should always be treated as non-downloadable (domain suffixes)
DEFAULT_BLOCKLIST = ["google.com", "youtube.com", "facebook.com"]

async def download_file(session, url, filename=None, chunk_size=8192, progress_callback=None, max_retries=3, backoff_base=0.5):
    """Download a single file asynchronously with optional progress callback.

    If `progress_callback` is provided it will be called as:
        progress_callback(filename, downloaded_bytes, total_bytes)
    """
    if filename is None:
        filename = os.path.basename(url) or f"download_{uuid.uuid4().hex[:8]}"

    filename = sanitize_filename(filename)
    download_dir = download_dir_global if 'download_dir_global' in globals() else DEFAULT_DOWNLOAD_DIR
    os.makedirs(download_dir, exist_ok=True)
    filepath = os.path.join(download_dir, filename)
    # ensure filepath is inside download_dir
    if os.path.commonpath([os.path.abspath(download_dir)]) != os.path.commonpath([os.path.abspath(download_dir), os.path.abspath(filepath)]):
        # fallback to safe name
        filename = f"download_{uuid.uuid4().hex[:8]}"
        filepath = os.path.join(download_dir, filename)
    
    import random
    attempt = 0
    while True:
        try:
            struct_log("info", "download_attempt", url=url, filename=filename, attempt=attempt)
            # Check for existing partial file for resume
            mode = 'wb'
            local_size = 0
            if os.path.exists(filepath):
                local_size = os.path.getsize(filepath)

            headers = {}
            if local_size > 0:
                # ask for remaining bytes
                headers['Range'] = f'bytes={local_size}-'
                mode = 'ab'

            async with session.get(url, headers=headers) as response:
                # If server responds with 200 to a Range request, it ignored Range -> restart
                if response.status >= 400:
                    struct_log("warning", "http_error", url=url, status=response.status)
                    raise aiohttp.ClientResponseError(response.request_info, response.history, status=response.status)

                if local_size > 0 and response.status == 200:
                    # server ignored Range; restart download
                    struct_log("info", "range_ignored_restart", url=url, filename=filename)
                    mode = 'wb'
                    local_size = 0

                total_size = None
                content_length = response.headers.get('content-length')
                if content_length is not None:
                    try:
                        total_size = int(content_length) + (0 if mode == 'wb' else local_size)
                    except Exception:
                        total_size = None

                downloaded = local_size

                if progress_callback is None:
                    # use tqdm for CLI
                    with open(filepath, mode) as f, tqdm(
                        desc=filename,
                        total=total_size,
                        unit='B',
                        unit_scale=True,
                        unit_divisor=1024,
                        initial=local_size
                    ) as pbar:
                        async for chunk in response.content.iter_chunked(chunk_size):
                            f.write(chunk)
                            downloaded += len(chunk)
                            pbar.update(len(chunk))
                else:
                    with open(filepath, mode) as f:
                        async for chunk in response.content.iter_chunked(chunk_size):
                            f.write(chunk)
                            downloaded += len(chunk)
                            try:
                                progress_callback(filename, downloaded, total_size or 0)
                            except Exception:
                                pass

            struct_log("info", "download_completed", url=url, filename=filename, bytes=downloaded)
            return filepath

        except Exception as e:
            attempt += 1
            struct_log("error", "download_error", url=url, filename=filename, attempt=attempt, error=str(e))
            # on final failure, clean up partial file if it was a fresh download
            if attempt > max_retries:
                struct_log("error", "download_failed", url=url, filename=filename, attempts=attempt)
                # Do not remove partial file if resuming; keep partial for debugging
                raise e

            # exponential backoff with jitter
            sleep_for = backoff_base * (2 ** (attempt - 1))
            sleep_for = sleep_for * (0.8 + random.random() * 0.4)
            struct_log("info", "retry_sleep", url=url, filename=filename, sleep=round(sleep_for, 2))
            await asyncio.sleep(sleep_for)
            continue


async def is_url_downloadable(url: str, session: aiohttp.ClientSession = None, timeout: int = 10) -> Tuple[bool, str]:
    """Check whether a URL is likely downloadable.

    Returns (True, reason) if downloadable, otherwise (False, reason).
    Strategy:
    - Try a HEAD request first. If it returns useful headers (content-length or
      content-disposition) and a non-HTML content-type, consider it downloadable.
    - If HEAD is not allowed (405) or returns ambiguous results, fall back to a
      GET request for the first byte using a Range header to probe the resource.
    """
    # Quick host-based blocklist check
    try:
        host = urlparse(url).hostname or ""
    except Exception:
        host = ""
    host = host.lower()
    for blocked in DEFAULT_BLOCKLIST:
        if host.endswith(blocked):
            return False, f"Blocked host: {host}"

    own_session = False
    if session is None:
        session = aiohttp.ClientSession()
        own_session = True

    try:
        try:
            async with session.head(url, timeout=timeout, allow_redirects=True) as resp:
                status = resp.status
                if status >= 400:
                    struct_log("warning", "head_status", url=url, status=status)
                    return False, f"HEAD returned status {status}"

                ctype = resp.headers.get("content-type", "").lower()
                cdisp = resp.headers.get("content-disposition")
                clen = resp.headers.get("content-length")

                if cdisp or clen:
                    struct_log("info", "head_has_length_or_content_disp", url=url)
                    return True, "Has Content-Length or Content-Disposition"

                # If content-type exists and is not HTML, assume downloadable
                if ctype and "text/html" not in ctype:
                    struct_log("info", "head_content_type_non_html", url=url, content_type=ctype)
                    return True, f"Content-Type: {ctype}"

                # ambiguous: fall through to GET probe
        except aiohttp.ClientResponseError as e:
            # HEAD may be disallowed; fall back to GET probe
            pass
        except Exception:
            # Any other failure on HEAD -> try GET probe
            pass

        # Probe with a ranged GET for one byte
        headers = {"Range": "bytes=0-0"}
        async with session.get(url, headers=headers, timeout=timeout, allow_redirects=True) as resp:
            status = resp.status
            if status >= 400:
                struct_log("warning", "get_probe_status", url=url, status=status)
                return False, f"GET probe returned status {status}"

            ctype = resp.headers.get("content-type", "").lower()
            cdisp = resp.headers.get("content-disposition")
            if cdisp:
                struct_log("info", "get_has_content_disp", url=url)
                return True, "Has Content-Disposition"
            if ctype and "text/html" not in ctype:
                struct_log("info", "get_content_type_non_html", url=url, content_type=ctype)
                return True, f"Content-Type: {ctype}"

            # If we got HTML it's likely a page rather than a direct file
            struct_log("info", "likely_html", url=url, content_type=ctype)
            return False, f"Likely HTML (Content-Type: {ctype})"
    finally:
        if own_session:
            await session.close()


async def check_urls(urls, timeout: int = 10):
    """Async helper used by the CLI to check a list of URLs."""
    async with aiohttp.ClientSession() as session:
        results = []
        for url in urls:
            ok, reason = await is_url_downloadable(url, session=session, timeout=timeout)
            struct_log("info", "check_result", url=url, ok=ok, reason=reason)
            results.append((url, ok, reason))
        return results

async def download_multiple_files(urls, max_concurrent=5, chunk_size=8192, download_dir=None, progress_callback=None, status_callback=None, max_retries=3, backoff_base=0.5):
    """Download multiple files concurrently with optional callbacks.

    - progress_callback(filename, downloaded_bytes, total_bytes)
    - status_callback(filename, status, info) where status is 'completed' or 'failed' and info is filepath or error message
    """
    global download_dir_global
    download_dir_global = download_dir or DEFAULT_DOWNLOAD_DIR
    os.makedirs(download_dir_global, exist_ok=True)
    
    semaphore = asyncio.Semaphore(max_concurrent)
    
    async def download_with_semaphore(url):
        async with semaphore:
            filename = os.path.basename(url) or f"download_{uuid.uuid4().hex[:8]}"
            try:
                filepath = await download_file(session, url, filename, chunk_size, progress_callback, max_retries=max_retries, backoff_base=backoff_base)
                if status_callback:
                    try:
                        status_callback(filename, 'completed', filepath)
                    except Exception:
                        pass
                return filepath
            except Exception as e:
                if status_callback:
                    try:
                        status_callback(filename, 'failed', str(e))
                    except Exception:
                        pass
                return e
    
    async with aiohttp.ClientSession() as session:
        tasks = [download_with_semaphore(url) for url in urls]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        successful = 0
        failed = 0
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                print(f"Error downloading {urls[i]}: {result}")
                failed += 1
            else:
                print(f"Downloaded: {result}")
                successful += 1
        
        print(f"\nSummary: {successful} successful, {failed} failed downloads.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Asynchronous file downloader")
    parser.add_argument("urls", nargs="+", help="URLs to download")
    parser.add_argument("--max-concurrent", type=int, default=5, help="Maximum concurrent downloads (default: 5)")
    parser.add_argument("--chunk-size", type=int, default=8192, help="Chunk size in bytes (default: 8192)")
    parser.add_argument("--download-dir", default="downloads", help="Download directory (default: downloads)")
    parser.add_argument("--check-only", action="store_true", help="Only check whether URLs are downloadable and do not download")
    parser.add_argument("--check-timeout", type=int, default=10, help="Timeout seconds for URL checks (default: 10)")
    parser.add_argument("--max-retries", type=int, default=3, help="Maximum retries for downloads (default: 3)")
    parser.add_argument("--backoff-base", type=float, default=0.5, help="Base backoff seconds (default: 0.5)")
    parser.add_argument("--log-level", type=str, default="info", help="Log level: debug|info|warning|error")
    parser.add_argument("--log-file", type=str, default=None, help="Path to write structured logs (append)")
    parser.add_argument("--log-remote", type=str, default=None, help="Remote HTTP endpoint to POST structured logs")

    args = parser.parse_args()

    # configure logging according to CLI
    configure_logging(level=args.log_level if hasattr(args, 'log_level') else 'info', log_file=getattr(args, 'log_file', None), remote_url=getattr(args, 'log_remote', None))

    if args.check_only:
        results = asyncio.run(check_urls(args.urls, timeout=args.check_timeout))
        for url, ok, reason in results:
            status = "DOWNLOADABLE" if ok else "NOT DOWNLOADABLE"
            print(f"{url}\t{status}\t{reason}")
    else:
        asyncio.run(download_multiple_files(args.urls, args.max_concurrent, args.chunk_size, download_dir=args.download_dir, max_retries=args.max_retries, backoff_base=args.backoff_base))