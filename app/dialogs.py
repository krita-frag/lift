from datetime import UTC, datetime

import customtkinter as ctk

from app.theme import _Theme


class ProfileExportDialog(ctk.CTkToplevel):
    def __init__(self, parent, dcc_name: str, dcc_version: str):
        super().__init__(parent)
        self.title("导出 Profile")
        self.geometry("400x250")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self.dcc_name = dcc_name
        self.dcc_version = dcc_version
        self.result = None

        frame = ctk.CTkFrame(self)
        frame.pack(fill="both", expand=True, padx=20, pady=20)

        ctk.CTkLabel(
            frame,
            text=f"从本机 {dcc_name} {dcc_version} 导出配置",
            font=ctk.CTkFont(size=_Theme.FONT_SIZE_TITLE, weight="bold"),
        ).pack(pady=(0, 15))

        ctk.CTkLabel(frame, text="Profile 名称:", font=ctk.CTkFont(size=_Theme.FONT_SIZE_MEDIUM)).pack(anchor="w")
        self.name_entry = ctk.CTkEntry(frame, placeholder_text="my_maya_setup", width=360)
        self.name_entry.pack(pady=(0, 10))

        ctk.CTkLabel(frame, text="描述 (可选):", font=ctk.CTkFont(size=_Theme.FONT_SIZE_MEDIUM)).pack(anchor="w")
        self.desc_entry = ctk.CTkEntry(frame, placeholder_text="我的 Maya 配置", width=360)
        self.desc_entry.pack(pady=(0, 15))

        btn_frame = ctk.CTkFrame(frame, fg_color="transparent")
        btn_frame.pack(fill="x")

        ctk.CTkButton(
            btn_frame,
            text="取消",
            width=100,
            command=self.destroy,
            fg_color="gray40",
            hover_color="gray30",
        ).pack(side="right", padx=5)

        ctk.CTkButton(
            btn_frame,
            text="导出",
            width=100,
            command=self._on_export,
            fg_color=_Theme.COLOR_SUCCESS,
            hover_color=_Theme.COLOR_SUCCESS_HOVER,
        ).pack(side="right", padx=5)

        self.name_entry.focus_set()

    def _on_export(self):
        name = self.name_entry.get().strip()
        if not name:
            self.name_entry.configure(border_width=2)
            return
        self.result = {
            "name": name,
            "description": self.desc_entry.get().strip(),
        }
        self.destroy()


class ProfileImportDialog(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("导入 Profile")
        self.geometry("400x280")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self.result = None

        frame = ctk.CTkFrame(self)
        frame.pack(fill="both", expand=True, padx=20, pady=20)

        ctk.CTkLabel(
            frame,
            text="导入 Profile（目录或 .tar.gz 归档）",
            font=ctk.CTkFont(size=_Theme.FONT_SIZE_TITLE, weight="bold"),
        ).pack(pady=(0, 15))

        ctk.CTkLabel(frame, text="源路径:", font=ctk.CTkFont(size=_Theme.FONT_SIZE_MEDIUM)).pack(anchor="w")
        self.path_entry = ctk.CTkEntry(
            frame, placeholder_text="/path/to/profile 或 /path/to/profile.tar.gz", width=360
        )
        self.path_entry.pack(pady=(0, 10))

        ctk.CTkLabel(frame, text="重命名 (可选，留空使用原名):", font=ctk.CTkFont(size=_Theme.FONT_SIZE_MEDIUM)).pack(
            anchor="w"
        )
        self.name_entry = ctk.CTkEntry(frame, placeholder_text="自定义名称", width=360)
        self.name_entry.pack(pady=(0, 15))

        btn_frame = ctk.CTkFrame(frame, fg_color="transparent")
        btn_frame.pack(fill="x")

        ctk.CTkButton(
            btn_frame,
            text="取消",
            width=100,
            command=self.destroy,
            fg_color="gray40",
            hover_color="gray30",
        ).pack(side="right", padx=5)

        ctk.CTkButton(
            btn_frame,
            text="浏览...",
            width=80,
            command=self._browse,
        ).pack(side="left", padx=5)

        ctk.CTkButton(
            btn_frame,
            text="导入",
            width=100,
            command=self._on_import,
            fg_color=_Theme.COLOR_PRIMARY,
            hover_color=_Theme.COLOR_PRIMARY_HOVER,
        ).pack(side="right", padx=5)

        self.path_entry.focus_set()

    def _browse(self):
        from tkinter import filedialog

        path = filedialog.askdirectory(title="选择 Profile 目录")
        if not path:
            path = filedialog.askopenfilename(
                title="选择 Profile 归档",
                filetypes=[("tar.gz 归档", "*.tar.gz"), ("所有文件", "*.*")],
            )
        if path:
            self.path_entry.delete(0, "end")
            self.path_entry.insert(0, path)

    def _on_import(self):
        source = self.path_entry.get().strip()
        if not source:
            self.path_entry.configure(border_width=2)
            return
        name = self.name_entry.get().strip() or None
        self.result = {
            "source": source,
            "name": name,
        }
        self.destroy()


class BackupSelectDialog(ctk.CTkToplevel):
    def __init__(self, parent, backups: list, dcc_name: str, dcc_version: str):
        super().__init__(parent)
        self.title(f"恢复备份 — {dcc_name} {dcc_version}")
        self.geometry("500x400")
        self.resizable(True, True)
        self.transient(parent)
        self.grab_set()

        self.backups = backups
        self.result = None

        frame = ctk.CTkFrame(self)
        frame.pack(fill="both", expand=True, padx=20, pady=20)

        ctk.CTkLabel(
            frame,
            text=f"选择要恢复的备份（共 {len(backups)} 个）",
            font=ctk.CTkFont(size=_Theme.FONT_SIZE_TITLE, weight="bold"),
        ).pack(pady=(0, 10))

        list_frame = ctk.CTkScrollableFrame(frame)
        list_frame.pack(fill="both", expand=True, pady=(0, 15))

        self._selected_index: int | None = None
        self._radio_vars: list[ctk.StringVar] = []

        for i, backup in enumerate(backups):
            var = ctk.StringVar(value="" if i > 0 else "selected")
            self._radio_vars.append(var)

            row = ctk.CTkFrame(list_frame, fg_color="transparent")
            row.pack(fill="x", pady=2)

            ctk.CTkRadioButton(
                row,
                text="",
                variable=var,
                value="selected",
                command=lambda idx=i: self._on_select(idx),
            ).pack(side="left", padx=(5, 10))

            info_frame = ctk.CTkFrame(row, fg_color="transparent")
            info_frame.pack(side="left", fill="x", expand=True)

            ctk.CTkLabel(
                info_frame,
                text=backup.name,
                font=ctk.CTkFont(size=_Theme.FONT_SIZE_NORMAL, weight="bold"),
                anchor="w",
            ).pack(fill="x")

            stat = backup.stat()
            mtime = datetime.fromtimestamp(stat.st_mtime, tz=UTC).strftime("%Y-%m-%d %H:%M:%S")
            size_kb = stat.st_size / 1024
            ctk.CTkLabel(
                info_frame,
                text=f"{mtime}  ·  {size_kb:.1f} KB",
                font=ctk.CTkFont(size=_Theme.FONT_SIZE_SMALL),
                text_color=_Theme.COLOR_TEXT_MUTED,
                anchor="w",
            ).pack(fill="x")

            for widget in (row, info_frame):
                widget.bind("<Button-1>", lambda e, idx=i: self._on_row_click(idx))
                widget.bind("<Double-Button-1>", lambda e, idx=i: self._on_row_double_click(idx))

        if backups:
            self._selected_index = 0

        btn_frame = ctk.CTkFrame(frame, fg_color="transparent")
        btn_frame.pack(fill="x")

        ctk.CTkButton(
            btn_frame,
            text="取消",
            width=100,
            command=self.destroy,
            fg_color="gray40",
            hover_color="gray30",
        ).pack(side="right", padx=5)

        ctk.CTkButton(
            btn_frame,
            text="恢复选中",
            width=100,
            command=self._on_restore,
            fg_color=_Theme.COLOR_PRIMARY,
            hover_color=_Theme.COLOR_PRIMARY_HOVER,
        ).pack(side="right", padx=5)

    def _on_select(self, index: int):
        self._selected_index = index

    def _on_row_click(self, index: int):
        self._on_select(index)
        for i, var in enumerate(self._radio_vars):
            var.set("selected" if i == index else "")

    def _on_row_double_click(self, index: int):
        self._on_select(index)
        self._on_restore()

    def _on_restore(self):
        if self._selected_index is None:
            return
        self.result = self.backups[self._selected_index]
        self.destroy()
