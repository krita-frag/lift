# Lift

轻量级 DCC 启动器，支持 Maya、Houdini 等工具的环境隔离与一键切换。
![lift](./images/screenshot.png)

> ⚠️ 🍎 仅 macOS 测试通过，Windows / Linux 待验证

## 定位

面向影视/游戏行业的 DCC（Digital Content Creation）软件启动器，解决多项目环境冲突问题：

- **环境隔离**: 每个项目拥有独立的插件、脚本、首选项
- **一键切换**: 通过 GUI 选择项目和 DCC，自动解析并启动
- **可定制**： 用户可自定义项目配置，添加插件、脚本、首选项等。

## 架构

```
Zig 启动器 (src/)
  └─ 加载 Python 运行时 → 执行 app/main.py

Python 应用 (app/)
  └─ main.py    # 应用入口

构建脚本 (build.py)
  └─ uv 管理依赖、打包分发
```

## 快速开始

### 构建

```bash
brew install tcl-tk python-tk  # 安装 tkinter 库(仅 macOS)
zig build           # 编译启动器
uv sync             # 同步依赖
uv run build.py     # 构建完整分发包
```

### 运行

```bash
./dist/bin/lift     # 启动 GUI
```

## 配置

在 `packages/` 目录下创建包，GUI 自动发现，以下是package目录结构：
| 目录          | 定位     | 内容                                                         |
| ----------- | ------ | ---------------------------------------------------------- |
| **`app/`**  | DCC 软件 | 指向系统已安装的 Maya、Houdini、Nuke、Blender 等本体。纯引用，不携带载荷。负责 DCC 发现与环境配置。 | 
| **`ext/`**  | 插件扩展 | Arnold、Redshift、Mgear、自定义工具集等。可自包含（带 `.mll`/`.py`）或引用系统插件。`ext/lift_profile` 提供 DCC 端 Profile 导出功能。 |
| **`int/`**  | 基础环境 | Python 运行时、通用库、跨项目工具脚本。被 `app` 和 `ext` 隐式或显式依赖。            |
| **`proj/`** | 项目配置 | **用户直接选用的入口**。纯依赖声明，只声明"这个项目需要哪些 app + ext + int 组合"。不包含 DCC 发现逻辑。 | 

### Profile 系统

`profiles/` 目录存储用户的 DCC 配置快照（偏好、插件列表、脚本等），支持跨机器迁移：

- **导出**: 从当前 DCC 环境导出用户数据到 Profile（通过 `ext/lift_profile` 在 DCC 内执行）
- **注入**: 启动 DCC 时选择 Profile，自动注入偏好和脚本路径
- **迁移**: 将 `profiles/` 目录复制到新机器即可恢复全部配置

每个 Profile 包含 `manifest.json` 元数据文件，记录 DCC 类型、版本、平台、插件列表等信息。


## 平台差异

| 平台 | Python 来源 | 说明 |
|------|-------------|------|
| Linux/macOS | 系统 Python | 运行时动态加载系统 Python |
| Windows | Embeddable | 打包到 `libexec/python3/` |

### 自定义 Python 库路径

通过环境变量 `LIFT_PYTHON_LIB` 可以指定自定义的 Python 库路径：

```bash
# macOS
export LIFT_PYTHON_LIB=/usr/local/lib/python3.11

# Windows
set LIFT_PYTHON_LIB=C:\Python311\libs
```

优先级：
1. 环境变量 `LIFT_PYTHON_LIB`（如果设置）
2. Windows: `libexec/python3/` 下的 embeddable Python
3. Linux/macOS: 系统 Python 库（运行时动态加载）

## 依赖

- Zig 0.16.0+
- uv
- Python 3.10+（仅 Windows 构建时）
- tkinter (仅Linux/MacOS)

## 使用手册

### 1. 启动与项目选择

```bash
./dist/bin/lift     # 启动 GUI
```

1. **选择项目**: 顶部工具栏选择 `分类` → `包` → `版本`
2. **解析环境**: 点击 `▶ 解析环境`，等待环境解析完成
3. **选择 Profile** (可选): 从 Profile 下拉菜单选择配置快照

### 2. 启动 DCC

**工具 Tab** 显示可启动的软件：
- 点击 `启动` 启动 DCC
- **临时模式**: 仅本次启动生效，不修改用户目录（默认）
- **默认模式**: 写入用户目录并自动备份原配置（在 Profile Tab 切换）

### 3. Profile 管理

**导出本机配置**:
1. 打开 Profile Tab
2. 点击 `导出本机配置`，输入名称和描述
3. 当前 DCC 的用户数据被导出到 `profiles/` 目录

**导入 Profile**:
1. 点击 `导入`
2. 选择 Profile 目录或 `.tar.gz` 归档文件
3. 可重命名后导入

**删除 Profile**:
1. 在列表中勾选要删除的 Profile（支持多选）
2. 点击 `删除`

**打包分享**:
1. 点击 Profile 条目右侧的 `打包`
2. 选择保存位置，生成 `.tar.gz` 文件
3. 复制到其他机器即可导入

### 4. 应用模式说明

| 模式 | 行为 | 适用场景 |
|------|------|----------|
| **只读** | Profile 复制到临时目录，通过环境变量指向 | 快速测试、不污染用户配置 |
| **覆盖** | Profile 复制到 DCC 用户目录 | 长期使用、跨机器同步 |
| **读写** | 直接指向 Profile 目录 | 开发调试，会污染 Profile |

切换模式：Profile Tab → 应用模式 → 选择 `只读`、`覆盖` 或 `读写`

## 参考项目

- **[PyStand](https://github.com/skywind3000/PyStand)**: 轻量级 Python 独立部署方案，使用 C++ 语言编写的启动器加载 Python 运行时。
- **[rez-for-projects](https://github.com/mottosso/rez-for-projects)**: Rez 包管理系统的项目示例，展示如何使用 Rez 管理复杂 DCC 项目的环境配置与依赖解析。
