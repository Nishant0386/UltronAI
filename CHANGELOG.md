# ULTRON OS - System Update & Implementation Changelog

All system updates, bug fixes, and architectural implementations are logged below in chronological order:

---

## [v2.2.0] - 2026-07-25

### 1. AutoGPT Architecture Fixes
- **Playwright Chromium Launch (`backend/browser_agent.py`)**:
  - Replaced system browser redirection with Playwright Chromium headful launch using `args=["--start-maximized", "--no-sandbox", "--disable-setuid-sandbox"]`.
- **AutoGPT `execute_dom_action` (`backend/browser_agent.py`)**:
  - Created flexible `execute_dom_action(url_or_page, action_type, selector, text)` supporting both positional and keyword argument variations.
  - Added `networkidle` state wait (`await page.wait_for_load_state("networkidle", timeout=5000)`).
  - Added `loc.click(force=True)` overlay bypass.
  - Added Deep Shadow DOM JS Injection fallback (`findInShadow(document)`).
- **Win32 `AttachThreadInput` Focus Stealing (`backend/desktop_agent.py`)**:
  - Implemented `force_foreground(hwnd)` using `win32process.AttachThreadInput` to temporarily attach Python thread to target app window thread, bypassing Windows UIPI focus stealing locks before typing.
  - Updated `open_app_and_type()` to assert foreground focus before sending `pyautogui.write()` keystrokes.
- **Base64 Audio Data URI Return for PyWebView (`backend/routers/tts.py` & `frontend/index.html`)**:
  - Encoded TTS audio into Base64 JSON URI (`data:audio/mpeg;base64,...` / `data:audio/wav;base64,...`), solving PyWebView `blob:http://...` URL blocking.
  - Updated `speakChatResponse()` in `frontend/index.html` to parse Data URIs directly into `new Audio(data.audio_base64).play()`.

---

### 2. Frontend JS Syntax Fix & Control Recovery
- **Syntax Error Fix (`frontend/index.html`)**:
  - Resolved duplicate closing brace `}` inside `speakChatResponse()` at line 1435 that crashed JavaScript parsing on page load.
- **3D Sphere & Controls Recovery (`frontend/index.html`)**:
  - Wrapped Three.js Holographic Core initialization in a safe `try-catch` block.
  - Re-attached and verified event listeners for `#chatInput`, `#chatSendBtn`, `#chatMicBtn`, and `#autoListenToggleBtn`.
  - Empirically verified with Playwright test `verify_frontend_syntax_fix.py`: `0` console errors, `#chatInput` active, Three.js 3D Core canvas rendered (`True`).

---

## [v2.1.0] - 2026-07-25

### 1. NVIDIA API Latency Optimization & LLM Pipeline
- Configured fast model hierarchy: `mistralai/mistral-nemotron` -> `meta/llama-3.2-3b-instruct` -> `ibm/granite-3.0-8b-instruct`.
- Reduced Time-To-First-Token (TTFT) from 11.21 seconds down to **0.39 seconds**.

### 2. Wikipedia Knowledge Retrieval Engine
- Added direct Wikipedia factual summary lookup for queries like "who is", "what is", "kaun hai".
- Injected verified Wikipedia summaries into prompt context.

### 3. Modi Voice Cloning via Coqui XTTS-v2
- Integrated zero-shot voice cloning from Modi reference audio clip.
- Configured automatic fallback to Edge-TTS (`hi-IN-MadhurNeural` / `en-US-ChristopherNeural`).

---

## [v2.0.0] - 2026-07-25

### Initial Native Desktop Integration
- Frameless `pywebview` window runtime with `pystray` system tray support.
- Dual-layer Three.js 3D Holographic Core sphere.
- Sci-Fi floating glassmorphism HUD modals (`#translateModal`, `#agentModal`, `#mapsModal`).
