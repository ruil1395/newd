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
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any

import aiohttp
from dotenv import load_dotenv

load_dotenv()

# Configuration
QUEUE_DIR = Path(os.getenv("QUEUE_DIR", "/tmp/qwen_queue"))
RESPONSES_DIR = Path(os.getenv("RESPONSES_DIR", "/tmp/qwen_responses"))
QWEN_CODE_API_URL = os.getenv("QWEN_CODE_API_URL", "")  # Optional: direct API
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


async def process_with_qwen_api(request_data: Dict[str, Any]) -> Optional[str]:
    """Process request using direct Qwen Code API (if configured)."""
    if not QWEN_CODE_API_URL:
        return None
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                QWEN_CODE_API_URL,
                json=request_data,
                timeout=aiohttp.ClientTimeout(total=60)
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


async def process_with_subprocess(request_data: Dict[str, Any]) -> Optional[str]:
    """
    Process request by calling Qwen Code CLI.
    
    This is a placeholder - adjust based on your Qwen Code setup.
    """
    prompt = request_data.get("prompt", "")
    history = request_data.get("history", [])
    
    # Build context from history
    context = ""
    for msg in history[-5:]:  # Last 5 messages
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        context += f"{role}: {content}\n"
    
    # Create a temporary file with the prompt
    import tempfile
    
    try:
        # Example: call qwen-code CLI if available
        # Adjust this based on your actual Qwen Code installation
        proc = await asyncio.create_subprocess_exec(
            "qwen-code",  # or full path to CLI
            "--prompt", prompt,
            "--context", context,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
        
        if proc.returncode == 0:
            return stdout.decode('utf-8').strip()
        else:
            logger.error(f"Qwen CLI error: {stderr.decode('utf-8')}")
            return None
            
    except FileNotFoundError:
        logger.warning("qwen-code CLI not found, using mock response")
        return generate_mock_response(prompt)
    except asyncio.TimeoutError:
        logger.error("Qwen CLI timeout")
        return None
    except Exception as e:
        logger.exception(f"Error in subprocess: {e}")
        return None


def generate_mock_response(prompt: str) -> str:
    """
    Generate a mock response for testing.
    Replace this with actual Qwen Code integration.
    """
    return f"""[Qwen Code Response]

Получен запрос: {prompt}

Это демонстрационный ответ. Для реальной работы настройте интеграцию:

1. **Вариант A: Direct API**
   Установите QWEN_CODE_API_URL в .env
   
2. **Вариант B: CLI**
   Установите qwen-code CLI: npm install -g @qwen-code/qwen-code

3. **Вариант C: Custom processor**
   Отредактируйте queue_processor.py и добавьте свою логику

---
Запрос обработан в: {datetime.now().isoformat()}
"""


async def process_request(request_file: Path):
    """Process a single request file."""
    request_id = request_file.stem
    
    try:
        # Read request
        with open(request_file, "r", encoding="utf-8") as f:
            request_data = json.load(f)
        
        logger.info(f"Processing request {request_id} from user {request_data.get('user_id')}")
        
        # Process with Qwen Code (try API first, then CLI, then mock)
        response_text = await process_with_qwen_api(request_data)
        
        if not response_text:
            response_text = await process_with_subprocess(request_data)
        
        if not response_text:
            response_text = generate_mock_response(request_data.get("prompt", ""))
        
        # Write response
        response_data = {
            "id": request_id,
            "user_id": request_data.get("user_id"),
            "response": response_text,
            "timestamp": datetime.now().isoformat(),
            "status": "completed"
        }
        
        response_file = RESPONSES_DIR / f"{request_id}.json"
        with open(response_file, "w", encoding="utf-8") as f:
            json.dump(response_data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"Response written for request {request_id}")
        
        # Clean up request file
        try:
            request_file.unlink()
        except:
            pass
            
    except Exception as e:
        logger.exception(f"Error processing request {request_id}: {e}")
        
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
    logger.info(f"Queue processor started")
    logger.info(f"Queue directory: {QUEUE_DIR}")
    logger.info(f"Responses directory: {RESPONSES_DIR}")
    
    while running:
        # Find all request files
        request_files = list(QUEUE_DIR.glob("*.json"))
        
        for request_file in request_files:
            if not running:
                break
            await process_request(request_file)
        
        # Wait before next poll
        await asyncio.sleep(POLL_INTERVAL)
    
    logger.info("Queue processor stopped")


async def main():
    logger.info("=" * 50)
    logger.info("Qwen Code Queue Processor")
    logger.info("=" * 50)
    
    try:
        await monitor_queue()
    except Exception as e:
        logger.exception(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
