import asyncio
from .agent_loop import _async_main

if __name__ == "__main__":
    try:
        asyncio.run(_async_main())
    except KeyboardInterrupt:
        pass
