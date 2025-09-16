# log_viewer.py
from __future__ import annotations
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import logging
import queue
from datetime import datetime
import json
from typing import List, Dict, Any, Optional

class TkinterLogHandler(logging.Handler):
    """一個將日誌記錄發送到 GUI 佇列的 logging handler"""
    def __init__(self, log_queue: queue.Queue):
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record: logging.LogRecord):
        # 格式化日誌記錄並放入佇列
        msg = self.format(record)
        log_entry = {
            'timestamp': datetime.fromtimestamp(record.created),
            'level': record.levelname,
            'source': record.name,
            'message': msg,
            'detail': f"檔案: {record.pathname}\n行號: {record.lineno}\n函式: {record.funcName}",
        }
        self.log_queue.put(log_entry)

class LogViewer(tk.Toplevel):
    """一個顯示應用程式日誌的獨立視窗"""
    def __init__(self, parent):
        super().__init__(parent)
        self.title("應用程式日誌")
        self.geometry("800x500")
        self.withdraw() # 預設隱藏

        self.log_records: List[Dict[str, Any]] = []
        self.log_queue = queue.Queue()
        self.after_id: Optional[str] = None

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self.toggle_visibility) # 點擊關閉按鈕時隱藏而非銷毀
        
        # 開始定期檢查佇列
        self._process_log_queue()

    def _build_ui(self):
        # --- 主要框架 ---
        main_frame = ttk.Frame(self, padding=5)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # --- 頂部控制列 ---
        controls_frame = self._create_controls_frame(main_frame)
        controls_frame.pack(fill=tk.X, pady=(0, 5))
        
        # --- 日誌顯示區 (使用 PanedWindow 分割) ---
        paned_window = ttk.PanedWindow(main_frame, orient=tk.VERTICAL)
        paned_window.pack(fill=tk.BOTH, expand=True)

        # --- Treeview (日誌列表) ---
        tree_frame = self._create_tree_frame(paned_window)
        paned_window.add(tree_frame, weight=3)
        
        # --- Text (詳細資訊) ---
        detail_frame = self._create_detail_frame(paned_window)
        paned_window.add(detail_frame, weight=1)

    def _create_controls_frame(self, parent) -> ttk.Frame:
        frame = ttk.Frame(parent)
        
        # 篩選
        self.filter_vars = {
            level: tk.BooleanVar(value=True) for level in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        }
        for i, (level, var) in enumerate(self.filter_vars.items()):
            cb = ttk.Checkbutton(frame, text=level, variable=var, command=self._apply_filters)
            cb.pack(side=tk.LEFT, padx=2)
            
        ttk.Separator(frame, orient=tk.VERTICAL).pack(side=tk.LEFT, padx=10, fill=tk.Y)

        # 搜尋
        ttk.Label(frame, text="搜尋:").pack(side=tk.LEFT)
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *args: self._apply_filters())
        search_entry = ttk.Entry(frame, textvariable=self.search_var, width=20)
        search_entry.pack(side=tk.LEFT, padx=5)

        # 功能按鈕 (靠右)
        self.autoscroll_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(frame, text="自動捲動", variable=self.autoscroll_var).pack(side=tk.RIGHT, padx=5)
        ttk.Button(frame, text="匯出", command=self._export_logs).pack(side=tk.RIGHT, padx=2)
        ttk.Button(frame, text="清除", command=self._clear_logs).pack(side=tk.RIGHT, padx=2)
        
        return frame

    def _create_tree_frame(self, parent) -> ttk.Frame:
        frame = ttk.Frame(parent)
        self.tree = ttk.Treeview(
            frame, columns=("Time", "Level", "Source", "Message"), show="headings"
        )
        self.tree.heading("Time", text="時間", anchor=tk.W)
        self.tree.heading("Level", text="級別", anchor=tk.W)
        self.tree.heading("Source", text="來源", anchor=tk.W)
        self.tree.heading("Message", text="訊息", anchor=tk.W)
        self.tree.column("Time", width=150, stretch=False)
        self.tree.column("Level", width=80, stretch=False)
        self.tree.column("Source", width=120, stretch=False)
        self.tree.column("Message", width=400)
        
        # 設定顏色標籤
        self.tree.tag_configure("WARNING", foreground="orange")
        self.tree.tag_configure("ERROR", foreground="red")
        self.tree.tag_configure("CRITICAL", foreground="red", font=("", 9, "bold"))
        
        self.tree.bind("<<TreeviewSelect>>", self._on_log_select)

        # 捲軸
        vsb = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        hsb.pack(side=tk.BOTTOM, fill=tk.X)
        self.tree.pack(fill=tk.BOTH, expand=True)

        return frame

    def _create_detail_frame(self, parent) -> ttk.Frame:
        frame = ttk.Frame(parent)
        ttk.Label(frame, text="詳細資訊:").pack(anchor=tk.W)
        self.detail_text = tk.Text(frame, height=5, wrap="word", state="disabled")
        self.detail_text.pack(fill=tk.BOTH, expand=True, pady=(2, 0))
        return frame

    def _process_log_queue(self):
        """從佇列中處理所有待處理的日誌"""
        try:
            while not self.log_queue.empty():
                log_entry = self.log_queue.get_nowait()
                self.log_records.append(log_entry)
                self._add_log_to_tree(log_entry)
        finally:
            self.after_id = self.after(100, self._process_log_queue)

    def _add_log_to_tree(self, log_entry, index=tk.END):
        """將一條日誌加入 Treeview"""
        values = (
            log_entry['timestamp'].strftime('%Y-%m-%d %H:%M:%S'),
            log_entry['level'],
            log_entry['source'],
            log_entry['message'].split('\n')[0] # 只顯示第一行
        )
        tag = log_entry['level']
        item_id = self.tree.insert("", index, values=values, tags=(tag,))
        
        if self.autoscroll_var.get():
            self.tree.see(item_id)
        return item_id

    def _apply_filters(self):
        """根據目前的篩選和搜尋條件重新填充 Treeview"""
        # 清空 Treeview
        for i in self.tree.get_children():
            self.tree.delete(i)
        
        search_term = self.search_var.get().lower()
        active_levels = {level for level, var in self.filter_vars.items() if var.get()}
        
        for record in self.log_records:
            if record['level'] not in active_levels:
                continue
            if search_term and search_term not in record['message'].lower():
                continue
            
            self._add_log_to_tree(record)
            
    def _on_log_select(self, event):
        """當使用者在 Treeview 中選擇一行時，更新詳細資訊"""
        selected_items = self.tree.selection()
        if not selected_items: return
        
        item_id = selected_items[0]
        # 透過 item id 找到原始的 log record
        # 注意：這是一個較慢的操作，如果日誌量很大需要優化
        item_index = self.tree.index(item_id)
        
        # 由於篩選，tree 的 index 和 log_records 的 index 可能不同
        # 我們需要找到對應的 record
        visible_records = [
            rec for rec in self.log_records 
            if self.filter_vars[rec['level']].get() and 
               (not self.search_var.get() or self.search_var.get().lower() in rec['message'].lower())
        ]
        
        if item_index < len(visible_records):
            record = visible_records[item_index]
            detail_content = f"--- 訊息 ---\n{record['message']}\n\n--- 來源 ---\n{record['detail']}"
            self.detail_text.config(state="normal")
            self.detail_text.delete(1.0, tk.END)
            self.detail_text.insert(tk.END, detail_content)
            self.detail_text.config(state="disabled")

    def _clear_logs(self):
        self.log_records.clear()
        self._apply_filters() # 清空 Treeview

    def _export_logs(self):
        if not self.log_records:
            messagebox.showinfo("無日誌", "沒有可匯出的日誌。", parent=self)
            return
            
        file_path = filedialog.asksaveasfilename(
            parent=self,
            title="匯出日誌",
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("Text files", "*.txt"), ("All files", "*.*")]
        )
        if not file_path: return
        
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                if file_path.endswith('.json'):
                    # 將 datetime 物件轉換為字串以便 JSON 序列化
                    export_data = [
                        {**rec, 'timestamp': rec['timestamp'].isoformat()} for rec in self.log_records
                    ]
                    json.dump(export_data, f, ensure_ascii=False, indent=2)
                else:
                    for rec in self.log_records:
                        ts = rec['timestamp'].strftime('%Y-%m-%d %H:%M:%S')
                        f.write(f"[{ts}][{rec['level']:<8}][{rec['source']}] {rec['message']}\n")
            messagebox.showinfo("成功", "日誌已成功匯出！", parent=self)
        except Exception as e:
            messagebox.showerror("錯誤", f"匯出失敗: {e}", parent=self)

    def toggle_visibility(self):
        if self.winfo_viewable():
            self.withdraw()
        else:
            self.deiconify()
            self.lift()
            self.focus_set()

    def close(self):
        """徹底關閉並清理資源"""
        if self.after_id:
            self.after_cancel(self.after_id)
            self.after_id = None
        self.destroy()
