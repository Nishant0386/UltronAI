import os
from faster_whisper import WhisperModel
import asyncio

# Load the model once when the service starts
# Options: tiny, base, small, medium, large-v3
# Download will happen automatically on first run
MODEL_SIZE = os.getenv("WHISPER_MODEL", "base")
print(f"Loading faster-whisper model: {MODEL_SIZE}")

# Initialize model (cpu by default since we don't assume GPU on windows, though it will use GPU if available and cuDNN is installed)
model = WhisperModel(MODEL_SIZE, device="cpu", compute_type="int8")

def transcribe_sync(audio_path: str, language: str = None) -> str:
    """
    Synchronously transcribe an audio file.
    If language is 'auto' or None, it will detect it.
    """
    lang_param = None if language == "auto" else language
    segments, info = model.transcribe(audio_path, beam_size=5, language=lang_param)
    
    # segments is a generator, so we must iterate
    transcript = " ".join([segment.text for segment in segments])
    return transcript.strip()

async def transcribe_async(audio_path: str, language: str = None) -> str:
    """Async wrapper for transcription."""
    return await asyncio.to_thread(transcribe_sync, audio_path, language)
