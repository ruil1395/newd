"""
Debug script for Vosk STT
"""
import io
import wave
import json
from pathlib import Path

from vosk import Model, KaldiRecognizer

print("=" * 50)
print("Vosk STT Debug Test")
print("=" * 50)

# Check model path
model_path = Path("./vosk-model-ru")
print(f"\n1. Checking model path: {model_path}")
print(f"   Exists: {model_path.exists()}")

if not model_path.exists():
    print("   ❌ Model not found!")
    exit(1)

# List model files
print("\n2. Model files:")
for f in list(model_path.glob("**/*"))[:10]:
    if f.is_file():
        print(f"   - {f.relative_to(model_path)}")

# Load model
print("\n3. Loading model...")
try:
    model = Model(str(model_path))
    print("   ✅ Model loaded successfully!")
except Exception as e:
    print(f"   ❌ Error loading model: {e}")
    exit(1)

# Test with sample recognition
print("\n4. Testing recognizer...")
try:
    recognizer = KaldiRecognizer(model, 16000)
    print("   ✅ Recognizer created (16kHz)")
except Exception as e:
    print(f"   ❌ Error creating recognizer: {e}")
    exit(1)

# Test with empty data (should not crash)
print("\n5. Testing with sample data...")
try:
    # Create a simple test - just check if accept waveform works
    test_data = b'\x00' * 4000  # 4000 bytes of silence
    result = recognizer.AcceptWaveform(test_data)
    print(f"   ✅ AcceptWaveform works (result: {result})")
    
    final = recognizer.FinalResult()
    print(f"   ✅ FinalResult: {final}")
except Exception as e:
    print(f"   ❌ Error during recognition: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 50)
print("Vosk STT is READY!")
print("=" * 50)
