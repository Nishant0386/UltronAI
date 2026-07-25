"""
Run this ONCE after installing dependencies to pre-download the SpeechT5 model
and verify Modi voice works.

Requirements (pure Python, no C++ needed):
    pip install torch --index-url https://download.pytorch.org/whl/cpu
    pip install transformers soundfile librosa datasets

Modi MP3 path used for speaker embedding extraction:
    C:\\Users\\nisha\\Downloads\\bearing-translate (1)\\ultron-translate\\PM Modi's big message to sportspersons for the Olympics 2036 #shorts - Narendra Modi (128k).mp3
"""
import os, io, sys

MODI_AUDIO_PATH = r"C:\Users\nisha\Downloads\bearing-translate (1)\ultron-translate\PM Modi's big message to sportspersons for the Olympics 2036 #shorts - Narendra Modi (128k).mp3"

print("=" * 65)
print("ULTRON OS — Modi Voice Setup (SpeechT5 + librosa, no C++ needed)")
print("=" * 65)

# 1. Check Modi MP3
if not os.path.exists(MODI_AUDIO_PATH):
    print(f"\n[ERROR]: Modi MP3 not found:\n  {MODI_AUDIO_PATH}")
    sys.exit(1)
print(f"\n[OK]: Modi MP3 found.")

# 2. Check dependencies
print("\n[INFO]: Checking dependencies...")
missing = []
for pkg in ["torch", "transformers", "soundfile", "librosa", "datasets"]:
    try:
        __import__(pkg)
        print(f"  [OK] {pkg}")
    except ImportError:
        print(f"  [MISSING] {pkg}")
        missing.append(pkg)

if missing:
    print(f"\n[ERROR]: Missing packages: {', '.join(missing)}")
    print("Run:")
    if "torch" in missing:
        print("  pip install torch --index-url https://download.pytorch.org/whl/cpu")
    others = [p for p in missing if p != "torch"]
    if others:
        print(f"  pip install {' '.join(others)}")
    sys.exit(1)

# 3. Load models & generate test audio
print("\n[INFO]: Loading SpeechT5 model (may download ~500MB on first run)...")
import torch, librosa, soundfile, numpy as np
from transformers import SpeechT5Processor, SpeechT5ForTextToSpeech, SpeechT5HifiGan

processor = SpeechT5Processor.from_pretrained("microsoft/speecht5_tts")
model     = SpeechT5ForTextToSpeech.from_pretrained("microsoft/speecht5_tts")
vocoder   = SpeechT5HifiGan.from_pretrained("microsoft/speecht5_hifigan")
print("[OK]: Model loaded!")

print("\n[INFO]: Extracting Modi speaker embedding from MP3...")
wav, sr = librosa.load(MODI_AUDIO_PATH, sr=16000, mono=True, duration=30.0)
mel    = librosa.feature.melspectrogram(y=wav, sr=sr, n_mels=256)
mel_db = librosa.power_to_db(mel, ref=np.max)
emb    = np.concatenate([mel_db.mean(axis=1), mel_db.std(axis=1)]).astype(np.float32)
emb    = emb / (np.linalg.norm(emb) + 1e-8)
speaker_embeddings = torch.tensor(emb).unsqueeze(0)
print("[OK]: Embedding extracted!")

print("\n[INFO]: Generating test speech in Modi-style voice...")
test_text = "Namaste! I am Ultron, your personal AI Operating System. How can I assist you today?"
inputs = processor(text=test_text, return_tensors="pt")
with torch.no_grad():
    speech = model.generate_speech(inputs["input_ids"], speaker_embeddings, vocoder=vocoder)

out_path = "modi_test_output.wav"
soundfile.write(out_path, speech.numpy(), samplerate=16000)
print(f"[OK]: Test audio saved -> '{out_path}' - play it to verify the voice!")

print("\n" + "=" * 65)
print("SETUP COMPLETE! Modi voice is ready.")
print("Start Ultron with: python desktop_app.py")
print("=" * 65)
