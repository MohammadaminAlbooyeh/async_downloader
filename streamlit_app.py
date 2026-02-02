import streamlit as st
import threading
import queue
import time
import os
import asyncio
from async_downloader import download_multiple_files

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
    st.write('')
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

# Start downloads when button clicked
if start:
    urls = [u.strip() for u in urls_text.splitlines() if u.strip()]
    if len(urls) == 0:
        st.warning("Please paste one or more URLs to download.")
    else:
        os.makedirs(download_dir, exist_ok=True)
        st.session_state['queue'] = queue.Queue()
        st.session_state['files'] = {os.path.basename(u) or f"file_{i}": {'downloaded': 0, 'total': 0, 'status': 'queued', 'info': ''} for i, u in enumerate(urls)}
        st.session_state['placeholders'] = {}
        st.session_state['done'] = False
        worker = threading.Thread(target=download_worker, args=(urls, download_dir, max_concurrent, chunk_size, st.session_state['queue']), daemon=True)
        st.session_state['worker'] = worker
        worker.start()

# Clear results
if clear:
    st.session_state['queue'] = None
    st.session_state['files'] = {}
    st.session_state['worker'] = None
    st.session_state['done'] = False
    st.session_state['placeholders'] = {}
    st.experimental_rerun()

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
                        if info.get('status') == 'completed':
                            st.success('Done')
                        elif info.get('status') == 'failed':
                            st.error('Failed')
                        elif info.get('status') == 'downloading':
                            st.info('Downloading')
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
