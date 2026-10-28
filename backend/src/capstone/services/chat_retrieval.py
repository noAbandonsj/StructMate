"""Optional, bounded retrieval for chat; shared retrieval keeps strict failures."""

import logging
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from threading import BoundedSemaphore

from capstone.core.errors import ApiError
from capstone.services.retrieval import retrieve

logger = logging.getLogger(__name__)


class ChatRetrieval:
    def __init__(self, factory, embedding, vectors, settings):
        self.factory, self.embedding, self.vectors, self.settings = (
            factory,
            embedding,
            vectors,
            settings,
        )
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="chat-retrieval")
        # Timed-out calls may still finish in the transport. Never queue more work
        # behind them or allow their late results to alter an answer.
        self.slots = BoundedSemaphore(2)

    def close(self):
        self.executor.shutdown(wait=True, cancel_futures=True)

    def search(self, user_id, scope, ids, query, cancelled):
        if cancelled.is_set():
            return []
        if not self.embedding.available:
            logger.warning("chat_retrieval_skipped code=EMBEDDING_NOT_CONFIGURED")
            return []
        if not self.slots.acquire(blocking=False):
            logger.warning("chat_retrieval_skipped code=RETRIEVAL_BUSY")
            return []
        try:
            future = self.executor.submit(
                retrieve,
                self.factory,
                self.embedding,
                self.vectors,
                self.settings,
                user_id,
                scope,
                ids,
                query,
            )
        except Exception:
            self.slots.release()
            raise
        future.add_done_callback(lambda _: self.slots.release())
        deadline = time.monotonic() + self.settings.chat_retrieval_timeout_seconds
        try:
            while not cancelled.is_set():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    logger.warning("chat_retrieval_skipped code=RETRIEVAL_TIMEOUT")
                    return []
                try:
                    return future.result(timeout=min(remaining, 0.05))
                except TimeoutError:
                    if future.done():
                        # A TimeoutError raised by the retrieval itself is handled
                        # as an I/O failure below, rather than polled forever.
                        return future.result()
            return []
        except ApiError as error:
            code = error.detail["code"]
            if error.status_code != 503 or not (
                code.startswith("EMBEDDING_") or code in {"INDEX_MISSING", "INDEX_REBUILD_REQUIRED"}
            ):
                raise
            logger.warning("chat_retrieval_skipped code=%s", code)
            return []
        except OSError as error:
            logger.warning(
                "chat_retrieval_skipped code=RETRIEVAL_IO_ERROR type=%s", type(error).__name__
            )
            return []
        finally:
            future.cancel()
