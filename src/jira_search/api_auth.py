"""API Authentication and Rate Limiting for Jira Search."""

import time
import logging
from functools import wraps
from typing import Dict, Optional, Tuple
from flask import request, jsonify
from collections import defaultdict, deque

logger = logging.getLogger(__name__)


class RateLimiter:
    """Simple in-memory rate limiter."""

    def __init__(self):
        self.requests = defaultdict(deque)
        self.blocked_until = defaultdict(float)

    def is_allowed(
        self, key: str, limit: int = 60, window: int = 60
    ) -> Tuple[bool, Dict[str, int]]:
        """Check if request is allowed within rate limit.

        Args:
            key: Unique identifier (IP, API key, etc.)
            limit: Maximum requests per window
            window: Time window in seconds

        Returns:
            Tuple of (is_allowed, rate_limit_info)
        """
        now = time.time()

        # Check if currently blocked
        if key in self.blocked_until and now < self.blocked_until[key]:
            remaining_block_time = int(self.blocked_until[key] - now)
            return False, {
                "remaining": 0,
                "reset_time": int(self.blocked_until[key]),
                "blocked_for": remaining_block_time,
            }

        # Clean old requests outside the window
        requests = self.requests[key]
        while requests and requests[0] < now - window:
            requests.popleft()

        # Check if within limit
        if len(requests) >= limit:
            # Block for remaining window time
            oldest_request = requests[0]
            reset_time = oldest_request + window
            self.blocked_until[key] = reset_time

            return False, {
                "remaining": 0,
                "reset_time": int(reset_time),
                "blocked_for": int(reset_time - now),
            }

        # Allow request
        requests.append(now)
        remaining = limit - len(requests)
        reset_time = now + window

        return True, {
            "remaining": remaining,
            "reset_time": int(reset_time),
            "blocked_for": 0,
        }


class APIKeyManager:
    """Simple API key management."""

    def __init__(self):
        # In production, these would come from a database or config
        self.api_keys = {
            "example-dev-key": {
                "name": "Example Development Key",
                "created": "2025-01-01",
                "rate_limit": 120,  # requests per minute
                "enabled": True,
            },
            "example-prod-key": {
                "name": "Example Production Key",
                "created": "2025-01-01",
                "rate_limit": 300,  # requests per minute
                "enabled": True,
            },
        }

    def validate_key(self, api_key: str) -> Optional[Dict]:
        """Validate API key and return key info.

        Args:
            api_key: The API key to validate

        Returns:
            API key info if valid, None if invalid
        """
        if not api_key:
            return None

        key_info = self.api_keys.get(api_key)
        if key_info and key_info.get("enabled", False):
            return key_info

        return None

    def get_rate_limit(self, api_key: str) -> int:
        """Get rate limit for API key.

        Args:
            api_key: The API key

        Returns:
            Rate limit (requests per minute)
        """
        key_info = self.api_keys.get(api_key, {})
        return key_info.get("rate_limit", 60)  # Default 60 requests/minute


# Global instances
rate_limiter = RateLimiter()
api_key_manager = APIKeyManager()


def get_client_identifier() -> str:
    """Get unique identifier for rate limiting.

    Returns:
        Client identifier (API key or IP address)
    """
    # Try API key first
    api_key = request.headers.get("X-API-Key")
    if api_key and api_key_manager.validate_key(api_key):
        return f"api_key:{api_key}"

    # Fall back to IP address
    # Handle proxy headers
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        ip = forwarded_for.split(",")[0].strip()
    else:
        ip = request.remote_addr

    return f"ip:{ip}"


def get_rate_limit_for_client(client_id: str) -> int:
    """Get appropriate rate limit for client.

    Args:
        client_id: Client identifier

    Returns:
        Rate limit (requests per minute)
    """
    if client_id.startswith("api_key:"):
        api_key = client_id.split(":", 1)[1]
        return api_key_manager.get_rate_limit(api_key)
    else:
        # IP-based rate limit (lower than API key)
        return 30  # 30 requests per minute for anonymous users


def require_api_key(f):
    """Decorator to require valid API key."""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = request.headers.get("X-API-Key")

        if not api_key:
            return (
                jsonify(
                    {
                        "error": "API key required",
                        "message": "Include X-API-Key header with a valid API key",
                    }
                ),
                401,
            )

        key_info = api_key_manager.validate_key(api_key)
        if not key_info:
            return (
                jsonify(
                    {
                        "error": "Invalid API key",
                        "message": "The provided API key is invalid or disabled",
                    }
                ),
                401,
            )

        # Add key info to request context
        request.api_key_info = key_info

        return f(*args, **kwargs)

    return decorated_function


def apply_rate_limit(f):
    """Decorator to apply rate limiting."""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        client_id = get_client_identifier()
        rate_limit = get_rate_limit_for_client(client_id)

        allowed, rate_info = rate_limiter.is_allowed(
            client_id, limit=rate_limit, window=60  # 1 minute window
        )

        if not allowed:
            response = jsonify(
                {
                    "error": "Rate limit exceeded",
                    "message": f"Maximum {rate_limit} requests per minute allowed",
                    "retry_after": rate_info["blocked_for"],
                }
            )
            response.status_code = 429
            response.headers["X-RateLimit-Limit"] = str(rate_limit)
            response.headers["X-RateLimit-Remaining"] = str(rate_info["remaining"])
            response.headers["X-RateLimit-Reset"] = str(rate_info["reset_time"])
            response.headers["Retry-After"] = str(rate_info["blocked_for"])
            return response

        # Execute the function
        result = f(*args, **kwargs)

        # Add rate limit headers to successful responses
        if hasattr(result, "headers"):
            result.headers["X-RateLimit-Limit"] = str(rate_limit)
            result.headers["X-RateLimit-Remaining"] = str(rate_info["remaining"])
            result.headers["X-RateLimit-Reset"] = str(rate_info["reset_time"])

        return result

    return decorated_function


def conditional_rate_limit(config):
    """Decorator factory that conditionally applies rate limiting based on config."""

    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Check if rate limiting is enabled in config
            if not config.api_enable_rate_limiting:
                # Rate limiting disabled, execute function directly
                return f(*args, **kwargs)

            # Rate limiting enabled, apply normal rate limiting logic
            client_id = get_client_identifier()
            rate_limit = get_rate_limit_for_client(client_id)

            allowed, rate_info = rate_limiter.is_allowed(
                client_id, limit=rate_limit, window=60  # 1 minute window
            )

            if not allowed:
                response = jsonify(
                    {
                        "error": "Rate limit exceeded",
                        "message": f"Maximum {rate_limit} requests per minute allowed",
                        "retry_after": rate_info["blocked_for"],
                    }
                )
                response.status_code = 429
                response.headers["X-RateLimit-Limit"] = str(rate_limit)
                response.headers["X-RateLimit-Remaining"] = str(rate_info["remaining"])
                response.headers["X-RateLimit-Reset"] = str(rate_info["reset_time"])
                response.headers["Retry-After"] = str(rate_info["blocked_for"])
                return response

            # Execute the function
            result = f(*args, **kwargs)

            # Add rate limit headers to successful responses
            if hasattr(result, "headers"):
                result.headers["X-RateLimit-Limit"] = str(rate_limit)
                result.headers["X-RateLimit-Remaining"] = str(rate_info["remaining"])
                result.headers["X-RateLimit-Reset"] = str(rate_info["reset_time"])

            return result

        return decorated_function

    return decorator


def optional_api_key(f):
    """Decorator for endpoints that optionally accept API keys."""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = request.headers.get("X-API-Key")

        if api_key:
            key_info = api_key_manager.validate_key(api_key)
            if key_info:
                request.api_key_info = key_info
            else:
                # Invalid API key provided
                return (
                    jsonify(
                        {
                            "error": "Invalid API key",
                            "message": "The provided API key is invalid or disabled",
                        }
                    ),
                    401,
                )

        return f(*args, **kwargs)

    return decorated_function


def add_api_info_headers(response):
    """Add API information headers to response."""
    if hasattr(response, "headers"):
        response.headers["X-API-Version"] = "v1"
        response.headers["X-Powered-By"] = "Jira Search"
    return response
