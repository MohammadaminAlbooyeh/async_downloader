import streamlit as st
import threading
import queue
import time
import os
import asyncio
from async_downloader import download_multiple_files, is_url_downloadable, configure_logging

st.set_page_config(page_title="Async Downloader", layout="wide")

st.markdown(
    """
    <style>
    .big-title {font-size:28px; font-weight:700;}
    .muted {color:#6c757d}
    .small {font-size:12px; color:#6c757d}
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown('<div class="big-title">Async Downloader 🌐</div>', unsafe_allow_html=True)
st.markdown('<div class="muted">Paste one URL per line, choose a target directory, and click Start.</div>', unsafe_allow_html=True)

# Layout: left for URLs and progress, right for controls
left_col, right_col = st.columns([3, 1])

with left_col:
    urls_text = st.text_area("Download URLs (one per line)", height=240)
    # Copy URLs button via a tiny HTML snippet
    if st.button("Copy URLs to clipboard"):
        if urls_text.strip() == "":
            st.warning("No URLs to copy.")
        else:
            import streamlit.components.v1 as components
            escaped = urls_text.replace("\n", "\\n").replace("\"", "\\\"")
            html = """
            <textarea id="urls" style="display:none">{}</textarea>
            <button onclick="navigator.clipboard.writeText(document.getElementById('urls').value)">Copy URLs</button>
            <script>document.querySelector('button').click()</script>
            """.format(escaped)
            components.html(html, height=40)

with right_col:
    st.subheader('Settings')
    download_dir = st.text_input("Download directory", value="downloads")
    max_concurrent = st.number_input("Max concurrent downloads", min_value=1, value=5)
    chunk_size = st.number_input("Chunk size (bytes)", min_value=1024, value=8192)
    st.markdown('**Logging**')
    log_level = st.selectbox("Log level", options=["debug", "info", "warning", "error"], index=1)
    log_file = st.text_input("Log file (optional)", value="")
    log_remote = st.text_input("Remote log endpoint (optional)", value="")
    st.write('')
    check = st.button("🔎 Check URLs")
    start = st.button("▶️ Start downloads")
    clear = st.button("🧹 Clear results")

# Session state initialisation
if 'queue' not in st.session_state:
    st.session_state['queue'] = None
if 'files' not in st.session_state:
    st.session_state['files'] = {}
if 'worker' not in st.session_state:
    st.session_state['worker'] = None
if 'done' not in st.session_state:
    st.session_state['done'] = False
if 'placeholders' not in st.session_state:
    st.session_state['placeholders'] = {}

# Worker that runs downloads in background
def download_worker(urls, download_dir, max_concurrent, chunk_size, q):
    def progress_cb(filename, downloaded, total):
        q.put(('progress', filename, downloaded, total))

    def status_cb(filename, status, info):
        q.put(('status', filename, status, info))

    try:
        asyncio.run(download_multiple_files(urls, max_concurrent, chunk_size, download_dir=download_dir, progress_callback=progress_cb, status_callback=status_cb))
    except Exception as e:
        q.put(('error', str(e)))
    finally:
        q.put(('done', True))


def check_worker(urls, q):
    # Run simple checks for each URL and push results to queue
    try:
        for url in urls:
            filename = os.path.basename(url) or url
            try:
                ok, reason = asyncio.run(is_url_downloadable(url))
            except Exception as e:
                ok = False
                reason = str(e)
            q.put(('check', filename, ok, reason))
    except Exception as e:
        q.put(('error', str(e)))
    finally:
        q.put(('check_done', True))

# Start downloads when button clicked
if start:
    urls = [u.strip() for u in urls_text.splitlines() if u.strip()]
    if len(urls) == 0:
        st.warning("Please paste one or more URLs to download.")
    else:
        # configure logging from UI inputs
        configure_logging(level=log_level, log_file=log_file or None, remote_url=log_remote or None)
        os.makedirs(download_dir, exist_ok=True)
        st.session_state['queue'] = queue.Queue()
        st.session_state['files'] = {os.path.basename(u) or f"file_{i}": {'downloaded': 0, 'total': 0, 'status': 'queued', 'info': ''} for i, u in enumerate(urls)}
        st.session_state['placeholders'] = {}
        st.session_state['done'] = False
        worker = threading.Thread(target=download_worker, args=(urls, download_dir, max_concurrent, chunk_size, st.session_state['queue']), daemon=True)
        st.session_state['worker'] = worker
        worker.start()

# Start URL checks when button clicked
if check:
    urls = [u.strip() for u in urls_text.splitlines() if u.strip()]
    if len(urls) == 0:
        st.warning("Please paste one or more URLs to check.")
    else:
        # configure logging from UI inputs
        configure_logging(level=log_level, log_file=log_file or None, remote_url=log_remote or None)
        st.session_state['queue'] = queue.Queue()
        # Initialize file entries for display
        st.session_state['files'] = {os.path.basename(u) or f"file_{i}": {'downloaded': 0, 'total': 0, 'status': 'queued', 'info': ''} for i, u in enumerate(urls)}
        st.session_state['placeholders'] = {}
        st.session_state['done'] = False
        worker = threading.Thread(target=check_worker, args=(urls, st.session_state['queue']), daemon=True)
        st.session_state['worker'] = worker
        worker.start()

# Clear results
if clear:
    st.session_state['queue'] = None
    st.session_state['files'] = {}
    st.session_state['worker'] = None
    st.session_state['done'] = False
    st.session_state['placeholders'] = {}
    st.rerun()

# Progress container
progress_container = left_col.container()

if st.session_state['queue'] is not None:
    q = st.session_state['queue']

    # Poll queue while worker is running
    while True:
        # Process all queued messages
        while not q.empty():
            msg = q.get()
            if msg[0] == 'progress':
                _, filename, downloaded, total = msg
                key = filename
                if key not in st.session_state['files']:
                    st.session_state['files'][key] = {'downloaded': downloaded, 'total': total, 'status': 'downloading', 'info': ''}
                else:
                    st.session_state['files'][key]['downloaded'] = downloaded
                    st.session_state['files'][key]['total'] = total
                    st.session_state['files'][key]['status'] = 'downloading'
            elif msg[0] == 'status':
                _, filename, status, info = msg
                key = filename
                if key not in st.session_state['files']:
                    st.session_state['files'][key] = {'downloaded': 0, 'total': 0, 'status': status, 'info': info}
                else:
                    st.session_state['files'][key]['status'] = status
                    st.session_state['files'][key]['info'] = info
            elif msg[0] == 'error':
                _, err = msg
                st.error(f"Worker error: {err}")
            elif msg[0] == 'check':
                _, filename, ok, reason = msg
                key = filename
                status = 'downloadable' if ok else 'not-downloadable'
                if key not in st.session_state['files']:
                    st.session_state['files'][key] = {'downloaded': 0, 'total': 0, 'status': status, 'info': reason}
                else:
                    st.session_state['files'][key]['status'] = status
                    st.session_state['files'][key]['info'] = reason
            elif msg[0] == 'check_done':
                st.session_state['done'] = True
            elif msg[0] == 'done':
                st.session_state['done'] = True

        # Render progress UI with placeholders for smoother updates
        with progress_container:
            st.subheader("Downloads")
            for fname, info in st.session_state['files'].items():
                # create or reuse placeholder for each file to avoid re-creating widgets
                ph = st.session_state['placeholders'].get(fname)
                if ph is None:
                    ph = progress_container.empty()
                    st.session_state['placeholders'][fname] = ph

                with ph.container():
                    row = st.columns([3, 1])
                    with row[0]:
                        st.markdown(f"**{fname}**")
                        total = info.get('total', 0)
                        downloaded = info.get('downloaded', 0)
                        status = info.get('status', '')
                        if total:
                            pct = int(downloaded / total * 100) if total else 0
                            st.progress(pct)
                            st.write(f"{status} — {pct}% — {downloaded} / {total} bytes")
                        else:
                            st.write(f"{status} — {downloaded} bytes")
                    with row[1]:
                        status_val = info.get('status')
                        if status_val == 'completed':
                            st.success('Done')
                        elif status_val == 'failed':
                            st.error('Failed')
                        elif status_val == 'downloading':
                            st.info('Downloading')
                        elif status_val == 'downloadable':
                            st.markdown("<div style='background:#d4edda;padding:8px;border-radius:6px;text-align:center'>Downloadable</div>", unsafe_allow_html=True)
                        elif status_val == 'not-downloadable':
                            st.markdown("<div style='background:#f8d7da;padding:8px;border-radius:6px;text-align:center;color:#721c24'>Not-downloadable</div>", unsafe_allow_html=True)
                        else:
                            st.write(info.get('status'))

        # Break when worker finished and queue drained
        worker = st.session_state.get('worker')
        if (worker is not None and not worker.is_alive()) and q.empty():
            break

        time.sleep(0.35)

    # Final summary
    completed = sum(1 for f in st.session_state['files'].values() if f['status'] == 'completed')
    failed = sum(1 for f in st.session_state['files'].values() if f['status'] == 'failed')
    st.success(f"Completed: {completed}, Failed: {failed}")
st.markdown("---")
st.markdown("**Tip:** Run this app locally with `streamlit run streamlit_app.py`. You can copy the result URLs from the UI or open the target download directory on your machine.")
