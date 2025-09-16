# main.py
from __future__ import annotations
import tkinter as tk
import logging
import sv_ttk
import threading
import subprocess
import sys

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
    """在背景執行緒中檢查 yt-dlp 是否有新版本"""
    def worker():
        try:
            # 使用 yt-dlp 的 --update-pretend 功能來檢查，而不安裝
            # '-Uv' 結合了pretend和verbose，能讓我們從輸出中解析版本資訊
            process = subprocess.run(
                [sys.executable, "-m", "yt_dlp", "-Uv"],
                capture_output=True, text=True, check=True, encoding='utf-8'
            )
            output = process.stdout
            logging.info("yt-dlp 更新檢查輸出:\n%s", output)
            
            # 根據 yt-dlp 的輸出判斷是否有新版本
            if "yt-dlp is up to date" in output:
                logging.info("yt-dlp 已是最新版本。")
            elif "Updating to" in output:
                logging.warning("偵測到 yt-dlp 新版本！")
                # 在主執行緒中呼叫 UI 更新
                app_instance.root.after(0, app_instance.show_update_notification)
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            logging.error("檢查 yt-dlp 更新時發生錯誤: %s", e)
        except Exception as e:
            logging.exception("檢查 yt-dlp 更新時發生未預期的錯誤。")

    # 使用 threading 在背景執行，避免阻塞 UI
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

