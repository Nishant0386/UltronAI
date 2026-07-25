from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
import edge_tts
import tempfile
import os
import uuid
import io
import asyncio

router = APIRouter()

# ─── Modi Voice Reference MP3 path ────────────────────────────────────────────
MODI_AUDIO_PATH = r"C:\Users\nisha\Downloads\bearing-translate (1)\ultron-translate\PM Modi's big message to sportspersons for the Olympics 2036 #shorts - Narendra Modi (128k).mp3"

# ─── Lazy-loaded models (cached after first call) ─────────────────────────────
_models_loaded = False
_processor = _tts_model = _vocoder = _speaker_embeddings = None

def _load_models():
    global _models_loaded, _processor, _tts_model, _vocoder, _speaker_embeddings
    if _models_loaded:
        return _processor is not None

    _models_loaded = True
    try:
        import torch
        from transformers import SpeechT5Processor, SpeechT5ForTextToSpeech, SpeechT5HifiGan
        from datasets import load_dataset
        import librosa, soundfile

        print("[MODI TTS]: Loading SpeechT5 model (first run downloads ~500MB)…")
        _processor = SpeechT5Processor.from_pretrained("microsoft/speecht5_tts")
        _tts_model = SpeechT5ForTextToSpeech.from_pretrained("microsoft/speecht5_tts")
        _vocoder   = SpeechT5HifiGan.from_pretrained("microsoft/speecht5_hifigan")

        # ── Extract speaker embedding from Modi MP3 using librosa ──────────────
        if os.path.exists(MODI_AUDIO_PATH):
            print("[MODI TTS]: Extracting speaker embedding from Modi MP3…")
            wav, sr = librosa.load(MODI_AUDIO_PATH, sr=16000, mono=True, duration=30.0)
            # Create a basic speaker embedding from mel-spectrogram statistics
            # (mean + std across 256 freq bins → concat → 512-dim vector)
            import numpy as np
            mel = librosa.feature.melspectrogram(y=wav, sr=sr, n_mels=256)
            mel_db = librosa.power_to_db(mel, ref=np.max)
            emb = np.concatenate([mel_db.mean(axis=1), mel_db.std(axis=1)]).astype(np.float32)
            emb = emb / (np.linalg.norm(emb) + 1e-8)           # L2 normalise
            _speaker_embeddings = torch.tensor(emb).unsqueeze(0)  # [1, 512]
            print("[MODI TTS]: Speaker embedding ready!")
        else:
            # Use a warm, deep male CMU-Arctic speaker embedding as fallback
            from datasets import load_dataset
            emb_ds = load_dataset("Matthijs/cmu-arctic-xvectors", split="validation")
            # Index 7306 = "bdl" (deep American male voice, closest to Modi timbre)
            _speaker_embeddings = torch.tensor(emb_ds[7306]["xvector"]).unsqueeze(0)
            print("[MODI TTS]: Using CMU-Arctic speaker embedding (Modi MP3 not found).")

        return True
    except Exception as e:
        print(f"[MODI TTS]: Model load failed: {e}")
        return False


def _generate_with_speecht5(text: str) -> bytes | None:
    """Generate speech using Microsoft SpeechT5 with Modi-derived speaker embedding."""
    try:
        import torch, soundfile, numpy as np

        if not _load_models() or _processor is None:
            return None

        # SpeechT5 handles English best; trim to 450 chars to avoid OOM
        safe_text = text[:450]

        inputs  = _processor(text=safe_text, return_tensors="pt")
        with torch.no_grad():
            speech = _tts_model.generate_speech(
                inputs["input_ids"], _speaker_embeddings, vocoder=_vocoder
            )

        buf = io.BytesIO()
        soundfile.write(buf, speech.numpy(), samplerate=16000, format="WAV")
        buf.seek(0)
        return buf.read()
    except Exception as e:
        print(f"[MODI TTS]: SpeechT5 generation error: {e}")
        return None


# ─── Language detection ───────────────────────────────────────────────────────
def _detect_lang(text: str) -> str:
    try:
        from langdetect import detect
        return detect(text)
    except Exception:
        return "en"

# ─── Edge-TTS voice map ───────────────────────────────────────────────────────
VOICE_MAP = {
    "en": "en-US-ChristopherNeural",
    "es": "es-ES-AlvaroNeural",
    "fr": "fr-FR-HenriNeural",
    "de": "de-DE-KillianNeural",
    "it": "it-IT-DiegoNeural",
    "ja": "ja-JP-KeitaNeural",
    "hi": "hi-IN-MadhurNeural",
    "zh-CN": "zh-CN-YunxiNeural",
    "zh":    "zh-CN-YunxiNeural",
    "ko": "ko-KR-HyunsuNeural",
    "ar": "ar-AE-HamdanNeural",
}

import base64

class SpeakRequest(BaseModel):
    text: str
    lang: str = "auto"
    use_modi_voice: bool = True

@router.post("/speak")
async def speak_text(req: SpeakRequest):
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="No text to speak.")

    # ── PRIORITY 1: Modi voice via SpeechT5 ────
    if req.use_modi_voice:
        try:
            audio_bytes = await asyncio.to_thread(_generate_with_speecht5, req.text)
            if audio_bytes:
                b64 = base64.b64encode(audio_bytes).decode("utf-8")
                return {
                    "status": "success",
                    "audio_base64": f"data:audio/wav;base64,{b64}",
                    "media_type": "audio/wav"
                }
        except Exception as e:
            print(f"[MODI TTS]: SpeechT5 failed, using Edge-TTS fallback: {e}")

    # ── PRIORITY 2: Edge-TTS fallback (always works) ──────────────────────────
    lang  = req.lang if req.lang != "auto" else _detect_lang(req.text)
    voice = VOICE_MAP.get(lang, "en-US-ChristopherNeural")

    output_file = os.path.join(tempfile.gettempdir(), f"speech_{uuid.uuid4().hex}.mp3")
    try:
        communicate = edge_tts.Communicate(req.text, voice, rate="+10%")
        await communicate.save(output_file)
        with open(output_file, "rb") as f:
            b64_audio = base64.b64encode(f.read()).decode("utf-8")
        try:
            os.remove(output_file)
        except Exception:
            pass
        return {
            "status": "success",
            "audio_base64": f"data:audio/mpeg;base64,{b64_audio}",
            "media_type": "audio/mpeg"
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"TTS failed: {str(e)}")
