# async_downloader.py
# Main script for asynchronous file downloading

import asyncio
import aiohttp
import os
import argparse
from tqdm import tqdm
import uuid

DEFAULT_DOWNLOAD_DIR = "downloads"

async def download_file(session, url, filename=None, chunk_size=8192, progress_callback=None):
    """Download a single file asynchronously with optional progress callback.

    If `progress_callback` is provided it will be called as:
        progress_callback(filename, downloaded_bytes, total_bytes)
    """
    if filename is None:
        filename = os.path.basename(url) or f"download_{uuid.uuid4().hex[:8]}"
    
    filepath = os.path.join(download_dir_global, filename) if 'download_dir_global' in globals() else os.path.join(DEFAULT_DOWNLOAD_DIR, filename)
    
    try:
        async with session.get(url) as response:
            response.raise_for_status()
            total_size = int(response.headers.get('content-length', 0) or 0)
            
            downloaded = 0
            # If a progress callback is provided, use it; otherwise use tqdm for CLI feedback
            if progress_callback is None:
                with open(filepath, 'wb') as f, tqdm(
                    desc=filename,
                    total=total_size,
                    unit='B',
                    unit_scale=True,
                    unit_divisor=1024,
                ) as pbar:
                    async for chunk in response.content.iter_chunked(chunk_size):
                        f.write(chunk)
                        downloaded += len(chunk)
                        pbar.update(len(chunk))
            else:
                with open(filepath, 'wb') as f:
                    async for chunk in response.content.iter_chunked(chunk_size):
                        f.write(chunk)
                        downloaded += len(chunk)
                        try:
                            progress_callback(filename, downloaded, total_size)
                        except Exception:
                            # swallow progress callback errors
                            pass
        
        return filepath
    except Exception as e:
        # Clean up partial file on error
        if os.path.exists(filepath):
            os.remove(filepath)
        raise e

async def download_multiple_files(urls, max_concurrent=5, chunk_size=8192, download_dir=None, progress_callback=None, status_callback=None):
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
                filepath = await download_file(session, url, filename, chunk_size, progress_callback)
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
    
    args = parser.parse_args()
    DOWNLOAD_DIR = args.download_dir
    
    asyncio.run(download_multiple_files(args.urls, args.max_concurrent, args.chunk_size))