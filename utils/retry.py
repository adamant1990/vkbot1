import asyncio
from functools import wraps
import logging

logger = logging.getLogger(__name__)

def retry_on_error(max_retries=3, base_delay=1):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    delay = base_delay * (2 ** attempt)
                    logger.warning(f"Retry {attempt+1}/{max_retries} after error: {e}")
                    await asyncio.sleep(delay)
            raise last_exception
        return wrapper
    return decorator