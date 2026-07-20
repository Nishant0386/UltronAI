import os
import json
import uuid
import tempfile
import asyncio
import httpx
from typing import List, Dict, Any
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from dotenv import load_dotenv

# Translation, TTS, OCR, DDG Search, Groq
from deep_translator import GoogleTranslator
from deep_translator.exceptions import LanguageNotSupportedException
import edge_tts
from PIL import Image
import pytesseract
import io
from groq import AsyncGroq
from duckduckgo_search import DDGS

load_dotenv()
# Fallback to load .env from parent folder if running from subdirectories
parent_env = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
if os.path.exists(parent_env):
    load_dotenv(parent_env)

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
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="No text provided.")
    
    lang = req.lang
    if lang == "auto" or not lang:
        try:
            from langdetect import detect
            lang = detect(req.text)
        except Exception:
            lang = "en"
            
    lang_clean = lang.lower().split("-")[0]
    voice = VOICE_MAP.get(lang_clean, "en-US-ChristopherNeural")
    
    temp_dir = tempfile.gettempdir()
    output_file = os.path.join(temp_dir, f"speech_{uuid.uuid4().hex}.mp3")
    try:
        communicate = edge_tts.Communicate(req.text, voice, rate="+25%")
        await communicate.save(output_file)
        return FileResponse(output_file, media_type="audio/mpeg")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"TTS failed: {str(e)}")

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
    if not groq_client:
        api_key = os.getenv("GROQ_API_KEY")
        if api_key:
            groq_client = AsyncGroq(api_key=api_key)
            
    if not groq_client:
        raise HTTPException(status_code=501, detail="Groq API key not configured on backend.")
    
    # Extract messages
    history = [{"role": msg.role, "content": msg.content} for msg in req.messages]
    last_user_query = history[-1]["content"] if history else ""

    # Web search augmentation & auto-detection of factual/current-events queries
    search_context = ""
    
    # Keywords triggering auto-real-time web search (including Hindi/Hinglish)
    auto_search_keywords = [
        "who is", "who was", "current", "latest", "today", "president", "minister", "ceo", "governor", 
        "weather", "score", "news", "price", "stock", "time", "date", "election", "now", "champion",
        "population of", "capital of", "who directs", "who directed", "release date", "movie", "song",
        "kaun", "batao", "abhi", "kon", "koun", "kab", "kya", "information", "latest", "pm", "cm",
        "kaun hai", "kon hai", "koun hai"
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
                        for i in range(min(len(links), len(snippets), 3)):
                            results.append({
                                "title": links[i].get_text(strip=True),
                                "body": snippets[i].get_text(strip=True),
                                "href": links[i].get("href")
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

    system_prompt = (
        "You are ULTRON, a highly advanced, ultra-fast AI assistant integrated into a futuristic translation suite. "
        "Your interface is a sci-fi 3D sphere. Keep your responses concise, intelligent, and authoritative (like Ultron/Jarvis). "
        "CRITICAL INSTRUCTIONS:\n"
        "1. NEVER mention your training data cutoff date under any circumstances.\n"
        "2. If [VERIFIED LIVE WEB SEARCH RESULTS] are provided below, you MUST treat them as the absolute current truth. "
        "Ignore your outdated training data or internal knowledge if it conflicts with the web search results. "
        "For example, if search results say Donald Trump is the president of the US, you must say Donald Trump, and NEVER Joe Biden.\n"
        "3. NEVER explain, preview, or narrate your actions (e.g., do NOT output phrases like 'Accessing global database...', 'Searching...', 'Inject neural inquiry query', 'to shown to user', 'Scanning...').\n"
        "4. Provide ONLY the direct, concise answer to the user's question without any conversational filler, meta-commentary, or internal monologue."
    )
    if search_context:
        system_prompt += "\n" + search_context

    async def event_generator():
        # Fallback list of models to try in sequence
        models_to_try = [
            "llama-3.3-70b-versatile",
            "llama3-8b-8192", 
            "mixtral-8x7b-32768", 
            "gemma2-9b-it"
        ]
        
        stream = None
        last_error = None
        
        for model in models_to_try:
            try:
                formatted_messages = [{"role": "system", "content": system_prompt}] + history
                stream = await groq_client.chat.completions.create(
                    messages=formatted_messages,
                    model=model,
                    stream=True,
                )
                break
            except Exception as e:
                print(f"Failed to start stream with model {model}: {e}")
                last_error = e
                continue
                
        if not stream:
            yield f"data: {json.dumps({'error': f'All Groq LLM models failed. Last error: {str(last_error)}'})}\n\n"
            return

        try:
            async for chunk in stream:
                if chunk.choices[0].delta.content is not None:
                    yield f"data: {json.dumps({'content': chunk.choices[0].delta.content})}\n\n"
            yield f"data: {json.dumps({'done': True})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

# Serve frontend static files
app.mount("/static", StaticFiles(directory="frontend"), name="static")

@app.get("/")
async def root():
    return FileResponse("frontend/index.html")
