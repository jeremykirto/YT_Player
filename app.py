# app.py
from __future__ import annotations
import logging
import time
import os
import sys
import subprocess
import threading
from contextlib import suppress
from typing import Optional, List, Tuple, Set, Any, Dict
import tkinter as tk
from tkinter import ttk, messagebox
import random
from datetime import datetime

# 嘗試匯入 yt_dlp
try:
    import yt_dlp
    from yt_dlp.utils import DownloadError as YTDLDownloadError, ExtractorError as YTDLExtractorError
except ImportError:
    yt_dlp = None
    YTDLDownloadError = YTDLExtractorError = Exception

# 嘗試匯入 vlc
try:
    import vlc
except (ImportError, OSError):
    vlc = None

from config import ConfigManager
from async_worker import AsyncWorker
from utils import locate_ffmpeg_exe
from cache import SmartCacheManager
from log_viewer import LogViewer

# 設定日誌
LOG = logging.getLogger("ytplayer.app")


class PlayerApp:
    def __init__(self, root: tk.Tk, log_viewer: LogViewer):
        self.root = root
        self.root.title("YT Player")
        self.root.geometry("900x640")
        self.root.minsize(600, 400)
        
        # --- 核心元件 ---
        self.log_viewer = log_viewer
        self.config = ConfigManager()
        self.async_worker = AsyncWorker()
        self.ydl_opts_common = {'quiet': True, 'nocheckcertificate': True, 'verbose': False}
        
        # --- 快取 ---
        self.playlist_cache = SmartCacheManager(app_name=self.config.app_name, default_ttl=3600)

        # --- 播放清單 ---
        self.playlist_urls: List[str] = []
        self.playlist_titles: List[str] = []
        self.current_idx: Optional[int] = None
        self.unavailable_indices: Set[int] = set()

        # --- VLC 播放器 ---
        self.vlc_inst: Optional[Any] = None
        self.vlc_player: Optional[Any] = None

        # --- UI 元件 ---
        self.url_entry: Optional[ttk.Entry] = None
        self.listbox: Optional[tk.Listbox] = None
        self.status_label: Optional[ttk.Label] = None
        self.history_popup: Optional[tk.Toplevel] = None
        self.history_details_modal: Optional[tk.Toplevel] = None
        self.update_notification_frame: Optional[ttk.Frame] = None
        self.update_label: Optional[ttk.Label] = None
        self.update_button: Optional[ttk.Button] = None
        self.top_control_frame: Optional[ttk.Frame] = None
        
        # --- 播放結束事件防抖 ---
        self._last_end_event_time = 0.0
        self._end_debounce_sec = float(self.config.get('end_debounce_sec', 1.5))

        self.build_ui()
        self.init_vlc()

        # --- 事件綁定 ---
        self.root.protocol("WM_DELETE_WINDOW", self._quit_gracefully)
        self.root.bind_all("<Button-1>", self._handle_root_click, add="+")
        self.root.bind("<Control-Shift-L>", lambda e: self.log_viewer.toggle_visibility())
        
        self.root.after(100, self._load_last_playlist_on_startup)

    def build_ui(self):
        """建立應用程式的圖形使用者介面"""
        font_main = ("Microsoft JhengHei UI", 10)
        font_list = ("Microsoft JhengHei UI", 11)
        self.color_playing_bg = "#0078D7"
        self.color_playing_fg = "white"
        self.color_selected_bg = "#CA5100"
        self.color_selected_fg = "white"
        self.color_unavailable_fg = "gray"

        # --- 更新提示列 (預設隱藏) ---
        self.update_notification_frame = ttk.Frame(self.root, style='Warn.TFrame', padding=5)
        
        self.update_label = ttk.Label(self.update_notification_frame, text="偵測到 yt-dlp 新版本，建議更新以獲得最佳體驗。", style='Warn.TLabel')
        self.update_label.pack(side=tk.LEFT, padx=5, expand=True)
        self.update_button = ttk.Button(self.update_notification_frame, text="立即更新", command=self._start_update, style='Warn.TButton')
        self.update_button.pack(side=tk.RIGHT, padx=5)
        
        s = ttk.Style()
        s.configure('TButton', padding=6, font=font_main)
        s.configure('Warn.TFrame', background='#ffc107') # 黃色背景
        s.configure('Warn.TLabel', background='#ffc107', foreground='black')
        s.configure('Warn.TButton', background='#ffc107', foreground='black')

        # --- 頂部控制列 ---
        self.top_control_frame = ttk.Frame(self.root, padding=10)
        self.top_control_frame.pack(fill=tk.X, side=tk.TOP)
        
        ttk.Label(self.top_control_frame, text="播放清單網址：", font=font_main).pack(side=tk.LEFT)
        self.url_entry = ttk.Entry(self.top_control_frame, font=font_main)
        self.url_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.url_entry.bind("<FocusIn>", self._show_history_popup)
        self.url_entry.bind("<Button-1>", self._show_history_popup, add="+")
        
        self.load_button = ttk.Button(self.top_control_frame, text="載入", command=self.load_playlist, style='TButton')
        self.load_button.pack(side=tk.LEFT, padx=2)
        ttk.Button(self.top_control_frame, text="🔀 隨機", command=self.play_random, style='TButton').pack(side=tk.LEFT, padx=2)
        ttk.Button(self.top_control_frame, text="▶ 播放/暫停", command=self.toggle_play, style='TButton').pack(side=tk.LEFT, padx=(2, 0))

        # --- 播放列表 ---
        list_frame = ttk.Frame(self.root, padding=(10, 0, 10, 10))
        list_frame.pack(fill=tk.BOTH, expand=True)
        self.listbox = tk.Listbox(
            list_frame, font=font_list, exportselection=False, borderwidth=0, highlightthickness=0,
            selectbackground=self.color_selected_bg, selectforeground=self.color_selected_fg
        )
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.listbox.bind("<Double-Button-1>", lambda e: self._on_list_double())
        sb = ttk.Scrollbar(list_frame, command=self.listbox.yview)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.listbox.config(yscrollcommand=sb.set)

        # --- 底部狀態列 ---
        status_frame = ttk.Frame(self.root, padding=(10, 5))
        status_frame.pack(fill=tk.X, side=tk.BOTTOM)
        self.status_label = ttk.Label(status_frame, text="準備就緒", anchor=tk.W, font=font_main)
        self.status_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(status_frame, text="日誌", command=self.log_viewer.toggle_visibility).pack(side=tk.RIGHT)

    # --- 更新機制 ---
    def show_update_notification(self):
        """顯示 yt-dlp 更新提示"""
        if self.update_notification_frame and self.top_control_frame:
            self.update_notification_frame.pack(fill=tk.X, side=tk.TOP, before=self.top_control_frame)

    def _start_update(self):
        """開始更新流程"""
        if self.update_label:
            self.update_label.config(text="正在更新，請稍候...")
        if self.update_button:
            self.update_button.config(state="disabled")
        
        update_thread = threading.Thread(target=self._perform_update_in_background, daemon=True)
        update_thread.start()

    def _perform_update_in_background(self):
        """在背景執行緒中執行 pip install --upgrade yt-dlp"""
        try:
            # 在 Windows 上，不顯示主控台視窗
            creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            process = subprocess.run(
                [sys.executable, "-m", "pip", "install", "--upgrade", "yt-dlp"],
                capture_output=True, text=True, check=True, encoding='utf-8',
                creationflags=creationflags
            )
            LOG.info("yt-dlp 更新成功:\n%s", process.stdout)
            self.root.after(0, self._on_update_success)
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            error_output = e.stderr if hasattr(e, 'stderr') else str(e)
            LOG.error("yt-dlp 更新失敗: %s", error_output)
            self.root.after(0, self._on_update_failure, error_output)

    def _on_update_success(self):
        """更新成功後的 UI 回饋"""
        # 隱藏更新提示列
        if self.update_notification_frame:
            self.update_notification_frame.pack_forget()
        
        # 彈出提示框，告知使用者需要手動重啟
        messagebox.showinfo("更新成功", "yt-dlp 已成功更新！\n\n請重新啟動應用程式以套用變更。", parent=self.root)
        LOG.info("yt-dlp 更新完畢，已提示使用者重啟。")

    def _on_update_failure(self, error_message: str):
        """更新失敗後的 UI 回饋"""
        if self.update_label:
            self.update_label.config(text="更新失敗，請查看日誌詳情。")
        if self.update_button:
            self.update_button.config(state="normal") # 重新啟用按鈕

    # --- 事件與其他函式 ---
    def _handle_root_click(self, event):
        if self.history_popup:
            try:
                if str(event.widget.winfo_toplevel()) == str(self.history_popup): return
            except tk.TclError: pass
        if event.widget != self.url_entry:
            self._hide_history_popup()

    def set_status(self, text: str):
        if self.root.winfo_exists():
            self.root.after(0, lambda: self.status_label and self.status_label.config(text=text))

    def _update_playlist_history(self, url: str):
        if not url: return
        history = self.config.get("playlist_history", {})
        entry = history.get(url, {"count": 0})
        entry["last_used"] = time.time()
        entry["count"] = entry.get("count", 0) + 1
        history[url] = entry
        self.config.set("playlist_history", history)
        LOG.info("已更新歷史紀錄: %s", url)

    def _get_sorted_playlist_history(self) -> List[Dict[str, Any]]:
        history = self.config.get("playlist_history", {})
        history_list = [{"url": k, **v} for k, v in history.items()]
        history_list.sort(key=lambda x: x.get("last_used", 0), reverse=True)
        return history_list

    def _show_history_popup(self, event=None):
        if self.history_popup or not self.url_entry: return
        history = self._get_sorted_playlist_history()
        x = self.url_entry.winfo_rootx()
        y = self.url_entry.winfo_rooty() + self.url_entry.winfo_height()
        width = self.url_entry.winfo_width()
        self.history_popup = popup = tk.Toplevel(self.root)
        popup.overrideredirect(True)
        popup.geometry(f"{width}x200+{x}+{y}")
        s = ttk.Style()
        s.configure('Card.TFrame', background='white', borderwidth=1, relief='solid')
        s.configure('Link.TButton', anchor='w', borderwidth=0, padding=4)
        s.map('Link.TButton', background=[('active', '#e5f3ff')])
        frame = ttk.Frame(popup, style='Card.TFrame', padding=5)
        frame.pack(fill=tk.BOTH, expand=True)
        if not history:
            ttk.Label(frame, text="無歷史紀錄", background='white', padding=5).pack(pady=10)
        else:
            for item in history[:3]:
                url = item['url']
                display_text = url if len(url) < (width // 7) else url[:(width // 7)-3] + "..."
                btn = ttk.Button(frame, text=display_text, style='Link.TButton',
                                 command=lambda u=url: self._on_history_item_selected(u))
                btn.pack(fill=tk.X, pady=1, padx=1)
        ttk.Separator(frame, orient='horizontal').pack(fill=tk.X, pady=5)
        ttk.Button(frame, text="詳細資料...", command=self._show_history_details_modal).pack(pady=5)

    def _hide_history_popup(self):
        if self.history_popup:
            self.history_popup.destroy()
            self.history_popup = None

    def _on_history_item_selected(self, url: str):
        if not self.url_entry: return
        self.url_entry.delete(0, tk.END)
        self.url_entry.insert(0, url)
        self._hide_history_popup()
        self.root.focus_set()

    def _show_history_details_modal(self):
        if self.history_details_modal and self.history_details_modal.winfo_exists():
            self.history_details_modal.lift()
            return
        self._hide_history_popup()
        history = self._get_sorted_playlist_history()
        self.history_details_modal = modal = tk.Toplevel(self.root)
        modal.title("所有歷史紀錄")
        modal.transient(self.root)
        modal.grab_set()
        modal.geometry("750x450")
        if not history:
            ttk.Label(modal, text="無任何歷史紀錄").pack(pady=20)
            return
        tree_frame = ttk.Frame(modal, padding=10)
        tree_frame.pack(fill=tk.BOTH, expand=True)
        button_frame = ttk.Frame(modal, padding=10)
        button_frame.pack(fill=tk.X)
        cols = ("URL", "使用次數", "上次使用")
        tree = ttk.Treeview(tree_frame, columns=cols, show='headings', selectmode='extended')
        for col in cols: tree.heading(col, text=col)
        tree.column("URL", width=450); tree.column("使用次數", width=80, anchor=tk.CENTER); tree.column("上次使用", width=150, anchor=tk.W)
        for item in history:
            last_used_str = datetime.fromtimestamp(item['last_used']).strftime('%Y-%m-%d %H:%M:%S')
            tree.insert("", tk.END, values=(item['url'], item['count'], last_used_str))
        sb = ttk.Scrollbar(tree_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        delete_button = ttk.Button(button_frame, text="刪除選取項目", state="disabled")
        delete_button.pack(side=tk.RIGHT)
        def on_selection_change(event): delete_button.config(state="normal" if tree.selection() else "disabled")
        def do_delete():
            selected_ids = tree.selection()
            if not selected_ids: return
            if not messagebox.askyesno("確認刪除", f"您確定要永久刪除這 {len(selected_ids)} 筆紀錄嗎？\n此操作無法復原。", parent=modal): return
            current_history = self.config.get("playlist_history", {})
            urls_to_delete = [tree.item(item_id, 'values')[0] for item_id in selected_ids]
            for url in urls_to_delete:
                if url in current_history: del current_history[url]
            self.config.set("playlist_history", current_history)
            LOG.info("已從歷史紀錄中刪除 %d 個項目。", len(urls_to_delete))
            tree.delete(*selected_ids)
            on_selection_change(None)
        def on_tree_double_click(event):
            selected_item_id = tree.selection()
            if not selected_item_id: return
            item_values = tree.item(selected_item_id[0], 'values')
            if item_values:
                self._on_history_item_selected(item_values[0])
                modal.destroy()
        delete_button.config(command=do_delete)
        tree.bind("<<TreeviewSelect>>", on_selection_change)
        tree.bind("<Double-1>", on_tree_double_click)
        
    def _load_last_playlist_on_startup(self):
        history = self._get_sorted_playlist_history()
        if history and self.url_entry and self.load_button:
            last_url = history[0]['url']
            LOG.info("在啟動時找到上次的播放清單: %s", last_url)
            self.url_entry.insert(0, last_url)
            self.load_button.invoke()
        else:
            LOG.info("找不到上次的播放清單。")

    def load_playlist(self):
        if not yt_dlp or not self.url_entry: return
        url = self.url_entry.get().strip()
        if not url: return messagebox.showerror("錯誤", "請輸入播放清單或影片連結")
        self._update_playlist_history(url)
        if (cached := self.playlist_cache.get(f"playlist::{url}")):
            LOG.info("從快取載入播放清單: %s", url)
            self.set_status("從快取載入播放清單...")
            self._on_playlist_loaded(cached, from_cache=True)
        else:
            self.set_status("正在從網路載入播放清單...")
            self.async_worker.submit_coro(self._load_playlist_async(url))

    async def _load_playlist_async(self, url: str):
        try:
            result = await self.async_worker.run_blocking(self._fetch_playlist_blocking, url)
            self.root.after(0, self._on_playlist_loaded, result, url)
        except Exception as e:
            self.root.after(0, self._on_playlist_load_failed, e)

    def _fetch_playlist_blocking(self, url: str) -> Tuple[List[str], List[str]]:
        ydl_opts = dict(self.ydl_opts_common, extract_flat=True, skip_download=True)
        with yt_dlp.YoutubeDL(ydl_opts) as ydl: info = ydl.extract_info(url, download=False)
        entries, urls, titles = info.get('entries') or [], [], []
        for e in entries:
            if not (vid_id := e.get('id')): continue
            urls.append(f"https://www.youtube.com/watch?v={vid_id}")
            titles.append(e.get('title', '未命名影片'))
        if not urls and isinstance(info, dict) and (web_url := info.get('webpage_url')):
            urls.append(web_url); titles.append(info.get('title', '未命名影片'))
        return urls, titles

    def _on_playlist_loaded(self, result, url_for_cache: Optional[str] = None, from_cache: bool = False):
        if url_for_cache: self.playlist_cache.set(f"playlist::{url_for_cache}", result)
        self.playlist_urls, self.playlist_titles = result
        self.unavailable_indices.clear()
        self.current_idx = None
        self._refresh_listbox()
        self.set_status(f"已載入 {len(self.playlist_urls)} 首影片" + (" (來自快取)" if from_cache else ""))

    def _on_playlist_load_failed(self, error: Exception):
        messagebox.showerror("載入失敗", f"無法載入播放清單。\n錯誤: {error}")
        self.set_status("載入失敗")

    def _refresh_listbox(self):
        if not self.listbox: return
        self.listbox.delete(0, tk.END)
        for i, title in enumerate(self.playlist_titles):
            self.listbox.insert(tk.END, f"{i+1}. {title}")
        self._update_listbox_highlights()

    def _update_listbox_highlights(self):
        if not self.listbox: return
        for i in range(self.listbox.size()):
            bg, fg = ("", "")
            if i == self.current_idx:
                bg, fg = self.color_playing_bg, self.color_playing_fg
            elif i in self.unavailable_indices:
                fg = self.color_unavailable_fg
            self.listbox.itemconfig(i, bg=bg, fg=fg)

    def play_index(self, idx: int):
        if not self.vlc_player: return messagebox.showwarning("無法播放", "VLC 播放器尚未初始化。")
        if not (0 <= idx < len(self.playlist_urls)): return
        if idx in self.unavailable_indices: return self.play_next(start_idx=idx)
        title = self.playlist_titles[idx]
        self.set_status(f"({idx+1}/{len(self.playlist_urls)}) 正在取得串流: {title}")
        self.async_worker.submit_coro(self._get_stream_info_async(self.playlist_urls[idx], idx))

    async def _get_stream_info_async(self, url: str, idx: int):
        try:
            result = await self.async_worker.run_blocking(self._get_stream_info_blocking, url)
            self.root.after(0, self._on_stream_info_ready, *result, idx)
        except Exception as e:
            self.root.after(0, self._on_stream_info_error, e, idx)

    def _get_stream_info_blocking(self, url: str) -> Tuple[str, str]:
        for fmt in ('bestaudio[ext=m4a]/bestaudio', 'bestaudio/best'):
            try:
                ydl_opts = dict(self.ydl_opts_common, format=fmt, skip_download=True)
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                title, stream_url = info.get('title', '無標題'), info.get('url')
                if not stream_url:
                    for f in info.get('formats', []):
                        if f.get('url') and f.get('acodec') != 'none':
                            stream_url = f['url']; break
                if stream_url: return title, stream_url
            except Exception as e:
                LOG.warning("使用格式 '%s' 獲取串流失敗: %s", fmt, e)
        raise RuntimeError(f"所有格式策略均無法為 {url} 獲取串流")

    def _on_stream_info_ready(self, title: str, stream_url: str, idx: int):
        self.set_status(f"正在播放: {title}")
        self._start_play(stream_url)
        self.current_idx = idx
        self._update_listbox_highlights()
        if self.listbox: self.listbox.see(idx)

    def _on_stream_info_error(self, error: Exception, idx: int):
        title = self.playlist_titles[idx]
        LOG.error("取得 '%s' 的串流失敗: %s", title, str(error))
        error_msg = str(error).lower()
        permanent_errors = ["video unavailable", "private video", "no longer available", "account associated", "violating", "copyright"]
        if any(err in error_msg for err in permanent_errors):
            self.set_status(f"跳過不可用影片: {title}")
            self.unavailable_indices.add(idx)
            self._refresh_listbox()
        else:
            self.set_status(f"暫時無法播放，跳過: {title}")
        self.root.after(200, lambda: self.play_next(start_idx=idx))

    def _start_play(self, stream_url: str):
        if not (vlc and self.vlc_inst and self.vlc_player): return
        self.vlc_player.set_media(self.vlc_inst.media_new(stream_url))
        self.vlc_player.play()

    def toggle_play(self):
        if not self.vlc_player: return messagebox.showwarning("無法播放", "VLC 尚未初始化。")
        if self.vlc_player.is_playing(): self.vlc_player.pause(); self.set_status("已暫停")
        else:
            if self.vlc_player.get_media(): self.vlc_player.play(); self.set_status("播放中")
            else:
                sel = self.listbox.curselection() if self.listbox else None
                self.play_index(sel[0] if sel else 0)

    def play_random(self):
        if not self.vlc_player: return messagebox.showwarning("無法播放", "VLC 尚未初始化。")
        if not self.playlist_urls: return
        pool = [i for i in range(len(self.playlist_urls)) if i not in self.unavailable_indices]
        if not pool: return
        if len(pool) > 1 and self.current_idx in pool: pool.remove(self.current_idx)
        self.play_index(random.choice(pool))

    def play_next(self, start_idx: Optional[int] = None):
        if not self.playlist_urls: return
        num = len(self.playlist_urls)
        start = self.current_idx if start_idx is None else start_idx
        for i in range(1, num + 1):
            next_idx = (start + i) % num
            if next_idx not in self.unavailable_indices: return self.play_index(next_idx)

    def _on_list_double(self):
        if self.listbox and (sel := self.listbox.curselection()): self.play_index(sel[0])

    def init_vlc(self):
        if not vlc: 
            LOG.warning("python-vlc 模組或 VLC 主程式未找到。")
            messagebox.showwarning("VLC 未就緒", "找不到 VLC Media Player。\n請確認您已安裝，否則播放功能將無法使用。")
            return
        try:
            cache = int(self.config.get('cache_ms', 5000))
            self.vlc_inst = vlc.Instance(f'--network-caching={cache}', '--no-video')
            self.vlc_player = self.vlc_inst.media_player_new()
            em = self.vlc_player.event_manager()
            em.event_attach(vlc.EventType.MediaPlayerEndReached, self._on_vlc_end)
            LOG.info("VLC 初始化成功 (網路快取 %d ms)", cache)
        except Exception as e:
            LOG.exception("VLC 初始化失敗")
            messagebox.showerror("VLC 錯誤", f"VLC 播放器初始化失敗。\n錯誤: {e}\n請確保 VLC 安裝正確。")
            self.vlc_player = self.vlc_inst = None

    def _on_vlc_end(self, event):
        now = time.time()
        if (now - self._last_end_event_time) < self._end_debounce_sec: return
        self._last_end_event_time = now
        LOG.info("索引 %s 播放完畢", self.current_idx)
        self.root.after(250, self.play_next)

    def _quit_gracefully(self):
        LOG.info("正在關閉應用程式...")
        with suppress(Exception): 
            if self.vlc_player: self.vlc_player.stop()
        with suppress(Exception): self.async_worker.stop()
        with suppress(Exception): self.log_viewer.close()
        self.root.destroy()

