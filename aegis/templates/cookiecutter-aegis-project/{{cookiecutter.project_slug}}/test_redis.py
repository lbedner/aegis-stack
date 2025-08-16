#!/usr/bin/env python3
"""
Quick Redis connection test for arq tutorial setup.

This script tests Redis connectivity and basic arq functionality.
Run this after starting Redis with 'make redis-start'.
"""

import asyncio
import sys
from datetime import datetime

try:
    import redis
    print("✅ redis library available")
except ImportError:
    print("❌ redis library not found. Install with: uv add redis")
    sys.exit(1)

try:
    from arq import create_pool
    from arq.connections import RedisSettings
    print("✅ arq library available")
except ImportError:
    print("❌ arq library not found. Install with: uv add arq")
    sys.exit(1)

from app.core.config import settings


async def test_basic_redis():
    """Test basic Redis connection without arq."""
    print("\n🔍 Testing basic Redis connection...")
    
    try:
        # Basic Redis connection
        redis_client = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
        
        # Test ping
        result = redis_client.ping()
        print(f"✅ Redis ping: {result}")
        
        # Test set/get
        test_key = f"test:{datetime.now().isoformat()}"
        redis_client.set(test_key, "Hello Redis!")
        value = redis_client.get(test_key)
        print(f"✅ Redis set/get: {value}")
        
        # Clean up
        redis_client.delete(test_key)
        print("✅ Basic Redis connection successful")
        
    except Exception as e:
        print(f"❌ Basic Redis connection failed: {e}")
        print("💡 Make sure Redis is running: make redis-start")
        return False
    
    return True


async def test_arq_connection():
    """Test arq connection and job enqueuing."""
    print("\n🔍 Testing arq connection...")
    
    try:
        # Create arq Redis pool
        redis_settings = RedisSettings(
            host=settings.REDIS_URL.split("://")[1].split(":")[0],
            port=int(settings.REDIS_URL.split(":")[-1]) if ":" in settings.REDIS_URL.split("://")[1] else 6379,
            database=settings.REDIS_DB
        )
        
        pool = await create_pool(redis_settings)
        
        # Test basic pool connection
        info = await pool.info()
        print(f"✅ arq pool connected: Redis version {info.get('redis_version', 'unknown')}")
        
        # Test job enqueuing (without worker to process it)
        job = await pool.enqueue_job('test_job', 'hello', 'world')
        print(f"✅ Job enqueued: {job}")
        
        # Check job exists in queue
        queue_length = await pool.llen('arq:queue:default')
        print(f"✅ Queue length: {queue_length}")
        
        # Clean up - remove the test job
        await pool.lpop('arq:queue:default')
        print("✅ arq connection successful")
        
        pool.close()
        await pool.wait_closed()
        
    except Exception as e:
        print(f"❌ arq connection failed: {e}")
        print("💡 Make sure Redis is running: make redis-start")
        return False
    
    return True


async def main():
    """Run all Redis and arq tests."""
    print("🚀 Redis + arq Connection Test")
    print("=" * 40)
    
    # Test basic Redis
    redis_ok = await test_basic_redis()
    
    if redis_ok:
        # Test arq if basic Redis works
        arq_ok = await test_arq_connection()
        
        if arq_ok:
            print("\n🎉 All tests passed! Redis + arq ready for tutorial.")
            print("\n📚 Next steps:")
            print("1. Create arq worker tasks")
            print("2. Start arq worker: python -m arq worker")
            print("3. Enqueue jobs from your application")
            print("\n🔧 Useful commands:")
            print("   make redis-cli     # Connect to Redis CLI")
            print("   make redis-stats   # Show Redis memory usage")
            print("   make redis-logs    # Show Redis logs")
            print("   make redis-reset   # Clear all Redis data")
        else:
            print("\n❌ arq test failed")
            sys.exit(1)
    else:
        print("\n❌ Redis test failed")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())