# main.py
from __future__ import annotations
import tkinter as tk
import logging
import sv_ttk

from app import PlayerApp
from log_viewer import LogViewer, TkinterLogHandler

def setup_logging(log_viewer: LogViewer):
    """設定日誌系統，將日誌導向到 LogViewer"""
    log_queue = log_viewer.log_queue
    
    # 取得根 logger
    root_logger = logging.getLogger()
    # 設定根 logger 的級別，INFO 代表會捕捉 INFO, WARNING, ERROR, CRITICAL
    root_logger.setLevel(logging.INFO) 
    
    # 建立並加入我們的 GUI handler
    gui_handler = TkinterLogHandler(log_queue)
    
    # 為 handler 設定一個統一的格式
    formatter = logging.Formatter(
        '%(message)s'  # 我們只傳送原始訊息，因為 LogViewer 會自己加上時間等資訊
    )
    gui_handler.setFormatter(formatter)
    
    # 將 handler 加入根 logger
    # 移除所有現有的 handler，確保日誌只會送到我們的 GUI
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    root_logger.addHandler(gui_handler)

if __name__ == "__main__":
    root = tk.Tk()
    
    # --- 套用 sv_ttk 主題 ---
    sv_ttk.set_theme("dark")

    # --- 初始化日誌檢視器並設定日誌系統 ---
    log_viewer = LogViewer(root)
    setup_logging(log_viewer)

    # --- 建立主應用程式，並傳入 log_viewer 的參考 ---
    # (下一步我們會修改 PlayerApp 來接收這個參數)
    app = PlayerApp(root, log_viewer=log_viewer)
    
    try:
        root.mainloop()
    except KeyboardInterrupt:
        pass
    # PlayerApp 的 _quit_gracefully 方法會處理 app 和 log_viewer 的關閉

