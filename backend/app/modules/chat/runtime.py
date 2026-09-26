"""Single-event-loop generation slots; persistent claims remain authoritative."""

import asyncio
from uuid import uuid4

from app.core.security import AuthError


class ChatRuntime:
    def __init__(self, max_active=2):
        self.max_active = max_active
        self._active = {}

    def reserve(self, conversation_id):
        if conversation_id in self._active:
            raise AuthError(409, "CONFLICT", "该会话已有回答正在生成")
        if len(self._active) >= self.max_active:
            raise AuthError(429, "RATE_LIMITED", "当前回答任务已满，请稍后重试")
        slot = uuid4()
        self._active[conversation_id] = (slot, None)
        return slot

    def bind(self, conversation_id, slot, task):
        if self._active.get(conversation_id, (None,))[0] == slot:
            self._active[conversation_id] = (slot, task)

    def release(self, conversation_id, slot):
        if self._active.get(conversation_id, (None,))[0] == slot:
            del self._active[conversation_id]

    def cancel(self, conversation_id):
        current = self._active.get(conversation_id)
        if current and current[1] is not None:
            current[1].cancel()

    async def shutdown(self):
        tasks = [task for _, task in self._active.values() if task is not None]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._active.clear()
