import asyncio
import http.server
import socketserver
import threading
import functools
import tempfile
import os
from pathlib import Path

# Ensure project root is on sys.path so tests can import the module
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from async_downloader import download_multiple_files


def run_http_server(directory):
    Handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=directory)
    httpd = socketserver.TCPServer(("127.0.0.1", 0), Handler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, thread, port


def stop_http_server(httpd):
    try:
        httpd.shutdown()
        httpd.server_close()
    except Exception:
        pass


def test_download_single_file(tmp_path):
    serve_dir = tmp_path / "serve"
    serve_dir.mkdir()
    f = serve_dir / "hello.txt"
    f.write_text("hello world")

    httpd, thread, port = run_http_server(str(serve_dir))
    try:
        url = f"http://127.0.0.1:{port}/hello.txt"
        download_dir = tmp_path / "downloads"
        download_dir.mkdir()

        asyncio.run(download_multiple_files([url], max_concurrent=1, chunk_size=1024, download_dir=str(download_dir)))

        downloaded = download_dir / "hello.txt"
        assert downloaded.exists()
        assert downloaded.read_text() == "hello world"
    finally:
        stop_http_server(httpd)


def test_multiple_with_failure(tmp_path):
    serve_dir = tmp_path / "serve2"
    serve_dir.mkdir()
    (serve_dir / "a.txt").write_text("A")

    httpd, thread, port = run_http_server(str(serve_dir))
    try:
        valid = f"http://127.0.0.1:{port}/a.txt"
        bad = f"http://127.0.0.1:{port}/notfound.txt"
        download_dir = tmp_path / "downloads2"
        download_dir.mkdir()

        asyncio.run(download_multiple_files([valid, bad], max_concurrent=2, chunk_size=512, download_dir=str(download_dir)))

        assert (download_dir / "a.txt").exists()
        assert not (download_dir / "notfound.txt").exists()
    finally:
        stop_http_server(httpd)
