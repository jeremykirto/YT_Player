# async_worker.py
import threading, asyncio

class AsyncWorker:
    def __init__(self):
        self.loop = None
        self._thread = threading.Thread(target=self._start_loop, daemon=True)
        self._started = threading.Event()
        self._thread.start()
        self._started.wait(timeout=3)

    def _start_loop(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self._started.set()
        try:
            self.loop.run_forever()
        finally:
            pending = asyncio.all_tasks(self.loop)
            for t in pending:
                t.cancel()
            try:
                self.loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            except Exception:
                pass
            self.loop.close()

    def submit_coro(self, coro):
        if not self.loop:
            raise RuntimeError("Async loop not started")
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

    async def run_blocking(self, func, *args, **kwargs):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: func(*args, **kwargs))

    def stop(self):
        if self.loop:
            self.loop.call_soon_threadsafe(self.loop.stop)
            self._thread.join(timeout=1)
