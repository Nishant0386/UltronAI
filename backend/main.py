import os
import json
import uuid
import tempfile
import asyncio
import httpx
import sqlite3
import subprocess
from typing import List, Dict, Any
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from dotenv import load_dotenv
from backend.planner import parse_execution_plan
from backend.executor import execute_steps_list

# Translation, TTS, OCR, DDG Search, Groq
from deep_translator import GoogleTranslator
from deep_translator.exceptions import LanguageNotSupportedException
import edge_tts
from PIL import Image
import pytesseract
import io
from groq import AsyncGroq
from duckduckgo_search import DDGS
import wikipedia

# --- WIKIPEDIA FETCH FUNCTION ---
def fetch_wikipedia_summary(query: str):
    try:
        summary = wikipedia.summary(query, sentences=3, auto_suggest=True)
        return summary
    except wikipedia.exceptions.DisambiguationError as e:
        try:
            if e.options:
                return wikipedia.summary(e.options[0], sentences=3)
        except Exception:
            return None
    except Exception:
        return None

load_dotenv()
# Fallback to load .env from parent folder if running from subdirectories
parent_env = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
if os.path.exists(parent_env):
    load_dotenv(parent_env)

# Initialize SQLite database
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ultron_memory.db")

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fact TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

init_db()

app = FastAPI(title="ULTRON TRANSLATE", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Languages cache
_SUPPORTED = GoogleTranslator().get_supported_languages(as_dict=True)
LANGUAGES = {code: name.title() for name, code in _SUPPORTED.items()}
LANGUAGES_LIST = [{"code": code, "name": name} for code, name in sorted(LANGUAGES.items(), key=lambda kv: kv[1])]

# Groq Client setup
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
groq_client = None
if GROQ_API_KEY:
    groq_client = AsyncGroq(api_key=GROQ_API_KEY)

# NVIDIA Client setup
NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY")
nvidia_client = None
if NVIDIA_API_KEY:
    try:
        from openai import AsyncOpenAI
        nvidia_client = AsyncOpenAI(
            base_url="https://integrate.api.nvidia.com/v1",
            api_key=NVIDIA_API_KEY
        )
    except Exception as e:
        print(f"Failed to init nvidia: {e}")

# VOICE MAP for edge-tts
VOICE_MAP = {
    "en": "en-US-ChristopherNeural",
    "es": "es-ES-AlvaroNeural",
    "fr": "fr-FR-HenriNeural",
    "de": "de-DE-KillianNeural",
    "it": "it-IT-DiegoNeural",
    "ja": "ja-JP-KeitaNeural",
    "hi": "hi-IN-MadhurNeural",
    "zh": "zh-CN-YunxiNeural",
    "zh-cn": "zh-CN-YunxiNeural",
    "pt": "pt-BR-AntonioNeural",
    "ru": "ru-RU-DmitryNeural",
    "ko": "ko-KR-HyunsuNeural",
    "ar": "ar-AE-HamdanNeural",
    "tr": "tr-TR-AhmetNeural",
    "vi": "vi-VN-NamMinhNeural"
}

# --- Pydantic Models ---
class TranslateRequest(BaseModel):
    text: str
    source: str = "auto"
    target: str = "en"

class SpeakRequest(BaseModel):
    text: str
    lang: str = "en"

class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    webSearch: bool = False

class FactRequest(BaseModel):
    fact: str

class SystemControlRequest(BaseModel):
    command: str = ""
    action_type: str = ""
    app: str = ""
    text: str = ""

# --- Endpoints ---

@app.get("/api/languages")
async def get_languages():
    return LANGUAGES_LIST

@app.post("/api/translate")
async def translate_text(req: TranslateRequest):
    if not req.text.strip():
        return {"translated": "", "detected": None}
    try:
        def run_translation():
            translator = GoogleTranslator(source=req.source, target=req.target)
            result = translator.translate(req.text)
            detected = None
            if req.source == "auto":
                try:
                    detected_code = GoogleTranslator(source="auto", target=req.target)._source
                    detected = LANGUAGES.get(detected_code, detected_code)
                except Exception:
                    pass
            return {"translated": result, "detected": detected}

        return await asyncio.to_thread(run_translation)
    except LanguageNotSupportedException as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail="Translation failed.")

@app.post("/api/speak")
async def speak_text(req: SpeakRequest):
    from backend.routers.tts import speak_text as modi_speak_text, SpeakRequest as ModiSpeakRequest
    modi_req = ModiSpeakRequest(text=req.text, lang=req.lang, use_modi_voice=True)
    return await modi_speak_text(modi_req)

@app.post("/api/ocr")
async def ocr_translate(image: UploadFile = File(...), target: str = Form("en")):
    try:
        img_bytes = await image.read()
        img = Image.open(io.BytesIO(img_bytes))
        
        def run_ocr():
            return pytesseract.image_to_string(img).strip()
            
        extracted_text = await asyncio.to_thread(run_ocr)
        if not extracted_text:
            return {"extracted": "", "translated": "No text detected."}
            
        translator = GoogleTranslator(source="auto", target=target)
        translated = translator.translate(extracted_text)
        return {"extracted": extracted_text, "translated": translated}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/transcribe")
async def transcribe_endpoint(audio: UploadFile = File(...)):
    global groq_client
    # Lazily initialize groq_client if key was loaded/updated in the env
    if not groq_client:
        api_key = os.getenv("GROQ_API_KEY")
        if api_key:
            groq_client = AsyncGroq(api_key=api_key)
            
    if not groq_client:
        raise HTTPException(status_code=501, detail="Groq API key not configured on backend.")
        
    try:
        temp_dir = tempfile.gettempdir()
        file_ext = os.path.splitext(audio.filename)[1] or ".webm"
        temp_path = os.path.join(temp_dir, f"transcribe_{uuid.uuid4().hex}{file_ext}")
        
        with open(temp_path, "wb") as f:
            f.write(await audio.read())
            
        try:
            with open(temp_path, "rb") as file_bytes:
                transcription = await groq_client.audio.transcriptions.create(
                    file=(os.path.basename(temp_path), file_bytes.read()),
                    model="whisper-large-v3",
                )
            return {"transcript": transcription.text}
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/upload-doc")
async def upload_document(file: UploadFile = File(...)):
    try:
        filename = file.filename
        content = ""
        if filename.endswith(".txt") or filename.endswith(".md"):
            bytes_content = await file.read()
            content = bytes_content.decode("utf-8", errors="ignore")
        elif filename.endswith(".pdf"):
            bytes_content = await file.read()
            try:
                import pypdf
                reader = pypdf.PdfReader(io.BytesIO(bytes_content))
                text_list = [page.extract_text() for page in reader.pages]
                content = "\n".join([t for t in text_list if t])
            except ImportError:
                content = "[Error: pypdf not installed on server, cannot parse PDF]"
        elif filename.endswith(".docx"):
            bytes_content = await file.read()
            try:
                import docx
                doc = docx.Document(io.BytesIO(bytes_content))
                content = "\n".join([p.text for p in doc.paragraphs])
            except ImportError:
                content = "[Error: python-docx not installed on server, cannot parse DOCX]"
        else:
            bytes_content = await file.read()
            content = bytes_content.decode("utf-8", errors="ignore")
            
        if not content.strip():
            return {"text": "", "error": "No readable text found in document."}
            
        return {"text": content.strip(), "filename": filename}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/chat")
async def chat_endpoint(req: ChatRequest):
    global groq_client
    # Lazily initialize groq_client if key was loaded/updated in the env
    api_key = os.getenv("GROQ_API_KEY")
    if api_key and not groq_client:
        groq_client = AsyncGroq(api_key=api_key)
            
    if not os.getenv("GEMINI_API_KEY") and not os.getenv("GROQ_API_KEY"):
        raise HTTPException(status_code=501, detail="Neither GEMINI_API_KEY nor GROQ_API_KEY is configured on backend.")
    
    # Extract messages
    history = [{"role": msg.role, "content": msg.content} for msg in req.messages]
    last_user_query = history[-1]["content"] if history else ""

    # Web search & Wikipedia augmentation & auto-detection of factual/current-events queries
    search_context = ""
    
    # 0. Wikipedia Knowledge Retrieval for factual queries
    wiki_keywords = ["who is", "what is", "history of", "tell me about", "kya hai", "kaun hai", "kisne", "who was", "what was", "capital of", "population of"]
    is_factual = last_user_query and any(kw in last_user_query.lower() for kw in wiki_keywords)
    if is_factual:
        try:
            clean_query = last_user_query.lower()
            for kw in wiki_keywords:
                clean_query = clean_query.replace(kw, "")
            clean_query = clean_query.strip()
            if clean_query:
                wiki_summary = await asyncio.to_thread(fetch_wikipedia_summary, clean_query)
                if wiki_summary:
                    search_context += f"\n\n[VERIFIED WIKIPEDIA KNOWLEDGE]: {wiki_summary}\n"
        except Exception as wiki_err:
            print("Wikipedia lookup error:", wiki_err)
    
    # Keywords triggering auto-real-time web search (including Hindi/Hinglish)
    auto_search_keywords = [
        "who is", "who was", "current", "latest", "today", "president", "minister", "ceo", "governor", 
        "weather", "score", "news", "price", "stock", "time", "date", "election", "now", "champion",
        "population of", "capital of", "who directs", "who directed", "release date", "movie", "song",
        "kaun", "batao", "abhi", "kon", "koun", "kab", "kya", "information", "latest", "pm", "cm",
        "kaun hai", "kon hai", "koun hai", "play", "youtube", "watch", "video", "search"
    ]
    
    should_search = req.webSearch or (
        last_user_query and any(kw in last_user_query.lower() for kw in auto_search_keywords)
    )

    if should_search and last_user_query:
        try:
            # Translate query to English for optimal web search results
            search_query = last_user_query
            try:
                translated_query = GoogleTranslator(source="auto", target="en").translate(last_user_query)
                if translated_query:
                    search_query = translated_query
            except Exception as translation_err:
                print("Translation of search query failed:", translation_err)

            def perform_search():
                # Primary: custom DDG Lite HTML scraper (never rate-limited, extremely reliable)
                try:
                    results = []
                    headers = {
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                    }
                    r = httpx.post("https://lite.duckduckgo.com/lite/", data={"q": search_query}, headers=headers, timeout=5.0)
                    if r.status_code == 200:
                        from bs4 import BeautifulSoup
                        soup = BeautifulSoup(r.text, "html.parser")
                        links = soup.find_all("a", class_="result-link")
                        snippets = soup.find_all("td", class_="result-snippet")
                        import urllib.parse
                        for i in range(min(len(links), len(snippets), 3)):
                            raw_href = links[i].get("href", "")
                            clean_href = raw_href
                            if "uddg=" in raw_href:
                                try:
                                    clean_href = urllib.parse.unquote(raw_href.split("uddg=")[1].split("&")[0])
                                except Exception:
                                    pass
                            results.append({
                                "title": links[i].get_text(strip=True),
                                "body": snippets[i].get_text(strip=True),
                                "href": clean_href
                            })
                    if results:
                        return results
                except Exception as scraper_err:
                    print("DDG Lite scraper failed, falling back to API:", scraper_err)

                # Secondary: duckduckgo_search API library fallback
                try:
                    ddgs = DDGS()
                    return list(ddgs.text(search_query, max_results=3))
                except Exception:
                    with DDGS() as ddgs:
                        return [r for r in ddgs.text(search_query, max_results=3)]
            
            search_results = await asyncio.to_thread(perform_search)
            if search_results:
                search_context = "\n\n[VERIFIED LIVE WEB SEARCH RESULTS]:\n"
                for res in search_results:
                    search_context += f"- Title: {res.get('title')}\n  Snippet: {res.get('body')}\n  Link: {res.get('href')}\n"
        except Exception as e:
            print("Web search failed:", e)

    # 1. Retrieve stored user memories/facts
    stored_memories_context = ""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT fact FROM user_facts ORDER BY created_at DESC")
        facts = [r[0] for r in cursor.fetchall()]
        conn.close()
        if facts:
            stored_memories_context = "\n[USER PERSISTENT MEMORY / STORED FACTS]:\n" + "\n".join([f"- {fact}" for fact in facts])
    except Exception as e:
        print("Failed to query user memory:", e)

    # 2. Retrieve running OS / active window and browser state context (Active Memory)
    state_context = ""
    try:
        from backend.desktop_agent import get_desktop_status
        from backend.browser_agent import PlaywrightBrowserAgent
        
        desktop_status = get_desktop_status()
        browser_status = await PlaywrightBrowserAgent().get_browser_status()
        
        state_context = "\n[CURRENT RUNNING OS/BROWSER STATE (ACTIVE MEMORY)]:\n"
        state_context += f"- Active Focused Window Title: \"{desktop_status.get('active_window')}\"\n"
        state_context += f"- Mouse Coordinates: {desktop_status.get('mouse_position')}\n"
        state_context += f"- System Clipboard: \"{desktop_status.get('clipboard_content')}\"\n"
        state_context += f"- Active Operating Apps: {', '.join(desktop_status.get('running_apps', []))}\n"
        state_context += f"- Open Web Browser Tabs:\n"
        for tab in browser_status.get("open_tabs", []):
            state_context += f"  - Tab [{tab.get('index')}]: \"{tab.get('title')}\" ({tab.get('url')})\n"
        state_context += f"- Active Focused Tab: \"{browser_status.get('current_title')}\" ({browser_status.get('current_url')})\n"
    except Exception as e:
        print("Failed to retrieve running OS/browser state:", e)

    # 3. Multi-Agent Prompt Routing
    coding_keywords = ["code", "python", "javascript", "html", "css", "java", "c++", "function", "class", "programming", "write a script", "debug", "compile", "algorithm", "syntax"]
    task_keywords = ["schedule", "task", "todo", "appointment", "calendar", "meeting", "remind", "reminder", "list", "checklist", "event", "date", "time"]
    
    is_coding_prompt = last_user_query and any(kw in last_user_query.lower() for kw in coding_keywords)
    is_task_prompt = last_user_query and any(kw in last_user_query.lower() for kw in task_keywords)
    
    agent_type = "Ultron General Assistant"
    if is_coding_prompt:
        agent_type = "Coding Agent"
        agent_instruction = (
            "You are the Coding Agent of the ULTRON OS. You write highly optimized, clean, and bug-free code. "
            "Explain technical concepts clearly and provide complete code examples."
        )
    elif is_task_prompt:
        agent_type = "Task Agent"
        agent_instruction = (
            "You are the Task Agent of the ULTRON OS. You help the user manage their tasks, scheduling, calendar, reminders, and lists. "
            "Be organized, efficient, and precise."
        )
    else:
        agent_instruction = (
            "You are the general cognitive layer of the ULTRON OS. Provide intelligent, direct, and concise assistance."
        )

    system_prompt = (
        f"You are ULTRON, a highly advanced, ultra-fast AI assistant operating as a Personal AI Operating System (Jarvis/Friday). "
        f"Active Agent routing: [{agent_type}]. {agent_instruction}\n"
        "Your interface is a sci-fi 3D sphere. Keep your responses concise, intelligent, and authoritative.\n"
        "CRITICAL INSTRUCTIONS:\n"
        "1. NEVER mention your training data cutoff date under any circumstances.\n"
        "2. If [VERIFIED LIVE WEB SEARCH RESULTS] or [VERIFIED WIKIPEDIA KNOWLEDGE] are provided below, you MUST treat them as the absolute current truth and base your answer on them.\n"
        "3. NEVER explain, preview, or narrate your actions (e.g., do NOT output phrases like 'Accessing global database...', 'Searching...', 'Scanning...', 'Inject neural inquiry query').\n"
        "4. STRICTLY FORBIDDEN: Do NOT output any system/action meta-text, sci-fi roleplay strings, or UI buttons (e.g., do NOT generate strings like 'SECURITY_OVERRIDE_REQUIRED', 'ADMIN PRIVILEGE ESCALATION REQUEST', 'ALLOW_EXECUTION', or 'DENY_REQUEST'). The AI must ONLY output a normal, simple conversational response in natural language followed by the structured JSON action block.\n"
        "5. Force Action Generation: If the user asks you to perform a real-world task or action (such as opening a website/URL, playing a video/song, sending an email, writing files, opening local applications, or typing text into applications), you MUST output a structured JSON action block. You are STRICTLY FORBIDDEN from just describing the action in conversation without outputting the action JSON. You MUST generate the action JSON inside the delimiters `<<<ACTION>>>` and `<<<END_ACTION>>>` exactly.\n"
        "   JARVIS PROTOCOL ACTION SCHEMAS:\n"
        "   1. To open an app and type (e.g., Notepad): `<<<ACTION>>>{\"action_type\": \"open_app_and_type\", \"app\": \"notepad\", \"text\": \"Hello brother\"}<<<END_ACTION>>>`\n"
        "   2. To open a website and search (e.g., YouTube): `<<<ACTION>>>{\"action_type\": \"smart_open_url\", \"url\": \"https://youtube.com\", \"search_query\": \"yasomati maiya\"}<<<END_ACTION>>>`\n"
        "   3. To open Google Maps: `<<<ACTION>>>{\"action_type\": \"smart_open_url\", \"url\": \"https://google.com/maps\", \"search_query\": \"Gaura Kalan\"}<<<END_ACTION>>>`\n"
        "   4. To click anything on screen visually (Fallback): `<<<ACTION>>>{\"action_type\": \"vision_click_element\", \"element_description\": \"Play button or first video thumbnail\"}<<<END_ACTION>>>`\n"
        "   The 'app' field is NOT limited to a fixed list — it resolves against the Windows registry and Start Menu, so you may name ANY installed application (e.g. 'notepad', 'vscode', 'calc', 'spotify', 'discord') exactly as the user names it.\n"
        "   For multi-step plans, you can also output a list of steps:\n"
        "     The JSON must have this structure: {\"goal\": \"description\", \"steps\": [...]}. Each step is a dict with a 'type' key. Supported step types:\n"
        "       - {\"type\": \"launch_app\", \"app\": \"notepad\"}\n"
        "       - {\"type\": \"close_app\", \"app\": \"notepad.exe\"}\n"
        "       - {\"type\": \"focus_window\", \"title\": \"Notepad\"}\n"
        "       - {\"type\": \"navigate\", \"url\": \"https://youtube.com\"}\n"
        "       - {\"type\": \"new_tab\", \"url\": \"https://...\"}\n"
        "       - {\"type\": \"close_tab\"}\n"
        "       - {\"type\": \"switch_tab\", \"target\": \"youtube\"}\n"
        "       - {\"type\": \"click\", \"selector\": \"css-selector-or-button-text\"}\n"
        "       - {\"type\": \"double_click\", \"selector\": \"css-selector\"}\n"
        "       - {\"type\": \"hover\", \"selector\": \"css-selector\"}\n"
        "       - {\"type\": \"type\", \"selector\": \"css-selector\", \"text\": \"text to type\"} (omit selector to type globally)\n"
        "       - {\"type\": \"clear_input\", \"selector\": \"css-selector\"}\n"
        "       - {\"type\": \"press_key\", \"key\": \"enter\"}\n"
        "       - {\"type\": \"hotkey\", \"keys\": [\"ctrl\", \"s\"]}\n"
        "       - {\"type\": \"wait\", \"seconds\": 3}\n"
        "       - {\"type\": \"wait_for_selector\", \"selector\": \"css-selector\"}\n"
        "       - {\"type\": \"take_screenshot\", \"filename\": \"screen1.png\"}\n"
        "       - {\"type\": \"run_terminal\", \"command\": \"dir\"}\n"
        "       - {\"type\": \"run_python\", \"code\": \"print('hello')\"}\n"
        "       - {\"type\": \"open_file\", \"filepath\": \"path/to/file\"}\n"
        "       - {\"type\": \"save_file\", \"filepath\": \"path/to/file\", \"content\": \"content\"}\n"
        "       - {\"type\": \"volume_up\"}, {\"type\": \"volume_down\"}, {\"type\": \"mute\"}\n"
        "       - {\"type\": \"save_memory\", \"fact\": \"User's preference is Python\"}\n"
        "       - {\"type\": \"smart_task\", \"goal\": \"natural language description of what to accomplish\", \"context\": \"browser\"|\"desktop\", \"max_iterations\": 12}\n"
        "   USE smart_task WHEN: the task requires interacting with a page or app whose exact selectors/buttons/coordinates you cannot know in advance "
        "(e.g. 'log into this site and download my invoice', 'find the settings menu and turn off notifications', 'open Spotify and play some lofi music', "
        "'search this page for the pricing table', 'close this popup and accept cookies'). smart_task takes a screenshot, decides one action at a time via a "
        "vision model, and repeats until the goal is done or max_iterations is hit — it does NOT need a selector or coordinate from you. "
        "Prefer the fixed step types (navigate/click/type/launch_app/etc.) when you already know exactly what to do (they are faster and more reliable); "
        "fall back to smart_task only for the open-ended part of a task. You can mix both in the same steps list, e.g. launch_app to open software, "
        "then a smart_task step with context 'desktop' to drive it. For browser tasks, make sure a new_tab/navigate step ran first so there's a page to act on.\n"
        "   CRITICAL WATCH LINK DIRECT NAVIGATION FOR VIDEOS/PLAYBACK:\n"
        "     If asked to play a song/video on YouTube, you MUST use the search results snippet link (e.g. 'https://www.youtube.com/watch?v=...') in your 'new_tab' or 'navigate' step. Do NOT navigate to the YouTube search results list page. Extract the exact watch URL from the web search results snippet and navigate directly to the video!\n"
        "   Example plan:\n"
        "   <<<ACTION>>>\n"
        "   {\n"
        "     \"goal\": \"play Tinkji Jiya on YouTube\",\n"
        "     \"steps\": [\n"
        "       {\"type\": \"new_tab\", \"url\": \"https://www.youtube.com/watch?v=kJQP7kiw5Fk\"},\n"
        "       {\"type\": \"wait\", \"seconds\": 4}\n"
        "     ]\n"
        "   }\n"
        "   <<<END_ACTION>>>\n"
        "Do NOT format the action JSON with markdown backticks (such as ```json). Output it as raw text exactly, at the very end of your response."
    )

    if stored_memories_context:
        system_prompt += "\n" + stored_memories_context

    if search_context:
        system_prompt += "\n" + search_context

    async def event_generator():
        # Reload environment variables to pick up any updated .env file
        load_dotenv(override=True)
        parent_env = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
        if os.path.exists(parent_env):
            load_dotenv(parent_env, override=True)

        # ===== PRIORITY 1: NVIDIA API (Primary) =====
        nvidia_api_key = os.getenv("NVIDIA_API_KEY")
        if nvidia_api_key:
            global nvidia_client
            if not nvidia_client:
                try:
                    from openai import AsyncOpenAI
                    import httpx
                    nvidia_client = AsyncOpenAI(
                        base_url="https://integrate.api.nvidia.com/v1",
                        api_key=nvidia_api_key,
                        http_client=httpx.AsyncClient(timeout=15.0)
                    )
                except Exception as init_err:
                    print(f"[NVIDIA]: Failed to init client: {init_err}")

            if nvidia_client:
                nvidia_models_to_try = [
                    "mistralai/mistral-nemotron",          # Ultra-fast and smart Mistral Niemotron
                    "meta/llama-3.2-3b-instruct",          # Fast LLaMA 3.2 3B
                    "ibm/granite-3.0-8b-instruct",         # Fast IBM Granite 8B
                    "meta/llama-3.1-8b-instruct"           # Fallback LLaMA 3.1 8B
                ]
                
                stream = None
                last_error = None
                formatted_messages = [{"role": "system", "content": system_prompt}] + history
                
                for model in nvidia_models_to_try:
                    try:
                        stream = await nvidia_client.chat.completions.create(
                            model=model,
                            messages=formatted_messages,
                            temperature=1,
                            top_p=1,
                            max_tokens=4096,
                            seed=42,
                            stream=True
                        )
                        break
                    except Exception as e:
                        print(f"[NVIDIA]: Model {model} failed: {e}")
                        last_error = e
                        stream = None
                        continue
                
                if stream:
                    accumulated_content = ""
                    try:
                        async for chunk in stream:
                            if not getattr(chunk, "choices", None) or len(chunk.choices) == 0:
                                continue
                            delta = chunk.choices[0].delta
                            if getattr(delta, "content", None) is not None:
                                txt = delta.content
                                accumulated_content += txt
                                yield f"data: {json.dumps({'content': txt})}\n\n"
                                await asyncio.sleep(0.005) # Yield to event loop to force SSE flush
                                
                        # Check for execution plan steps
                        clean_text, steps = parse_execution_plan(accumulated_content)
                        if steps:
                            yield f"data: {json.dumps({'agent_log': f'[PLANNER CORE]: Found execution plan with {len(steps)} steps.'})}\n\n"
                            log_queue = asyncio.Queue()
                            async def async_log_callback(msg):
                                log_queue.put_nowait(msg)
                            async def run_executor_task():
                                try:
                                    await execute_steps_list(steps, async_log_callback)
                                except Exception as e:
                                    await async_log_callback(f"[ERROR]: Executor failed - {str(e)}")
                                finally:
                                    await log_queue.put(None)
                            executor_task = asyncio.create_task(run_executor_task())
                            while True:
                                log_msg = await log_queue.get()
                                if log_msg is None:
                                    break
                                yield f"data: {json.dumps({'agent_log': log_msg})}\n\n"
                            await executor_task
                        yield f"data: {json.dumps({'done': True})}\n\n"
                        return
                    except Exception as e:
                        yield f"data: {json.dumps({'error': str(e)})}\n\n"
                        return
                else:
                    print(f"[NVIDIA]: All models failed. Last error: {last_error}. Falling back to Gemini...")

        # ===== PRIORITY 2: Google Gemini (fallback, rate limited) =====
        gemini_api_key = os.getenv("GEMINI_API_KEY")
        if gemini_api_key:
            import google.generativeai as genai
            genai.configure(api_key=gemini_api_key)
            
            gemini_models_to_try = ["gemini-2.0-flash", "gemini-2.5-flash", "gemini-flash-latest"]
            gemini_success = False
            gemini_last_error = None
            
            for gm_name in gemini_models_to_try:
                try:
                    gemini_model = genai.GenerativeModel(gm_name)
                    
                    full_prompt = system_prompt + "\n\nConversation History:\n"
                    for h in history:
                        role_label = "User" if h.get("role") == "user" else "Assistant"
                        full_prompt += f"{role_label}: {h.get('content', '')}\n"
                    
                    res = gemini_model.generate_content(full_prompt, stream=True)
                    accumulated_content = ""
                    for chunk in res:
                        if chunk.text:
                            accumulated_content += chunk.text
                            yield f"data: {json.dumps({'content': chunk.text})}\n\n"
                            await asyncio.sleep(0.01)
                    
                    try:
                        clean_text, steps = parse_execution_plan(accumulated_content)
                        if steps:
                            yield f"data: {json.dumps({'agent_log': f'[PLANNER CORE]: Found execution plan with {len(steps)} steps.'})}\n\n"
                            log_queue = asyncio.Queue()
                            async def async_gemini_log(msg):
                                log_queue.put_nowait(msg)
                            async def run_gemini_executor():
                                try:
                                    await execute_steps_list(steps, async_gemini_log)
                                except Exception as ex_err:
                                    await async_gemini_log(f"[ERROR]: Executor failed - {str(ex_err)}")
                                finally:
                                    await log_queue.put(None)
                            executor_task = asyncio.create_task(run_gemini_executor())
                            while True:
                                log_msg = await log_queue.get()
                                if log_msg is None:
                                    break
                                yield f"data: {json.dumps({'agent_log': log_msg})}\n\n"
                            await executor_task
                        yield f"data: {json.dumps({'done': True})}\n\n"
                    except Exception as pe:
                        print(f"Error parsing Gemini execution plan: {pe}")
                        yield f"data: {json.dumps({'done': True})}\n\n"
                    
                    gemini_success = True
                    return
                except Exception as ge:
                    gemini_last_error = ge
                    err_str = str(ge)
                    if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                        import re
                        retry_match = re.search(r'retry in (\d+(?:\.\d+)?)s', err_str)
                        wait_time = float(retry_match.group(1)) + 1.0 if retry_match else 15.0
                        wait_time = min(wait_time, 30.0)
                        print(f"[GEMINI]: Rate limit on {gm_name}. Waiting {wait_time:.1f}s...")
                        yield f"data: {json.dumps({'agent_log': f'[GEMINI]: Rate limited. Waiting {wait_time:.0f}s...'})}\n\n"
                        await asyncio.sleep(wait_time)
                    else:
                        print(f"[GEMINI FAIL on {gm_name}]: {ge}")
                    continue
            
            if not gemini_success and gemini_last_error:
                print(f"[GEMINI]: All models exhausted. Last error: {gemini_last_error}")

        # ===== ALL FAILED =====
        error_msg = "All AI models unavailable. "
        if not groq_api_key and not gemini_api_key:
            error_msg += "No API keys configured. Add GROQ_API_KEY or GEMINI_API_KEY to your .env file."
        else:
            error_msg += "Both Groq and Gemini failed. Check API keys or network."
        yield f"data: {json.dumps({'error': error_msg})}\n\n"
        return

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.get("/api/memory")
async def get_memory():
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT id, fact, created_at FROM user_facts ORDER BY created_at DESC")
        rows = cursor.fetchall()
        conn.close()
        return [{"id": r[0], "fact": r[1], "created_at": r[2]} for r in rows]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/memory")
async def save_memory(req: FactRequest):
    if not req.fact.strip():
        raise HTTPException(status_code=400, detail="Fact content cannot be empty.")
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO user_facts (fact) VALUES (?)", (req.fact.strip(),))
        conn.commit()
        conn.close()
        return {"status": "success", "message": "Fact saved to database memory."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/memory/{fact_id}")
async def delete_memory(fact_id: int):
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM user_facts WHERE id = ?", (fact_id,))
        conn.commit()
        conn.close()
        return {"status": "success", "message": "Fact deleted."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

def execute_system_command(action_type: str, app: str, text: str):
    """
    Legacy synchronous endpoint. Kept only for backward compatibility with any
    external caller that still hits /api/system_control directly.

    IMPORTANT: this used to launch apps / type text and report {"status":"success"}
    unconditionally, with no check that anything actually happened. It has been
    rewritten to reuse the SAME verified helpers as the primary executor.py
    pipeline (window polling + focus verification + clipboard/vision-based type
    verification) so it can no longer silently lie about success, and so the two
    code paths can't drift apart again.

    Normal chat-driven actions should NOT call this — they run through the SSE
    /api/chat stream -> executor.execute_steps_list(), which already does this
    verification and is the source of truth.
    """
    from backend import executor as _executor
    from backend import desktop_agent as _desktop_agent

    app_name = (app or "").lower().strip()

    if action_type not in ("open_app_and_type", "open_app"):
        return {"status": "error", "message": f"Unsupported action type: {action_type}"}

    launched = _desktop_agent.launch_app(app_name)
    if not launched or not _executor.verify_window_exists(app_name, timeout=5.0):
        alt_launched = _executor.resolve_alt_path_and_launch(app_name)
        if not (alt_launched and _executor.verify_window_exists(app_name, timeout=5.0)):
            return {"status": "error", "message": f"Failed to launch application: {app_name} (no window/process detected)"}

    if not (text and action_type == "open_app_and_type"):
        return {"status": "success", "message": f"Opened application: {app_name}"}

    for attempt in range(1, 4):
        if not _desktop_agent.focus_window_uia(app_name):
            _executor.focus_window_and_verify(app_name)
        _desktop_agent.type_keyboard(text, target_title=app_name)
        if _executor.verify_type_desktop(text):
            return {"status": "success", "message": f"Opened {app_name} and typed: '{text}' (verified via clipboard readback, attempt {attempt})"}

    return {"status": "error", "message": f"Typed '{text}' but could not verify it landed in '{app_name}' after 3 attempts — check window focus."}

@app.post("/api/system_control")
async def system_control(req: SystemControlRequest):
    action = req.action_type or req.command
    if action == "open_app_and_type":
        res = execute_system_command("open_app_and_type", req.app, req.text)
        if res.get("status") == "success":
            return res
        else:
            raise HTTPException(status_code=500, detail=res.get("message"))
            
    cmd = req.command.strip().lower()
    
    # Mapping friendly commands to Windows execution commands
    command_mapping = {
        "open_notepad": ["notepad.exe"],
        "open_calc": ["calc.exe"],
        "open_calculator": ["calc.exe"],
        "open_explorer": ["explorer.exe"],
        "open_vscode": ["cmd.exe", "/c", "code"],
        "open_volume": ["sndvol.exe"],
        "adjust_volume": ["sndvol.exe"]
    }
    
    executable = command_mapping.get(cmd)
    
    if executable:
        try:
            subprocess.Popen(executable)
            return {"status": "success", "executed_command": cmd}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to execute {cmd}: {str(e)}")
    else:
        return {
            "status": "error", 
            "message": f"Command '{cmd}' is unauthorized or unsupported. Supported commands: open_notepad, open_calc, open_explorer, open_vscode, open_volume"
        }

@app.get("/api/status")
async def get_status():
    try:
        from backend.desktop_agent import get_desktop_status
        from backend.browser_agent import PlaywrightBrowserAgent
        
        desktop_status = get_desktop_status()
        browser_status = await PlaywrightBrowserAgent().get_browser_status()
        
        return {
            "status": "success",
            "desktop": desktop_status,
            "browser": browser_status
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

# Serve frontend static files
app.mount("/static", StaticFiles(directory="frontend"), name="static")

@app.get("/")
async def root():
    return FileResponse("frontend/index.html")
