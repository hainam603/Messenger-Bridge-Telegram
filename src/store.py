from __future__ import annotations

import json
import time
import logging
import threading
import requests
from dataclasses import asdict
from pathlib import Path
from threading import RLock
from typing import Any, Optional

from models import QuoteData, TopicEntry, Transport


class BridgeStore:
    def __init__(self, path: Path, *, message_cache_limit: int = 3000, kv_store_url: Optional[str] = None) -> None:
        self.path = path
        self.message_cache_limit = message_cache_limit
        self.kv_store_url = kv_store_url
        self._lock = RLock()
        self._dirty = False
        self._data: dict[str, Any] = {
            "version": 1,
            "topics": {},
            "messenger_index": {},
            "messages": {},
            "message_order": [],
            "tg_quotes": {},
        }
        self._download_from_kv()
        self._load()
        if self.kv_store_url:
            self._start_sync_thread()

    @staticmethod
    def _messenger_key(transport: Transport, messenger_id: str) -> str:
        return f"{transport}:{messenger_id}"

    @staticmethod
    def _message_key(transport: Transport, message_id: str) -> str:
        return f"{transport}:{message_id}"

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if isinstance(loaded, dict):
            self._data.update({
                "topics": loaded.get("topics") or {},
                "messenger_index": loaded.get("messenger_index") or {},
                "messages": loaded.get("messages") or {},
                "message_order": loaded.get("message_order") or [],
                "tg_quotes": loaded.get("tg_quotes") or {},
            })

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(self._data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)
        self._dirty = True

    def _download_from_kv(self) -> None:
        if not self.kv_store_url:
            return
        logger = logging.getLogger(__name__)
        logger.info("Downloading store from KV Store: %s", self.kv_store_url)
        try:
            response = requests.get(self.kv_store_url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, dict) and "topics" in data:
                    self.path.parent.mkdir(parents=True, exist_ok=True)
                    self.path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
                    logger.info("Successfully restored store from KV Store")
                else:
                    logger.warning("Downloaded data from KV Store is invalid or empty")
            elif response.status_code == 404:
                logger.info("KV Store is empty (404), starting with fresh local store")
            else:
                logger.error("Failed to download from KV Store, HTTP status: %d", response.status_code)
        except Exception as e:
            logger.error("Error downloading from KV Store: %s", e)

    def _start_sync_thread(self) -> None:
        thread = threading.Thread(target=self._sync_loop, daemon=True, name="kv-store-sync")
        thread.start()

    def _sync_loop(self) -> None:
        import time
        logger = logging.getLogger(__name__)
        while True:
            time.sleep(30)
            should_sync = False
            data_to_send = None
            with self._lock:
                if self._dirty:
                    should_sync = True
                    data_to_send = json.dumps(self._data, ensure_ascii=False)
            if should_sync and data_to_send:
                logger.debug("Syncing store to KV Store...")
                try:
                    headers = {"Content-Type": "application/json"}
                    response = requests.put(self.kv_store_url, data=data_to_send.encode("utf-8"), headers=headers, timeout=15)
                    if response.status_code in (200, 201):
                        logger.info("Successfully synced store to KV Store")
                        with self._lock:
                            self._dirty = False
                    else:
                        logger.error("Failed to sync to KV Store, HTTP status: %d, response: %s", response.status_code, response.text)
                except Exception as e:
                    logger.error("Error syncing to KV Store: %s", e)

    def all_topics(self) -> list[TopicEntry]:
        with self._lock:
            return [TopicEntry(**entry) for entry in self._data["topics"].values()]

    def get_topic_by_messenger(self, transport: Transport, messenger_id: str) -> Optional[TopicEntry]:
        with self._lock:
            topic_id = self._data["messenger_index"].get(self._messenger_key(transport, messenger_id))
            if topic_id is None:
                return None
            raw = self._data["topics"].get(str(topic_id))
            return TopicEntry(**raw) if raw else None

    def get_topic_by_id(self, topic_id: int) -> Optional[TopicEntry]:
        with self._lock:
            raw = self._data["topics"].get(str(topic_id))
            return TopicEntry(**raw) if raw else None

    def set_topic(self, entry: TopicEntry) -> TopicEntry:
        with self._lock:
            now = int(time.time())
            existing = self._data["topics"].get(str(entry.topic_id))
            if existing and not entry.created_at:
                entry.created_at = int(existing.get("created_at") or now)
            elif not entry.created_at:
                entry.created_at = now
            entry.updated_at = now

            self._data["topics"][str(entry.topic_id)] = asdict(entry)
            self._data["messenger_index"][self._messenger_key(entry.transport, entry.messenger_id)] = entry.topic_id
            self._save()
            return entry

    def update_topic_name(self, topic_id: int, name: str) -> Optional[TopicEntry]:
        with self._lock:
            raw = self._data["topics"].get(str(topic_id))
            if not raw:
                return None
            raw["name"] = name
            raw["updated_at"] = int(time.time())
            self._save()
            return TopicEntry(**raw)

    def remove_topic(self, topic_id: int) -> Optional[TopicEntry]:
        with self._lock:
            raw = self._data["topics"].pop(str(topic_id), None)
            if not raw:
                return None
            entry = TopicEntry(**raw)
            key = self._messenger_key(entry.transport, entry.messenger_id)
            if self._data["messenger_index"].get(key) == topic_id:
                self._data["messenger_index"].pop(key, None)
            self._save()
            return entry

    def save_message(
        self,
        tg_message_id: int,
        messenger_message_ids: list[str],
        quote: QuoteData,
    ) -> None:
        valid_ids = [mid for mid in messenger_message_ids if mid]
        if not valid_ids:
            return

        with self._lock:
            quote_dict = asdict(quote)
            self._data["tg_quotes"][str(tg_message_id)] = quote_dict
            for message_id in valid_ids:
                key = self._message_key(quote.transport, message_id)
                self._data["messages"][key] = {
                    "tg_message_id": tg_message_id,
                    "quote": quote_dict,
                }
                if key not in self._data["message_order"]:
                    self._data["message_order"].append(key)
            self._evict_messages()
            self._save()

    def get_tg_message_id(self, transport: Transport, messenger_message_id: str) -> Optional[int]:
        with self._lock:
            raw = self._data["messages"].get(self._message_key(transport, messenger_message_id))
            if not raw:
                return None
            return int(raw["tg_message_id"])

    def get_quote_by_messenger(self, transport: Transport, messenger_message_id: str) -> Optional[QuoteData]:
        with self._lock:
            raw = self._data["messages"].get(self._message_key(transport, messenger_message_id))
            if not raw:
                return None
            quote = raw.get("quote") or {}
            return QuoteData(**quote) if quote else None

    def find_quote_by_messenger(self, messenger_message_id: str) -> Optional[QuoteData]:
        with self._lock:
            for transport in ("e2ee", "regular"):
                raw = self._data["messages"].get(self._message_key(transport, messenger_message_id))
                if not raw:
                    continue
                quote = raw.get("quote") or {}
                return QuoteData(**quote) if quote else None
            return None

    def get_quote_by_tg(self, tg_message_id: int) -> Optional[QuoteData]:
        with self._lock:
            raw = self._data["tg_quotes"].get(str(tg_message_id))
            return QuoteData(**raw) if raw else None

    def _evict_messages(self) -> None:
        order = self._data["message_order"]
        while len(order) > self.message_cache_limit:
            old_key = order.pop(0)
            old = self._data["messages"].pop(old_key, None)
            if old:
                self._data["tg_quotes"].pop(str(old.get("tg_message_id")), None)