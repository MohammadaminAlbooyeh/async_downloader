# async_downloader ✅

An easy-to-use asynchronous file downloader written in Python using `aiohttp` and `asyncio`. It downloads multiple files concurrently with progress bars and a simple CLI.

---

## 🔧 Features

- Concurrent downloads using `asyncio` and `aiohttp`
- Progress bars for each file via `tqdm`
- Configurable maximum concurrency and chunk size
- Saves files to a `downloads/` directory by default

---

## 🚀 Quickstart

1. Create a virtual environment (recommended):

```bash
python -m venv .venv
source .venv/bin/activate  # macOS / Linux
.venv\Scripts\activate     # Windows (PowerShell)
```

2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Run the downloader:

```bash
python async_downloader.py https://example.com/file1.zip https://example.com/file2.jpg
```

Options:

- `--max-concurrent N` – maximum concurrent downloads (default: 5)
- `--chunk-size BYTES` – download chunk size in bytes (default: 8192)
- `--download-dir PATH` – where to save files (default: `downloads`)

Example with options:

```bash
python async_downloader.py --max-concurrent 10 --download-dir /tmp/my-downloads https://example.com/file1.zip
```

---

## 🌐 Web UI (Streamlit)

You can run a simple web UI powered by Streamlit to paste links, choose a download directory, and run downloads from your browser.

Install dependencies (if not already):

```bash
pip install -r requirements.txt
```

Run the Streamlit app:

```bash
streamlit run streamlit_app.py
```

The app lets you paste multiple URLs (one per line), set the target directory, and watch per-file progress and status from the web page. It also provides a **Copy URLs to clipboard** button to quickly copy the pasted links for sharing or reuse.

---

---

## ⚙️ Implementation notes

- The main script is `async_downloader.py` which:
  - Uses `aiohttp` `ClientSession` for HTTP requests
  - Streams responses and writes to disk in chunks
  - Uses `asyncio.Semaphore` to limit concurrency
  - Cleans up partial files on errors

> Tip: If a server does not send a `Content-Length` header, `tqdm` will show an indeterminate progress bar for that file.

---

## ✅ Tests & Contributing

Contributions are welcome — open an issue or send a pull request with improvements. If you add features, please include tests and update this README with usage notes.

---

## 📄 License

This project is provided under the MIT License. See `LICENSE` for details (add one if not present).

---

If you'd like, I can also add a simple `Makefile`, test cases, or a CI workflow to run checks automatically. ✨
