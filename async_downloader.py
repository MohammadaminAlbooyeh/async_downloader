# async_downloader.py
# Main script for asynchronous file downloading

import asyncio
import aiohttp
import os
import argparse
from tqdm import tqdm
import uuid

DOWNLOAD_DIR = "downloads"

async def download_file(session, url, filename=None, chunk_size=8192):
    """Download a single file asynchronously with progress tracking."""
    if filename is None:
        filename = os.path.basename(url) or f"download_{uuid.uuid4().hex[:8]}"
    
    filepath = os.path.join(DOWNLOAD_DIR, filename)
    
    try:
        async with session.get(url) as response:
            response.raise_for_status()
            total_size = int(response.headers.get('content-length', 0))
            
            with open(filepath, 'wb') as f, tqdm(
                desc=filename,
                total=total_size,
                unit='B',
                unit_scale=True,
                unit_divisor=1024,
            ) as pbar:
                downloaded = 0
                async for chunk in response.content.iter_chunked(chunk_size):
                    f.write(chunk)
                    downloaded += len(chunk)
                    pbar.update(len(chunk))
        
        return filepath
    except Exception as e:
        # Clean up partial file on error
        if os.path.exists(filepath):
            os.remove(filepath)
        raise e

async def download_multiple_files(urls, max_concurrent=5, chunk_size=8192):
    """Download multiple files concurrently."""
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    
    semaphore = asyncio.Semaphore(max_concurrent)
    
    async def download_with_semaphore(url):
        async with semaphore:
            filename = os.path.basename(url) or f"download_{uuid.uuid4().hex[:8]}"
            return await download_file(session, url, filename, chunk_size)
    
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