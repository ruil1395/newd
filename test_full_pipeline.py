"""
Test script for full pipeline: Voice → STT → Queue → Qwen Code → Response
"""

import asyncio
import json
import uuid
from pathlib import Path
from datetime import datetime

QUEUE_DIR = Path("/tmp/qwen_queue")
RESPONSES_DIR = Path("/tmp/qwen_responses")

async def test_queue_to_qwen():
    """Test sending request through queue and getting Qwen response."""
    
    print("=" * 60)
    print("Testing Full Pipeline: Queue → Qwen Code")
    print("=" * 60)
    
    # Create test request
    request_id = str(uuid.uuid4())
    test_request = {
        "id": request_id,
        "user_id": 999999,
        "prompt": "Напиши простую функцию на Python для сложения двух чисел",
        "history": [],
        "timestamp": datetime.now().isoformat()
    }
    
    QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    request_file = QUEUE_DIR / f"{request_id}.json"
    
    print(f"\n1. Creating request file: {request_file.name}")
    with open(request_file, "w", encoding="utf-8") as f:
        json.dump(test_request, f, ensure_ascii=False, indent=2)
    print(f"   ✓ Request created")
    
    # Wait for queue processor
    print(f"\n2. Waiting for queue processor...")
    response_file = RESPONSES_DIR / f"{request_id}.json"
    
    max_wait = 60  # seconds
    waited = 0
    while waited < max_wait:
        await asyncio.sleep(1)
        waited += 1
        
        if response_file.exists():
            print(f"   ✓ Response received after {waited}s")
            break
        
        if waited % 10 == 0:
            print(f"   ... waiting ({waited}s)")
    
    if not response_file.exists():
        print(f"   ❌ Timeout! No response after {max_wait}s")
        # Cleanup
        if request_file.exists():
            request_file.unlink()
        return False
    
    # Read response
    print(f"\n3. Reading response...")
    with open(response_file, "r", encoding="utf-8") as f:
        response_data = json.load(f)
    
    response_text = response_data.get("response", "")
    print(f"   ✓ Response length: {len(response_text)} chars")
    
    # Show response preview
    print(f"\n4. Response preview:")
    print("-" * 60)
    print(response_text[:500])
    if len(response_text) > 500:
        print("...")
    print("-" * 60)
    
    # Cleanup
    if request_file.exists():
        request_file.unlink()
    if response_file.exists():
        response_file.unlink()
    
    print(f"\n✓ Test completed successfully!")
    return True


if __name__ == "__main__":
    asyncio.run(test_queue_to_qwen())
