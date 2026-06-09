"""
Server-side conversation storage for Sahra AI.
Persists chat history to conversations.json for cross-device sync.
"""

import json
import os
import threading
import time

CONVERSATIONS_FILE = "conversations.json"
CONVERSATIONS_VERSION = 1


class ConversationNotFoundError(Exception):
    pass


class ConversationStore:
    def __init__(self, path=CONVERSATIONS_FILE):
        self.path = path
        self._lock = threading.Lock()
        self.data = {
            "version": CONVERSATIONS_VERSION,
            "active_id": None,
            "conversations": [],
        }
        self._load()

    def _load(self):
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
        except (json.JSONDecodeError, OSError):
            return

        if isinstance(loaded, dict):
            self.data["version"] = loaded.get("version", CONVERSATIONS_VERSION)
            self.data["active_id"] = loaded.get("active_id")
            conversations = loaded.get("conversations", [])
            self.data["conversations"] = conversations if isinstance(conversations, list) else []

    def save(self):
        with self._lock:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)

    def _sorted_conversations(self):
        conversations = list(self.data.get("conversations", []))
        conversations.sort(key=lambda item: item.get("updatedAt", 0), reverse=True)
        return conversations

    def list_all(self):
        return {
            "active_id": self.data.get("active_id"),
            "conversations": self._sorted_conversations(),
        }

    def get(self, conversation_id):
        for conversation in self.data.get("conversations", []):
            if conversation.get("id") == conversation_id:
                return conversation
        raise ConversationNotFoundError(conversation_id)

    def create(self, title="محادثة جديدة", messages=None):
        now = int(time.time() * 1000)
        conversation = {
            "id": f"c_{now}",
            "title": (title or "محادثة جديدة").strip() or "محادثة جديدة",
            "messages": list(messages or []),
            "updatedAt": now,
        }
        self.data.setdefault("conversations", []).insert(0, conversation)
        self.data["active_id"] = conversation["id"]
        self.save()
        return conversation

    def update(self, conversation_id, title=None, messages=None, updated_at=None):
        conversation = self.get(conversation_id)
        if title is not None:
            cleaned = str(title).strip()
            if cleaned:
                conversation["title"] = cleaned
        if messages is not None:
            conversation["messages"] = list(messages)
        conversation["updatedAt"] = updated_at or int(time.time() * 1000)
        self.save()
        return conversation

    def rename(self, conversation_id, title):
        cleaned = str(title or "").strip()
        if not cleaned:
            raise ValueError("عنوان المحادثة فارغ")
        return self.update(conversation_id, title=cleaned)

    def delete(self, conversation_id):
        conversations = self.data.get("conversations", [])
        before = len(conversations)
        self.data["conversations"] = [
            item for item in conversations if item.get("id") != conversation_id
        ]
        if len(self.data["conversations"]) == before:
            raise ConversationNotFoundError(conversation_id)

        if self.data.get("active_id") == conversation_id:
            remaining = self._sorted_conversations()
            self.data["active_id"] = remaining[0]["id"] if remaining else None

        self.save()
        return {
            "active_id": self.data.get("active_id"),
            "deleted_id": conversation_id,
        }

    def set_active(self, conversation_id):
        if conversation_id is None:
            self.data["active_id"] = None
            self.save()
            return {"active_id": None}

        self.get(conversation_id)
        self.data["active_id"] = conversation_id
        self.save()
        return {"active_id": conversation_id}

    def import_conversations(self, conversations, active_id=None):
        if not isinstance(conversations, list):
            raise ValueError("صيغة المحادثات غير صالحة")

        existing_ids = {item.get("id") for item in self.data.get("conversations", [])}
        imported = 0

        for item in conversations:
            if not isinstance(item, dict):
                continue
            conv_id = item.get("id")
            if not conv_id or conv_id in existing_ids:
                continue

            self.data.setdefault("conversations", []).append(
                {
                    "id": conv_id,
                    "title": str(item.get("title") or "محادثة جديدة").strip() or "محادثة جديدة",
                    "messages": list(item.get("messages") or []),
                    "updatedAt": int(item.get("updatedAt") or time.time() * 1000),
                }
            )
            existing_ids.add(conv_id)
            imported += 1

        if active_id and active_id in existing_ids:
            self.data["active_id"] = active_id
        elif not self.data.get("active_id") and self.data.get("conversations"):
            self.data["active_id"] = self._sorted_conversations()[0]["id"]

        self.save()
        return {"imported": imported, **self.list_all()}
