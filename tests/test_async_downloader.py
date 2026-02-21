import asyncio
import http.server
import socketserver
import threading
import functools
import os

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

    httpd, _thread, port = run_http_server(str(serve_dir))
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

    httpd, _thread, port = run_http_server(str(serve_dir))
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


def run_custom_server(handler_class):
    httpd = socketserver.TCPServer(("127.0.0.1", 0), handler_class)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, thread, port


def test_no_content_length(tmp_path):
    # Handler that serves response without Content-Length header
    class NoLengthHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain')
            # deliberately do not send Content-Length
            self.end_headers()
            self.wfile.write(b'hello-without-length')

        def log_message(self, format, *args):
            return

    httpd, thread, port = run_custom_server(NoLengthHandler)
    try:
        url = f"http://127.0.0.1:{port}/file"
        download_dir = tmp_path / "dl_no_len"
        download_dir.mkdir()

        asyncio.run(download_multiple_files([url], max_concurrent=1, chunk_size=8, download_dir=str(download_dir)))

        downloaded = download_dir / "file"
        assert downloaded.exists()
        assert downloaded.read_text() == "hello-without-length"
    finally:
        stop_http_server(httpd)


def test_redirect_handling(tmp_path):
    # Handler that redirects /redir to /final
    class RedirectHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == '/redir':
                self.send_response(302)
                self.send_header('Location', '/final')
                self.end_headers()
            elif self.path == '/final':
                self.send_response(200)
                self.send_header('Content-Type', 'text/plain')
                self.send_header('Content-Length', '5')
                self.end_headers()
                self.wfile.write(b'OKAY!')
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, format, *args):
            return

    httpd, thread, port = run_custom_server(RedirectHandler)
    try:
        url = f"http://127.0.0.1:{port}/redir"
        download_dir = tmp_path / "dl_redir"
        download_dir.mkdir()

        asyncio.run(download_multiple_files([url], max_concurrent=1, chunk_size=16, download_dir=str(download_dir)))

        downloaded = download_dir / "redir"
        # The downloader uses os.path.basename(url) -> 'redir' expected
        assert downloaded.exists()
        assert downloaded.read_text() == 'OKAY!'
    finally:
        stop_http_server(httpd)


def test_range_resume(tmp_path):
    content = b'0123456789'

    class RangeHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            # support Range header
            rng = self.headers.get('Range')
            if rng:
                # parse bytes=START-
                try:
                    _, part = rng.split('=')
                    start = int(part.split('-')[0])
                except Exception:
                    start = 0
                data = content[start:]
                self.send_response(206)
                self.send_header('Content-Type', 'application/octet-stream')
                self.send_header('Content-Range', f'bytes {start}-{len(content)-1}/{len(content)}')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            else:
                self.send_response(200)
                self.send_header('Content-Type', 'application/octet-stream')
                self.send_header('Content-Length', str(len(content)))
                self.end_headers()
                self.wfile.write(content)

        def log_message(self, format, *args):
            return

    httpd, thread, port = run_custom_server(RangeHandler)
    try:
        url = f"http://127.0.0.1:{port}/big"
        download_dir = tmp_path / "dl_range"
        download_dir.mkdir()

        # create partial file with first 4 bytes
        partial = download_dir / 'big'
        partial.write_bytes(content[:4])

        asyncio.run(download_multiple_files([url], max_concurrent=1, chunk_size=4, download_dir=str(download_dir)))

        downloaded = download_dir / 'big'
        assert downloaded.exists()
        assert downloaded.read_bytes() == content
    finally:
        stop_http_server(httpd)


    def test_retry_backoff(tmp_path):
        # server that fails first two attempts then succeeds
        state = {'count': 0}

        class FlakyHandler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                state['count'] += 1
                if state['count'] <= 2:
                    self.send_response(500)
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header('Content-Type', 'text/plain')
                self.send_header('Content-Length', '7')
                self.end_headers()
                self.wfile.write(b'SUCCESS')

            def log_message(self, format, *args):
                return

        httpd, thread, port = run_custom_server(FlakyHandler)
        try:
            url = f"http://127.0.0.1:{port}/flaky"
            download_dir = tmp_path / "dl_flaky"
            download_dir.mkdir()

            # set max_retries >=2 so it eventually succeeds
            asyncio.run(download_multiple_files([url], max_concurrent=1, chunk_size=4, download_dir=str(download_dir), max_retries=3, backoff_base=0.1))

            downloaded = download_dir / "flaky"
            assert downloaded.exists()
            assert downloaded.read_text() == 'SUCCESS'
        finally:
            stop_http_server(httpd)


    def test_filename_sanitization(tmp_path):
        # serve a file with dangerous name
        serve_dir = tmp_path / "serve_name"
        serve_dir.mkdir()
        f = serve_dir / "file.txt"
        f.write_text("data")

        httpd, thread, port = run_http_server(str(serve_dir))
        try:
            # craft URL with path traversal
            url = f"http://127.0.0.1:{port}/../../etc/passwd"
            download_dir = tmp_path / "downloads_name"
            download_dir.mkdir()

            asyncio.run(download_multiple_files([url], max_concurrent=1, chunk_size=1024, download_dir=str(download_dir)))

            # ensure file written inside download_dir and filename sanitized
            files = list(download_dir.iterdir())
            assert len(files) == 1
            assert files[0].parent == download_dir
        finally:
            stop_http_server(httpd)
