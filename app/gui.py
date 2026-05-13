#!/usr/bin/env python3

import os
import subprocess
import threading

import customtkinter as ctk
from rez.resolved_context import ResolvedContext

from app.utils import discover_tools, scan_packages


class LiftLauncher(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Lift Launcher")
        self.geometry("900x600")
        self.minsize(800, 500)
        ctk.set_appearance_mode("System")

        self.selected_category = None
        self.selected_pkg = None
        self.selected_ver = None
        self.resolved_context = None
        self.discovered_tools = []

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
            width=120,
            font=ctk.CTkFont(size=12),
        )
        self.cat_menu.pack(side="left", padx=5)

        ctk.CTkLabel(toolbar, text="包:", font=ctk.CTkFont(size=12)).pack(side="left", padx=(15, 5))
        self.pkg_menu = ctk.CTkOptionMenu(
            toolbar,
            values=["选择包"],
            command=self.on_pkg_change,
            width=150,
            font=ctk.CTkFont(size=12),
            state="disabled",
        )
        self.pkg_menu.pack(side="left", padx=5)

        ctk.CTkLabel(toolbar, text="版本:", font=ctk.CTkFont(size=12)).pack(side="left", padx=(15, 5))
        self.ver_menu = ctk.CTkOptionMenu(
            toolbar,
            values=["选择版本"],
            command=self.on_ver_change,
            width=100,
            font=ctk.CTkFont(size=12),
            state="disabled",
        )
        self.ver_menu.pack(side="left", padx=5)

        self.refresh_btn = ctk.CTkButton(
            toolbar,
            text="⟳ 刷新",
            width=80,
            command=self._refresh_packages,
            font=ctk.CTkFont(size=11),
        )
        self.refresh_btn.pack(side="right", padx=10)

        self.resolve_btn = ctk.CTkButton(
            toolbar,
            text="▶ 解析环境",
            width=100,
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

    def _refresh_packages(self):
        self.packages_data = scan_packages()

        cat_list = list(self.packages_data.keys()) if self.packages_data else []
        if not cat_list:
            self.cat_menu.configure(values=["无分类"])
            self.cat_menu.set("无分类")
            self.pkg_menu.configure(values=["选择包"], state="disabled")
            self.ver_menu.configure(values=["选择版本"], state="disabled")
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

    def on_cat_change(self, category):
        self.selected_category = category
        self.selected_pkg = None
        self.selected_ver = None
        self.resolved_context = None
        self.discovered_tools = []
        self._clear_tools()

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
        self.selected_ver = None
        self.resolved_context = None
        self.discovered_tools = []
        self._clear_tools()

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
        self.resolved_context = None
        self.discovered_tools = []
        self._clear_tools()
        self.resolve_btn.configure(state="normal")

        self._update_info()
        self._update_pkg_info()
        self.log(f"选择版本: {ver}")

    def _update_info(self):
        if self.selected_category and self.selected_pkg and self.selected_ver:
            self.info_label.configure(
                text=f"{self.selected_category} / {self.selected_pkg} - {self.selected_ver}",
                text_color="white",
            )
        elif self.selected_category and self.selected_pkg:
            self.info_label.configure(
                text=f"{self.selected_category} / {self.selected_pkg} - 请选择版本",
                text_color="gray60",
            )
        else:
            self.info_label.configure(
                text="请选择分类、包和版本",
                text_color="gray60",
            )

    def _update_pkg_info(self):
        self.pkg_info_box.delete("1.0", "end")

        if not self.selected_category or not self.selected_pkg or not self.selected_ver:
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
            self.resolved_context = context
            env = context.get_environ()

            self._gui_log(f"✓ 解析成功: {context.status}")
            self._gui_log(f"  包数量: {len(context.resolved_packages)}")
            self._gui_log(f"  环境变量: {len(env)} 个")

            env_text = ""
            for key in sorted(env.keys()):
                val = env[key]
                if isinstance(val, list):
                    val = os.pathsep.join(val)
                if any(x in key for x in ["PATH", "MAYA", "HOUDINI", "NUKE", "BLENDER", "REZ", "PYTHON"]):
                    env_text += f"{key}={val}\n"

            self.after(0, lambda: self.env_box.insert("end", env_text))

            tools = discover_tools(context)
            self.discovered_tools = tools
            self.after(0, self._render_tools)

            self.after(0, lambda: self.status("环境解析完成"))

        except Exception as e:
            self._gui_log(f"✗ 解析失败: {e}", error=True)
            self.after(0, lambda: self.status(f"错误: {e}"))
        finally:
            self.after(0, lambda: self.resolve_btn.configure(
                state="normal", text="▶ 解析环境"
            ))

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
                width=80,
                command=lambda t=tool: self.launch_tool(t),
                font=ctk.CTkFont(size=11),
                fg_color="#28A745",
                hover_color="#218838",
            )
            launch_btn.pack(side="right", padx=10, pady=3)

    def launch_tool(self, tool: dict):
        if not self.resolved_context:
            self.log("请先解析环境", error=True)
            return

        tool_name = tool["name"]
        tool_path = tool["path"]
        env = self.resolved_context.get_environ()

        self.log(f"启动: {tool_name} ({tool_path})")
        self.status(f"正在启动 {tool_name}...")

        thread = threading.Thread(
            target=self._launch_thread,
            args=(tool_name, tool_path, env),
            daemon=True,
        )
        thread.start()

    def _serialize_env(self, env: dict) -> dict[str, str]:
        """确保环境变量所有值均为字符串，避免 subprocess.Popen 序列化失败。"""
        serialized: dict[str, str] = {}
        for key, val in env.items():
            if isinstance(val, list):
                serialized[key] = os.pathsep.join(val)
            else:
                serialized[key] = str(val)
        return serialized

    def _launch_thread(self, tool_name: str, tool_path: str, env: dict):
        try:
            clean_env = self._serialize_env(env)
            subprocess.Popen([tool_path], env=clean_env)
            self._gui_log(f"✓ 进程已启动: {tool_name}")
            self.after(0, self.status(f"{tool_name} 已启动"))
        except Exception as e:
            self._gui_log(f"✗ 启动失败: {e}", error=True)
            self.after(0, self.status(f"错误: {e}"))

    def log(self, msg, error=False):
        prefix = "✗ " if error else ""
        self.log_box.insert("end", f"{prefix}{msg}\n")
        self.log_box.see("end")

    def _gui_log(self, msg, error=False):
        self.after(0, self.log(msg, error))

    def status(self, text):
        self.after(0, lambda: self.status_label.configure(text=text))


def main():
    app = LiftLauncher()
    app.mainloop()


if __name__ == "__main__":
    main()
