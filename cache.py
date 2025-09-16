# cache.py
import threading
import time
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional
import logging

LOG = logging.getLogger("ytplayer.cache")

class SmartCacheManager:
    def __init__(self, app_name: str = "ytplayer", cache_file: str = "cache.json", max_size: int = 400, default_ttl: int = 60*60):
        self.app_name = app_name
        self.cache_file = cache_file
        self.path = self._get_cache_path()
        self.store: Dict[str, Dict[str, Any]] = {}
        self.max_size = max_size
        self.default_ttl = default_ttl
        self.lock = threading.Lock()
        self._load()

    def _get_cache_path(self) -> Path:
        """取得快取檔案的路徑，與 config.py 的邏輯保持一致"""
        if os.name == "nt":
            base = Path(os.environ.get('APPDATA', Path.home() / 'AppData' / 'Roaming'))
        else:
            base = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config'))
        cache_dir = base / self.app_name
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir / self.cache_file

    def _load(self):
        """從檔案載入快取資料"""
        with self.lock:
            try:
                if self.path.exists():
                    with open(self.path, 'r', encoding='utf-8') as f:
                        self.store = json.load(f)
                        LOG.info("已從 %s 載入永續性快取。", self.path)
            except (json.JSONDecodeError, IOError) as e:
                LOG.warning("載入快取檔案失敗 (%s)，將使用空快取。", e)
                self.store = {}

    def _save(self):
        """將目前的快取資料儲存到檔案"""
        # 這個函式總是在 lock 保護下被呼叫
        try:
            with open(self.path, 'w', encoding='utf-8') as f:
                json.dump(self.store, f, ensure_ascii=False, indent=2)
        except IOError as e:
            LOG.error("儲存快取檔案失敗: %s", e)

    def get(self, key: str) -> Optional[Any]:
        """從快取中取得資料，若資料過期則移除"""
        with self.lock:
            entry = self.store.get(key)
            if not entry:
                return None
            
            # 檢查是否過期
            if entry.get('expires_at') is not None and time.time() > entry['expires_at']:
                LOG.info("快取項目 '%s' 已過期，將其移除。", key)
                self.store.pop(key, None)
                self._save() # 移除過期項目後儲存變更
                return None
            
            entry['hit'] = entry.get('hit', 0) + 1
            return entry.get('value')

    def set(self, key: str, value: Any, ttl: Optional[int] = None):
        """將資料存入快取，並檢查是否超出大小限制"""
        with self.lock:
            ttl_eff = ttl if ttl is not None else self.default_ttl
            self.store[key] = {
                'value': value,
                'created': time.time(),
                'expires_at': (time.time() + ttl_eff) if ttl_eff > 0 else None,
                'hit': 0
            }
            if len(self.store) > self.max_size:
                self._evict_one()
            self._save() # 每次設定新值後都儲存

    def _evict_one(self):
        """根據 LFU/LRU 策略移除一個快取項目"""
        # 這個函式總是在 lock 保護下被呼叫
        now = time.time()
        
        # 優先移除已過期的項目
        expired_keys = [k for k, v in self.store.items() if v.get('expires_at') and v['expires_at'] < now]
        if expired_keys:
            for k in expired_keys:
                self.store.pop(k, None)
            LOG.info("因快取已滿，清除了 %d 個過期項目。", len(expired_keys))
            return

        # 若空間仍然不足，則根據點擊數(hit)和創建時間(created)來淘汰
        if len(self.store) > self.max_size:
            # 排序策略：優先淘汰點擊數最少的，若點擊數相同則淘汰最舊的
            items = [(k, v.get('hit', 0), v.get('created', 0)) for k, v in self.store.items()]
            items.sort(key=lambda x: (x[1], x[2])) 
            if items:
                key_to_evict = items[0][0]
                self.store.pop(key_to_evict, None)
                LOG.info("快取已滿，依據淘汰策略移除項目: %s", key_to_evict)

    def clear(self):
        """清空所有快取"""
        with self.lock:
            self.store.clear()
            self._save()
