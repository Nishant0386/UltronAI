from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
import edge_tts
import tempfile
import os
import uuid

router = APIRouter()

class SpeakRequest(BaseModel):
    text: str
    lang: str = "en"

# Map simple language codes to edge-tts voices
VOICE_MAP = {
    "en": "en-US-ChristopherNeural", # A good deep voice for "Ultron" feel
    "es": "es-ES-AlvaroNeural",
    "fr": "fr-FR-HenriNeural",
    "de": "de-DE-KillianNeural",
    "it": "it-IT-DiegoNeural",
    "ja": "ja-JP-KeitaNeural",
    "hi": "hi-IN-MadhurNeural",
    "zh-CN": "zh-CN-YunxiNeural"
}

@router.post("/speak")
async def speak_text(req: SpeakRequest):
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="No text to speak.")
        
    voice = VOICE_MAP.get(req.lang, "en-US-ChristopherNeural")
    
    # Generate temporary file path
    temp_dir = tempfile.gettempdir()
    output_file = os.path.join(temp_dir, f"speech_{uuid.uuid4().hex}.mp3")
    
    try:
        communicate = edge_tts.Communicate(req.text, voice, rate="+25%") # Faster rate for futuristic feel
        await communicate.save(output_file)
        
        return FileResponse(output_file, media_type="audio/mpeg")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"TTS generation failed: {str(e)}")
