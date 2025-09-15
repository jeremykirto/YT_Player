# config.py
from __future__ import annotations
import json, os
from pathlib import Path
from typing import Dict, Any
import logging

LOG = logging.getLogger("ytplayer.config")

class ConfigManager:
    def __init__(self, app_name: str = "ytplayer"):
        self.app_name = app_name
        self.path = self._get_config_path()
        self.data: Dict[str, Any] = {}
        self._load()

    def _get_config_path(self) -> Path:
        if os.name == "nt":
            base = Path(os.environ.get('APPDATA', Path.home() / 'AppData' / 'Roaming'))
        else:
            base = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config'))
        cfg_dir = base / self.app_name
        cfg_dir.mkdir(parents=True, exist_ok=True)
        return cfg_dir / "config.json"

    def _load(self):
        try:
            if self.path.exists():
                with open(self.path, 'r', encoding='utf-8') as f:
                    self.data = json.load(f)
        except Exception:
            LOG.exception("Failed to load config")
            self.data = {}

    def save(self):
        try:
            with open(self.path, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except Exception:
            LOG.exception("Failed to save config")

    def get(self, key: str, default=None):
        return self.data.get(key, default)

    def set(self, key: str, value):
        self.data[key] = value
        self.save()
