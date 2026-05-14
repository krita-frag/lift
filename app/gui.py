#!/usr/bin/env python3

import os
import subprocess
import threading

import customtkinter as ctk
from rez.resolved_context import ResolvedContext

from app.profile import (
    apply_profile,
    delete_profile,
    detect_dcc_from_context,
    export_profile,
    get_profiles_for_dcc,
    import_profile,
    pack_profile,
    scan_profiles,
)
from app.utils import discover_tools, scan_packages, serialize_env


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
            font=ctk.CTkFont(size=14, weight="bold"),
        ).pack(pady=(0, 15))

        ctk.CTkLabel(frame, text="Profile 名称:", font=ctk.CTkFont(size=12)).pack(anchor="w")
        self.name_entry = ctk.CTkEntry(frame, placeholder_text="my_maya_setup", width=360)
        self.name_entry.pack(pady=(0, 10))

        ctk.CTkLabel(frame, text="描述 (可选):", font=ctk.CTkFont(size=12)).pack(anchor="w")
        self.desc_entry = ctk.CTkEntry(frame, placeholder_text="我的 Maya 配置", width=360)
        self.desc_entry.pack(pady=(0, 15))

        btn_frame = ctk.CTkFrame(frame, fg_color="transparent")
        btn_frame.pack(fill="x")

        ctk.CTkButton(
            btn_frame, text="取消", width=100, command=self.destroy,
            fg_color="gray40", hover_color="gray30",
        ).pack(side="right", padx=5)

        ctk.CTkButton(
            btn_frame, text="导出", width=100, command=self._on_export,
            fg_color="#28A745", hover_color="#218838",
        ).pack(side="right", padx=5)

        self.name_entry.focus_set()

    def _on_export(self):
        name = self.name_entry.get().strip()
        if not name:
            self.name_entry.configure(border_color="red")
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
            font=ctk.CTkFont(size=14, weight="bold"),
        ).pack(pady=(0, 15))

        ctk.CTkLabel(frame, text="源路径:", font=ctk.CTkFont(size=12)).pack(anchor="w")
        self.path_entry = ctk.CTkEntry(frame, placeholder_text="/path/to/profile 或 /path/to/profile.tar.gz", width=360)
        self.path_entry.pack(pady=(0, 10))

        ctk.CTkLabel(frame, text="重命名 (可选，留空使用原名):", font=ctk.CTkFont(size=12)).pack(anchor="w")
        self.name_entry = ctk.CTkEntry(frame, placeholder_text="自定义名称", width=360)
        self.name_entry.pack(pady=(0, 15))

        btn_frame = ctk.CTkFrame(frame, fg_color="transparent")
        btn_frame.pack(fill="x")

        ctk.CTkButton(
            btn_frame, text="取消", width=100, command=self.destroy,
            fg_color="gray40", hover_color="gray30",
        ).pack(side="right", padx=5)

        ctk.CTkButton(
            btn_frame, text="浏览...", width=80, command=self._browse,
        ).pack(side="left", padx=5)

        ctk.CTkButton(
            btn_frame, text="导入", width=100, command=self._on_import,
            fg_color="#2B7DE9", hover_color="#1E5DB5",
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
            self.path_entry.configure(border_color="red")
            return
        name = self.name_entry.get().strip() or None
        self.result = {
            "source": source,
            "name": name,
        }
        self.destroy()


class LiftLauncher(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Lift Launcher")
        self.geometry("960x640")
        self.minsize(800, 500)
        ctk.set_appearance_mode("System")

        self.selected_category = None
        self.selected_pkg = None
        self.selected_ver = None
        self.selected_profile = None
        self.profile_mode = "read"
        self.resolved_context = None
        self.discovered_tools = []
        self.detected_dccs = []
        self._launching = False
        self._selected_profiles_for_delete = set()

        self._build_ui()
        self._refresh_packages()

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        toolbar = ctk.CTkFrame(self, height=60)
        toolbar.grid(row=0, column=0, padx=10, pady=10, sticky="ew")
        toolbar.grid_propagate(False)

        ctk.CTkLabel(toolbar, text="分类:", font=ctk.CTkFont(size=12)).pack(side="left", padx=(10, 5))
        self.cat_menu = ctk.CTkOptionMenu(
            toolbar,
            values=["选择分类"],
            command=self.on_cat_change,
            width=100,
            font=ctk.CTkFont(size=12),
        )
        self.cat_menu.pack(side="left", padx=5)

        ctk.CTkLabel(toolbar, text="包:", font=ctk.CTkFont(size=12)).pack(side="left", padx=(10, 5))
        self.pkg_menu = ctk.CTkOptionMenu(
            toolbar,
            values=["选择包"],
            command=self.on_pkg_change,
            width=130,
            font=ctk.CTkFont(size=12),
            state="disabled",
        )
        self.pkg_menu.pack(side="left", padx=5)

        ctk.CTkLabel(toolbar, text="版本:", font=ctk.CTkFont(size=12)).pack(side="left", padx=(10, 5))
        self.ver_menu = ctk.CTkOptionMenu(
            toolbar,
            values=["选择版本"],
            command=self.on_ver_change,
            width=80,
            font=ctk.CTkFont(size=12),
            state="disabled",
        )
        self.ver_menu.pack(side="left", padx=5)

        ctk.CTkLabel(toolbar, text="Profile:", font=ctk.CTkFont(size=12)).pack(side="left", padx=(10, 5))
        self.profile_menu = ctk.CTkOptionMenu(
            toolbar,
            values=["无"],
            command=self.on_profile_change,
            width=130,
            font=ctk.CTkFont(size=12),
            state="disabled",
        )
        self.profile_menu.pack(side="left", padx=5)

        self.refresh_btn = ctk.CTkButton(
            toolbar,
            text="⟳ 刷新",
            width=70,
            command=self._refresh_packages,
            font=ctk.CTkFont(size=11),
        )
        self.refresh_btn.pack(side="right", padx=10)

        self.resolve_btn = ctk.CTkButton(
            toolbar,
            text="▶ 解析环境",
            width=90,
            command=self.resolve_env,
            state="disabled",
            font=ctk.CTkFont(size=12),
            fg_color="#2B7DE9",
            hover_color="#1E5DB5",
        )
        self.resolve_btn.pack(side="right", padx=10)

        content = ctk.CTkFrame(self)
        content.grid(row=1, column=0, padx=10, pady=(0, 10), sticky="nsew")
        content.grid_columnconfigure(0, weight=1)
        content.grid_rowconfigure(1, weight=1)

        self.info_frame = ctk.CTkFrame(content, height=40)
        self.info_frame.grid(row=0, column=0, padx=10, pady=10, sticky="ew")
        self.info_frame.grid_propagate(False)

        self.info_label = ctk.CTkLabel(
            self.info_frame,
            text="请选择分类、包和版本",
            font=ctk.CTkFont(size=12),
            text_color="gray60",
        )
        self.info_label.pack(side="left", padx=10, pady=8)

        self.tabview = ctk.CTkTabview(content)
        self.tabview.grid(row=1, column=0, padx=10, pady=(0, 10), sticky="nsew")

        self.tab_log = self.tabview.add("日志")
        self.tab_env = self.tabview.add("环境变量")
        self.tab_pkg = self.tabview.add("包信息")
        self.tab_tools = self.tabview.add("工具")
        self.tab_profile = self.tabview.add("Profile")

        self.log_box = ctk.CTkTextbox(
            self.tab_log,
            wrap="word",
            font=("Consolas", 11),
        )
        self.log_box.pack(fill="both", expand=True, padx=5, pady=5)

        self.env_box = ctk.CTkTextbox(
            self.tab_env,
            wrap="none",
            font=("Consolas", 10),
        )
        self.env_box.pack(fill="both", expand=True, padx=5, pady=5)

        self.pkg_info_box = ctk.CTkTextbox(
            self.tab_pkg,
            wrap="word",
            font=("Consolas", 11),
        )
        self.pkg_info_box.pack(fill="both", expand=True, padx=5, pady=5)

        self.tools_frame = ctk.CTkScrollableFrame(self.tab_tools)
        self.tools_frame.pack(fill="both", expand=True, padx=5, pady=5)

        self._build_profile_tab()

        self.status_bar = ctk.CTkFrame(self, height=30)
        self.status_bar.grid(row=2, column=0, padx=10, pady=(0, 10), sticky="ew")
        self.status_bar.grid_propagate(False)

        self.status_label = ctk.CTkLabel(
            self.status_bar,
            text="就绪",
            font=ctk.CTkFont(size=11),
            text_color="gray60",
        )
        self.status_label.pack(side="left", padx=10, pady=5)

    def _build_profile_tab(self):
        btn_frame = ctk.CTkFrame(self.tab_profile)
        btn_frame.pack(fill="x", padx=5, pady=5)

        ctk.CTkButton(
            btn_frame, text="导出本机配置", width=110,
            command=self._on_export_profile,
            font=ctk.CTkFont(size=11),
            fg_color="#28A745", hover_color="#218838",
        ).pack(side="left", padx=5)

        ctk.CTkButton(
            btn_frame, text="导入", width=70,
            command=self._on_import_profile,
            font=ctk.CTkFont(size=11),
            fg_color="#6C757D", hover_color="#5A6268",
        ).pack(side="left", padx=5)

        ctk.CTkButton(
            btn_frame, text="删除", width=70,
            command=self._on_delete_profile,
            font=ctk.CTkFont(size=11),
            fg_color="#DC3545", hover_color="#C82333",
        ).pack(side="left", padx=5)

        ctk.CTkButton(
            btn_frame, text="⟳ 刷新", width=70,
            command=self._refresh_profile_list,
            font=ctk.CTkFont(size=11),
        ).pack(side="right", padx=5)

        mode_frame = ctk.CTkFrame(self.tab_profile)
        mode_frame.pack(fill="x", padx=5, pady=(5, 0))

        ctk.CTkLabel(
            mode_frame,
            text="应用模式:",
            font=ctk.CTkFont(size=12),
        ).pack(side="left", padx=10, pady=5)

        self.mode_var = ctk.StringVar(value="read")

        # 临时模式：只读，使用临时目录
        self.mode_read = ctk.CTkRadioButton(
            mode_frame,
            text="只读",
            variable=self.mode_var,
            value="read",
            command=self._on_mode_change,
            font=ctk.CTkFont(size=11),
        )
        self.mode_read.pack(side="left", padx=10, pady=5)

        # 链接模式：读写，直接定位到 profile 目录（有污染风险）
        self.mode_write = ctk.CTkRadioButton(
            mode_frame,
            text="读写",
            variable=self.mode_var,
            value="write",
            command=self._on_mode_change,
            font=ctk.CTkFont(size=11),
        )
        self.mode_write.pack(side="left", padx=10, pady=5)

        # 覆盖模式：替换用户原有配置
        self.mode_global = ctk.CTkRadioButton(
            mode_frame,
            text="覆盖",
            variable=self.mode_var,
            value="global",
            command=self._on_mode_change,
            font=ctk.CTkFont(size=11),
        )
        self.mode_global.pack(side="left", padx=10, pady=5)

        self.mode_hint = ctk.CTkLabel(
            mode_frame,
            text="仅本次启动生效，不修改用户目录",
            font=ctk.CTkFont(size=10),
            text_color="gray60",
        )
        self.mode_hint.pack(side="left", padx=10, pady=5)

        self.profile_list_frame = ctk.CTkScrollableFrame(self.tab_profile)
        self.profile_list_frame.pack(fill="both", expand=True, padx=5, pady=5)

        self._refresh_profile_list()

    def _on_mode_change(self):
        """处理模式切换事件，更新提示文本。"""
        self.profile_mode = self.mode_var.get()
        hints = {
            "read": (
                "临时目录，只读，安全无风险",
                "gray60",
            ),
            "write": (
                "直接指向 Profile 目录，可读写，DCC配置会污染 Profile",
                "#FFC107",
            ),
            "global": (
                "覆盖用户目录，自动备份原配置",
                "#FD7E14",
            ),
        }
        text, color = hints.get(self.profile_mode, ("", "gray60"))
        self.mode_hint.configure(text=text, text_color=color)

    def _toggle_profile_selection(self, profile_name: str, checkbox: ctk.CTkCheckBox):
        if profile_name in self._selected_profiles_for_delete:
            self._selected_profiles_for_delete.discard(profile_name)
            checkbox.deselect()
        else:
            self._selected_profiles_for_delete.add(profile_name)
            checkbox.select()

    def _refresh_profile_list(self):
        for widget in self.profile_list_frame.winfo_children():
            widget.destroy()

        profiles = scan_profiles()
        if not profiles:
            ctk.CTkLabel(
                self.profile_list_frame,
                text="暂无 Profile。点击「导出本机配置」或「导入」添加。",
                text_color="gray60",
            ).pack(pady=20)
            return

        for name, info in profiles.items():
            manifest = info["manifest"]
            frame = ctk.CTkFrame(self.profile_list_frame)
            frame.pack(fill="x", padx=5, pady=3)

            # Checkbox for selection
            is_selected = name in self._selected_profiles_for_delete
            checkbox = ctk.CTkCheckBox(
                frame, text="",
                width=20,
            )
            checkbox.configure(
                command=lambda n=name, cb=checkbox: self._toggle_profile_selection(n, cb)
            )
            if is_selected:
                checkbox.select()
            checkbox.pack(side="left", padx=(10, 5), pady=5)

            text = f"{name}  ({manifest['dcc']} {manifest['dcc_version']})"
            ctk.CTkLabel(
                frame, text=text,
                font=ctk.CTkFont(size=12, weight="bold"),
            ).pack(side="left", padx=5, pady=5)

            if manifest.get("description"):
                ctk.CTkLabel(
                    frame, text=manifest["description"],
                    font=ctk.CTkFont(size=11),
                    text_color="gray60",
                ).pack(side="left", padx=5, pady=5)

            platform_text = manifest.get("platform", "")
            if platform_text:
                ctk.CTkLabel(
                    frame, text=platform_text,
                    font=ctk.CTkFont(size=10),
                    text_color="gray50",
                ).pack(side="right", padx=10, pady=5)

            plugin_count = len(manifest.get("plugins", []))
            if plugin_count > 0:
                ctk.CTkLabel(
                    frame, text=f"{plugin_count} 插件",
                    font=ctk.CTkFont(size=10),
                    text_color="gray50",
                ).pack(side="right", padx=5, pady=5)

            pack_btn = ctk.CTkButton(
                frame, text="打包", width=50,
                command=lambda n=name: self._on_pack_profile(n),
                font=ctk.CTkFont(size=10),
                fg_color="#6C757D", hover_color="#5A6268",
            )
            pack_btn.pack(side="right", padx=5, pady=3)

    def _on_export_profile(self):
        if not self.detected_dccs:
            self.log("请先解析环境以检测 DCC", error=True)
            return

        dcc = self.detected_dccs[0]
        dialog = ProfileExportDialog(self, dcc["name"], dcc["version"])
        self.wait_window(dialog)

        if dialog.result:
            try:
                export_profile(
                    profile_name=dialog.result["name"],
                    dcc=dcc["name"],
                    dcc_version=dcc["version"],
                    description=dialog.result["description"],
                )
                self.log(f"✓ Profile 已导出: {dialog.result['name']}")
                self._refresh_profile_list()
                self._refresh_profile_dropdown()
            except (FileNotFoundError, FileExistsError, Exception) as e:
                self.log(f"✗ 导出失败: {e}", error=True)

    def _on_import_profile(self):
        dialog = ProfileImportDialog(self)
        self.wait_window(dialog)

        if dialog.result:
            try:
                imported_dir = import_profile(
                    source=dialog.result["source"],
                    name=dialog.result["name"],
                )
                self.log(f"✓ Profile 已导入: {imported_dir.name}")
                self._refresh_profile_list()
                self._refresh_profile_dropdown()
            except Exception as e:
                self.log(f"✗ 导入失败: {e}", error=True)

    def _on_delete_profile(self):
        if not self._selected_profiles_for_delete:
            self.log("请先在列表中勾选要删除的 Profile", error=True)
            return

        profiles_to_delete = list(self._selected_profiles_for_delete)
        deleted_count = 0
        failed_profiles = []

        for profile_name in profiles_to_delete:
            try:
                delete_profile(profile_name)
                deleted_count += 1
                self._selected_profiles_for_delete.discard(profile_name)
                # If the deleted profile was selected in dropdown, clear it
                if self.selected_profile == profile_name:
                    self.selected_profile = None
            except Exception as e:
                failed_profiles.append((profile_name, str(e)))

        if deleted_count > 0:
            self.log(f"✓ 已删除 {deleted_count} 个 Profile")
            self._refresh_profile_list()
            self._refresh_profile_dropdown()

        if failed_profiles:
            for name, error in failed_profiles:
                self.log(f"✗ 删除失败 '{name}': {error}", error=True)

    def _on_pack_profile(self, profile_name: str):
        from tkinter import filedialog
        dest_path = filedialog.asksaveasfilename(
            title="导出 Profile 压缩包",
            defaultextension=".tar.gz",
            initialfile=f"{profile_name}.tar.gz",
            filetypes=[("tar.gz 归档", "*.tar.gz"), ("所有文件", "*.*")],
        )
        if not dest_path:
            return

        try:
            archive_path = pack_profile(profile_name, output_path=dest_path)
            self.log(f"✓ Profile 已导出: {archive_path}")
        except Exception as e:
            self.log(f"✗ 导出失败: {e}", error=True)

    def _refresh_packages(self):
        self.packages_data = scan_packages()

        cat_list = list(self.packages_data.keys()) if self.packages_data else []
        if not cat_list:
            self.cat_menu.configure(values=["无分类"])
            self.cat_menu.set("无分类")
            self.pkg_menu.configure(values=["选择包"], state="disabled")
            self.ver_menu.configure(values=["选择版本"], state="disabled")
            self.profile_menu.configure(values=["无"], state="disabled")
            self.resolve_btn.configure(state="disabled")
            self.log("未在 packages/ 目录下发现任何包分类")
            self.status("无包")
            return

        self.cat_menu.configure(values=cat_list)
        self.cat_menu.set(cat_list[0])
        self.on_cat_change(cat_list[0])

        total = sum(
            len(versions)
            for cats in self.packages_data.values()
            for versions in cats.values()
        )
        self.log(f"发现 {total} 个包版本")
        self.status(f"已刷新 - {total} 个包版本")

    def _reset_selection_state(self, reset_pkg: bool = True, reset_ver: bool = True) -> None:
        """重置选择状态。"""
        if reset_pkg:
            self.selected_pkg = None
        if reset_ver:
            self.selected_ver = None
        self.resolved_context = None
        self.discovered_tools = []
        self.detected_dccs = []
        self._clear_tools()
        self._reset_profile_dropdown()

    def on_cat_change(self, category):
        self.selected_category = category
        self._reset_selection_state(reset_pkg=True, reset_ver=True)

        pkg_dict = self.packages_data.get(category, {})
        if not pkg_dict:
            self.pkg_menu.configure(values=["无包"], state="disabled")
            self.pkg_menu.set("无包")
            self.ver_menu.configure(values=["选择版本"], state="disabled")
            self.resolve_btn.configure(state="disabled")
            self._update_info()
            return

        pkg_list = list(pkg_dict.keys())
        self.pkg_menu.configure(values=pkg_list, state="normal")
        self.pkg_menu.set(pkg_list[0])
        self.on_pkg_change(pkg_list[0])
        self._update_info()

    def on_pkg_change(self, pkg_name):
        self.selected_pkg = pkg_name
        self._reset_selection_state(reset_pkg=False, reset_ver=True)

        versions = list(self.packages_data.get(self.selected_category, {}).get(pkg_name, {}).keys())
        if not versions:
            self.ver_menu.configure(values=["无版本"], state="disabled")
            self.resolve_btn.configure(state="disabled")
            self._update_info()
            self._update_pkg_info()
            self.log(f"选择包: {pkg_name} (无可用版本)")
            return

        versions.sort(reverse=True)
        self.ver_menu.configure(values=versions, state="normal")
        self.ver_menu.set(versions[0])
        self.on_ver_change(versions[0])

        self._update_info()
        self._update_pkg_info()
        self.log(f"选择包: {pkg_name}")

    def on_ver_change(self, ver):
        self.selected_ver = ver
        self._reset_selection_state(reset_pkg=False, reset_ver=False)
        self.resolve_btn.configure(state="normal")

        self._update_info()
        self._update_pkg_info()
        self.log(f"选择版本: {ver}")

    def on_profile_change(self, profile_name):
        self.selected_profile = profile_name if profile_name != "无" else None
        if self.selected_profile:
            self.log(f"选择 Profile: {profile_name}")
        self._update_info()

    def _reset_profile_dropdown(self):
        self.selected_profile = None
        self.profile_menu.configure(values=["无"], state="disabled")
        self.profile_menu.set("无")

    def _refresh_profile_dropdown(self):
        if not self.detected_dccs:
            self._reset_profile_dropdown()
            return

        dcc = self.detected_dccs[0]
        profiles = get_profiles_for_dcc(dcc["name"], dcc["version"])
        profile_names = ["无"] + list(profiles.keys())

        self.profile_menu.configure(values=profile_names, state="normal")
        if self.selected_profile and self.selected_profile in profile_names:
            self.profile_menu.set(self.selected_profile)
        else:
            self.profile_menu.set("无")
            self.selected_profile = None

    def _update_info(self):
        parts = []
        if self.selected_category and self.selected_pkg and self.selected_ver:
            parts.append(f"{self.selected_category} / {self.selected_pkg} - {self.selected_ver}")
        elif self.selected_category and self.selected_pkg:
            parts.append(f"{self.selected_category} / {self.selected_pkg} - 请选择版本")
        else:
            self.info_label.configure(text="请选择分类、包和版本", text_color="gray60")
            return

        if self.selected_profile:
            parts.append(f"Profile: {self.selected_profile}")

        self.info_label.configure(text="  |  ".join(parts), text_color="white")

    def _update_pkg_info(self):
        self.pkg_info_box.delete("1.0", "end")

        if not self.selected_category or not self.selected_pkg or self.selected_ver is None:
            self.pkg_info_box.insert("end", "请选择分类、包和版本查看详情")
            return

        pkg_path = self.packages_data.get(self.selected_category, {}).get(self.selected_pkg, {}).get(self.selected_ver)
        if pkg_path:
            self.pkg_info_box.insert("end", f"分类: {self.selected_category}\n")
            self.pkg_info_box.insert("end", f"包名: {self.selected_pkg}\n")
            self.pkg_info_box.insert("end", f"版本: {self.selected_ver}\n")
            self.pkg_info_box.insert("end", f"路径: {pkg_path}\n")

    def resolve_env(self):
        if not self.selected_pkg or not self.selected_ver:
            self.log("请先选择包和版本", error=True)
            return

        self.resolve_btn.configure(state="disabled", text="解析中...")
        self.status("正在解析环境...")
        self.env_box.delete("1.0", "end")
        self._clear_tools()

        thread = threading.Thread(target=self._resolve_thread, daemon=True)
        thread.start()

    def _resolve_thread(self):
        try:
            pkg_spec = f"{self.selected_pkg}-{self.selected_ver}"
            self._gui_log(f"解析: {pkg_spec}")

            context = ResolvedContext([pkg_spec])
            env = context.get_environ()

            self._gui_log(f"✓ 解析成功: {context.status}")
            self._gui_log(f"  包数量: {len(context.resolved_packages)}")
            self._gui_log(f"  环境变量: {len(env)} 个")

            detected_dccs = detect_dcc_from_context(context)
            if detected_dccs:
                for dcc in detected_dccs:
                    self._gui_log(f"  DCC: {dcc['name']} {dcc['version']}")

            env_text = ""
            for key in sorted(env.keys()):
                val = env[key]
                if isinstance(val, list):
                    val = os.pathsep.join(val)
                if any(x in key for x in ["PATH", "MAYA", "HOUDINI", "NUKE", "BLENDER", "REZ", "PYTHON"]):
                    env_text += f"{key}={val}\n"

            tools = discover_tools(context)

            self.after(0, lambda: self._on_resolve_success(
                context, env_text, tools, detected_dccs
            ))

        except Exception as e:
            self._gui_log(f"✗ 解析失败: {e}", error=True)
            error_msg = str(e)
            self.after(0, lambda msg=error_msg: self.status(f"错误: {msg}"))
        finally:
            self.after(0, lambda: self.resolve_btn.configure(
                state="normal", text="▶ 解析环境"
            ))

    def _on_resolve_success(
        self,
        context,
        env_text: str,
        tools: list[dict],
        detected_dccs: list[dict],
    ) -> None:
        self.resolved_context = context
        self.discovered_tools = tools
        self.detected_dccs = detected_dccs
        self.env_box.insert("end", env_text)
        self._render_tools()
        self._refresh_profile_dropdown()
        self.status("环境解析完成")

    def _clear_tools(self):
        for widget in self.tools_frame.winfo_children():
            widget.destroy()

        label = ctk.CTkLabel(
            self.tools_frame,
            text="解析环境后将显示可启动工具",
            text_color="gray60",
        )
        label.pack(pady=20)

    def _render_tools(self):
        self._clear_tools()

        if not self.discovered_tools:
            label = ctk.CTkLabel(
                self.tools_frame,
                text="未发现可启动工具",
                text_color="gray60",
            )
            label.pack(pady=20)
            return

        for tool in self.discovered_tools:
            frame = ctk.CTkFrame(self.tools_frame)
            frame.pack(fill="x", padx=5, pady=3)

            name_label = ctk.CTkLabel(
                frame,
                text=tool["name"],
                font=ctk.CTkFont(size=13, weight="bold"),
            )
            name_label.pack(side="left", padx=10, pady=5)

            pkg_label = ctk.CTkLabel(
                frame,
                text=f"({tool['package']})",
                font=ctk.CTkFont(size=11),
                text_color="gray60",
            )
            pkg_label.pack(side="left", padx=5, pady=5)

            launch_btn = ctk.CTkButton(
                frame,
                text="启动",
                width=70,
                command=lambda t=tool: self.launch_tool(t),
                font=ctk.CTkFont(size=11),
                fg_color="#2B7DE9",
                hover_color="#1E5DB5",
            )
            launch_btn.pack(side="right", padx=5, pady=3)

    def launch_tool(self, tool: dict):
        if not self.resolved_context:
            self.log("请先解析环境", error=True)
            return

        if self._launching:
            self.log("已有启动任务进行中，请稍候", error=True)
            return

        self._launching = True
        self._set_tool_buttons_state("disabled")
        self.update()

        tool_name = tool["name"]
        tool_path = tool["path"]
        env = self.resolved_context.get_environ()
        mode = self.profile_mode

        if self.selected_profile:
            try:
                dcc = self.detected_dccs[0] if self.detected_dccs else None
                dcc_name = dcc["name"] if dcc else None
                dcc_version = dcc["version"] if dcc else None
                env = apply_profile(
                    self.selected_profile,
                    env,
                    mode=mode,
                    dcc=dcc_name,
                    dcc_version=dcc_version,
                )
                if mode == "global":
                    self.log(f"✓ Profile 已应用为默认配置: {self.selected_profile}")
                else:
                    self.log(f"已应用 Profile（临时）: {self.selected_profile}")
            except Exception as e:
                self.log(f"✗ 应用 Profile 失败: {e}", error=True)
                self._launching = False
                self._set_tool_buttons_state("normal")
                return

        mode_label = "临时" if mode == "read" else "默认"
        self.log(f"启动 ({mode_label}): {tool_name} ({tool_path})")
        self.status(f"正在启动 {tool_name} ({mode_label})...")

        thread = threading.Thread(
            target=self._launch_thread,
            args=(tool_name, tool_path, env),
            daemon=True,
        )
        thread.start()

    def _set_tool_buttons_state(self, state: str):
        for frame in self.tools_frame.winfo_children():
            for widget in frame.winfo_children():
                if isinstance(widget, ctk.CTkButton):
                    widget.configure(state=state)

    def _launch_thread(self, tool_name: str, tool_path: str, env: dict):
        try:
            clean_env = serialize_env(env)
            subprocess.Popen([tool_path], env=clean_env)
            self._gui_log(f"✓ 进程已启动: {tool_name}")
            self.after(0, self.status(f"{tool_name} 已启动"))
        except Exception as e:
            self._gui_log(f"✗ 启动失败: {e}", error=True)
            self.after(0, self.status(f"错误: {e}"))
        finally:
            self.after(0, lambda: setattr(self, "_launching", False))
            self.after(0, lambda: self._set_tool_buttons_state("normal"))

    def log(self, msg, error=False):
        prefix = "✗ " if error else ""
        self.log_box.insert("end", f"{prefix}{msg}\n")
        self.log_box.see("end")

    def _gui_log(self, msg, error=False):
        self.after(0, self.log, msg, error)

    def status(self, text):
        self.after(0, lambda: self.status_label.configure(text=text))



