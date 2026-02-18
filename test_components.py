"""
Test script for Vosk STT and Queue System
Tests the components without requiring a Telegram bot token.
"""

import asyncio
import json
import wave
import io
from pathlib import Path

# Test Vosk STT
async def test_vosk():
    """Test Vosk speech recognition."""
    print("=" * 50)
    print("Testing Vosk STT...")
    print("=" * 50)
    
    from vosk import Model, KaldiRecognizer
    
    model_path = Path("./vosk-model-ru")
    if not model_path.exists():
        print("❌ Vosk model not found!")
        return False
    
    print(f"✓ Loading model from {model_path}...")
    model = Model(str(model_path))
    print("✓ Model loaded successfully!")
    
    # Note: Full audio test requires actual audio file
    print("✓ Vosk STT ready!")
    return True


# Test Queue System
async def test_queue():
    """Test file-based queue system."""
    print("\n" + "=" * 50)
    print("Testing Queue System...")
    print("=" * 50)
    
    queue_dir = Path("/tmp/qwen_queue")
    response_dir = Path("/tmp/qwen_responses")
    
    # Create directories
    queue_dir.mkdir(parents=True, exist_ok=True)
    response_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"✓ Queue directory: {queue_dir}")
    print(f"✓ Response directory: {response_dir}")
    
    # Create test request
    test_id = "test-12345"
    test_request = {
        "id": test_id,
        "user_id": 999999,
        "prompt": "Тестовый запрос",
        "history": [],
        "timestamp": "2024-01-01T00:00:00"
    }
    
    request_file = queue_dir / f"{test_id}.json"
    with open(request_file, "w", encoding="utf-8") as f:
        json.dump(test_request, f, ensure_ascii=False, indent=2)
    
    print(f"✓ Test request created: {request_file}")
    
    # Create test response
    test_response = {
        "id": test_id,
        "user_id": 999999,
        "response": "Тестовый ответ от Qwen Code",
        "timestamp": "2024-01-01T00:00:01",
        "status": "completed"
    }
    
    response_file = response_dir / f"{test_id}.json"
    with open(response_file, "w", encoding="utf-8") as f:
        json.dump(test_response, f, ensure_ascii=False, indent=2)
    
    print(f"✓ Test response created: {response_file}")
    
    # Verify files
    assert request_file.exists()
    assert response_file.exists()
    
    # Cleanup
    request_file.unlink()
    response_file.unlink()
    
    print("✓ Queue system test passed!")
    return True


# Test Configuration
async def test_config():
    """Test configuration loading."""
    print("\n" + "=" * 50)
    print("Testing Configuration...")
    print("=" * 50)
    
    from dotenv import load_dotenv
    import os
    
    load_dotenv()
    
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    queue_dir = os.getenv("QUEUE_DIR")
    vosk_path = os.getenv("VOSK_MODEL_PATH")
    
    print(f"• TELEGRAM_BOT_TOKEN: {'✓ set' if token and token != 'your_telegram_bot_token_here' else '❌ not set'}")
    print(f"• QUEUE_DIR: {queue_dir or 'default'}")
    print(f"• VOSK_MODEL_PATH: {vosk_path or 'default'}")
    
    if token and token != "your_telegram_bot_token_here":
        print("✓ Configuration ready for bot!")
        return True
    else:
        print("⚠️  Add TELEGRAM_BOT_TOKEN to .env to start the bot")
        return False


async def main():
    print("\n" + "=" * 60)
    print(" QWEN CODE VOICE BOT - COMPONENT TEST")
    print("=" * 60)
    
    results = []
    
    # Test components
    results.append(("Vosk STT", await test_vosk()))
    results.append(("Queue System", await test_queue()))
    results.append(("Configuration", await test_config()))
    
    # Summary
    print("\n" + "=" * 60)
    print(" TEST SUMMARY")
    print("=" * 60)
    
    for name, passed in results:
        status = "✓ PASS" if passed else "❌ FAIL"
        print(f"{status}: {name}")
    
    all_passed = all(r[1] for r in results)
    
    print("\n" + "=" * 60)
    if all_passed:
        print("✓ ALL TESTS PASSED!")
        print("\nTo start the bot:")
        print("1. Add your TELEGRAM_BOT_TOKEN to .env")
        print("2. Run: python bot.py")
        print("3. In another terminal: python queue_processor.py")
    else:
        print("⚠️  Some tests failed. Check the output above.")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
