"""
Qwen Code Queue Processor

This script monitors the queue directory for incoming requests,
sends them to Qwen Code, and writes responses back.

Usage:
    python queue_processor.py
"""

import asyncio
import json
import logging
import os
import signal
import sys
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any

from dotenv import load_dotenv

load_dotenv()

# Configuration
QUEUE_DIR = Path(os.getenv("QUEUE_DIR", "/tmp/qwen_queue"))
RESPONSES_DIR = Path(os.getenv("RESPONSES_DIR", "/tmp/qwen_responses"))
QWEN_CODE_API_URL = os.getenv("QWEN_CODE_API_URL", "")
POLL_INTERVAL = float(os.getenv("POLL_INTERVAL", "1.0"))

# Create directories
QUEUE_DIR.mkdir(parents=True, exist_ok=True)
RESPONSES_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Global flag for graceful shutdown
running = True


def signal_handler(sig, frame):
    """Handle shutdown signals."""
    global running
    logger.info("Shutdown signal received...")
    running = False


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


async def process_with_qwen_cli(request_data: Dict[str, Any]) -> Optional[str]:
    """
    Process request using Qwen Code CLI.
    """
    prompt = request_data.get("prompt", "")
    history = request_data.get("history", [])
    
    # Build context from history
    context = ""
    for msg in history[-5:]:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        context += f"{role}: {content}\n"
    
    logger.info(f"Sending to Qwen Code: {prompt[:100]}...")
    
    try:
        # Use full path to qwen CLI
        qwen_path = "/home/codespace/nvm/current/bin/qwen"
        
        # Use qwen CLI with stdin
        proc = await asyncio.create_subprocess_exec(
            qwen_path,
            "--no-sandbox",  # Run without sandbox for Codespaces
            prompt,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        # Send context via stdin if available
        stdin_data = context.encode('utf-8') if context else None
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input=stdin_data),
            timeout=120
        )
        
        if proc.returncode == 0:
            response = stdout.decode('utf-8').strip()
            logger.info(f"Qwen Code response received ({len(response)} chars)")
            return response
        else:
            error_msg = stderr.decode('utf-8')
            logger.error(f"Qwen CLI error ({proc.returncode}): {error_msg}")
            # Return partial response even on error
            partial = stdout.decode('utf-8').strip()
            if partial:
                return partial
            return f"Error: {error_msg}"
            
    except FileNotFoundError:
        logger.warning("qwen CLI not found, trying without full path")
        return None
    except asyncio.TimeoutError:
        logger.error("Qwen CLI timeout (120s)")
        return "⏱ Превышено время ожидания ответа от Qwen Code"
    except Exception as e:
        logger.exception(f"Error in subprocess: {e}")
        return None


async def process_with_qwen_api(request_data: Dict[str, Any]) -> Optional[str]:
    """Process request using direct Qwen Code API (if configured)."""
    if not QWEN_CODE_API_URL:
        return None
    
    import aiohttp
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                QWEN_CODE_API_URL,
                json=request_data,
                timeout=aiohttp.ClientTimeout(total=120)
            ) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    return result.get('response', result.get('answer', str(result)))
                else:
                    logger.error(f"Qwen API error: {resp.status}")
                    return None
    except Exception as e:
        logger.exception(f"Error calling Qwen API: {e}")
        return None


def generate_mock_response(request_data: Dict[str, Any]) -> str:
    """
    Generate a mock response for testing.
    """
    prompt = request_data.get("prompt", "")
    
    return f"""🤖 **Qwen Code (тестовый режим)**

Получен ваш запрос:
> {prompt}

---

Это демонстрационный ответ. Для реальной работы:

**Вариант 1: Qwen Code CLI**
```bash
npm install -g @qwen-code/qwen-code
```

**Вариант 2: API**
Установите `QWEN_CODE_API_URL` в `.env`

---
*Запрос обработан: {datetime.now().strftime('%H:%M:%S')}*
"""


async def process_request(request_file: Path):
    """Process a single request file."""
    request_id = request_file.stem
    
    try:
        # Read request
        with open(request_file, "r", encoding="utf-8") as f:
            request_data = json.load(f)
        
        user_id = request_data.get("user_id", "unknown")
        prompt = request_data.get("prompt", "")
        
        logger.info(f"📥 Processing request {request_id} from user {user_id}")
        logger.info(f"   Prompt: {prompt[:50]}...")
        
        # Try different methods in order
        response_text = None
        
        # 1. Try CLI first
        if response_text is None:
            logger.info("   Trying Qwen Code CLI...")
            response_text = await process_with_qwen_cli(request_data)
        
        # 2. Try API
        if not response_text and QWEN_CODE_API_URL:
            logger.info("   Trying Qwen Code API...")
            response_text = await process_with_qwen_api(request_data)
        
        # 3. Fallback to mock
        if not response_text:
            logger.info("   Using mock response (no Qwen available)")
            response_text = generate_mock_response(request_data)
        
        # Write response
        response_data = {
            "id": request_id,
            "user_id": user_id,
            "response": response_text,
            "timestamp": datetime.now().isoformat(),
            "status": "completed"
        }
        
        response_file = RESPONSES_DIR / f"{request_id}.json"
        with open(response_file, "w", encoding="utf-8") as f:
            json.dump(response_data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"✅ Response written for request {request_id}")
        
        # Clean up request file
        try:
            request_file.unlink()
            logger.info(f"   Cleaned up request file")
        except:
            pass
            
    except Exception as e:
        logger.exception(f"❌ Error processing request {request_id}: {e}")
        
        # Write error response
        error_data = {
            "id": request_id,
            "error": str(e),
            "timestamp": datetime.now().isoformat(),
            "status": "error"
        }
        
        response_file = RESPONSES_DIR / f"{request_id}.json"
        try:
            with open(response_file, "w", encoding="utf-8") as f:
                json.dump(error_data, f, ensure_ascii=False, indent=2)
        except:
            pass


async def monitor_queue():
    """Monitor queue directory and process requests."""
    logger.info("=" * 50)
    logger.info("Qwen Code Queue Processor Started")
    logger.info("=" * 50)
    logger.info(f"Queue directory: {QUEUE_DIR}")
    logger.info(f"Responses directory: {RESPONSES_DIR}")
    logger.info(f"Poll interval: {POLL_INTERVAL}s")
    logger.info("=" * 50)
    
    while running:
        # Find all request files
        request_files = list(QUEUE_DIR.glob("*.json"))
        
        if request_files:
            logger.info(f"📋 Found {len(request_files)} pending request(s)")
        
        for request_file in request_files:
            if not running:
                break
            await process_request(request_file)
        
        # Wait before next poll
        await asyncio.sleep(POLL_INTERVAL)
    
    logger.info("Queue processor stopped")


async def main():
    try:
        await monitor_queue()
    except Exception as e:
        logger.exception(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
