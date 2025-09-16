# main.py
from __future__ import annotations
import tkinter as tk
import logging
import sv_ttk
import threading
import subprocess
import sys
import json

from app import PlayerApp
from log_viewer import LogViewer, TkinterLogHandler

def setup_logging(log_viewer: LogViewer):
    """設定日誌系統，將日誌導向到 LogViewer"""
    log_queue = log_viewer.log_queue
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO) 
    
    gui_handler = TkinterLogHandler(log_queue)
    formatter = logging.Formatter('%(message)s')
    gui_handler.setFormatter(formatter)
    
    if root_logger.hasHandlers():
        root_logger.handlers.clear()
    root_logger.addHandler(gui_handler)

def check_for_yt_dlp_update(app_instance: PlayerApp):
    """在背景執行緒中透過 pip 檢查 yt-dlp 是否有新版本"""
    def worker():
        try:
            # 獲取本地安裝的版本
            local_process = subprocess.run(
                [sys.executable, "-m", "pip", "show", "yt-dlp"],
                capture_output=True, text=True, check=True, encoding='utf-8'
            )
            local_version = ""
            for line in local_process.stdout.splitlines():
                if line.startswith("Version:"):
                    local_version = line.split(":")[1].strip()
                    break
            
            if not local_version:
                logging.warning("無法獲取本地 yt-dlp 版本。")
                return

            # 獲取 PyPI 上的最新版本資訊 (使用 pip index)
            # pip index versions 會輸出 JSON 格式，更穩定
            remote_process = subprocess.run(
                [sys.executable, "-m", "pip", "index", "versions", "yt-dlp"],
                 capture_output=True, text=True, check=True, encoding='utf-8'
            )
            # 解析輸出以找到最新版本
            # 輸出範例: yt-dlp (2023.12.30)\nAvailable versions: ..., 2023.12.30
            # 我們需要的是 "Available versions" 列表中的最新一個
            remote_version = ""
            if "Available versions:" in remote_process.stdout:
                 versions = remote_process.stdout.split("Available versions:")[1].strip().split(", ")
                 if versions:
                    remote_version = versions[-1]


            if not remote_version:
                logging.warning("無法從 PyPI 獲取遠端 yt-dlp 版本。")
                return

            logging.info(f"yt-dlp 版本檢查: 本地={local_version}, 最新={remote_version}")

            # 比較版本 (簡單的字串比較通常可行，因為版本號是日期格式)
            if local_version < remote_version:
                logging.warning(f"偵測到 yt-dlp 新版本！本地: {local_version}, 最新: {remote_version}")
                app_instance.root.after(0, app_instance.show_update_notification)
            else:
                logging.info("yt-dlp 已是最新版本。")

        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            logging.error("檢查 yt-dlp 更新時發生錯誤 (可能是 pip 指令問題): %s", e)
        except Exception as e:
            logging.exception("檢查 yt-dlp 更新時發生未預期的錯誤。")

    update_thread = threading.Thread(target=worker, daemon=True)
    update_thread.start()

if __name__ == "__main__":
    root = tk.Tk()
    sv_ttk.set_theme("dark")

    log_viewer = LogViewer(root)
    setup_logging(log_viewer)

    app = PlayerApp(root, log_viewer=log_viewer)
    
    # 在應用程式啟動一小段時間後，開始檢查更新
    root.after(2000, lambda: check_for_yt_dlp_update(app))
    
    try:
        root.mainloop()
    except KeyboardInterrupt:
        pass

