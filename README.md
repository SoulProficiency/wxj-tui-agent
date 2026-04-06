# WXJ — Python TUI AI Coding Assistant

```
__      __ __  __       _
\ \    / / \ \/ /      | |
 \ \  / /   >  <    _  | |
  \ \/ /   / /\ \  | |_/ /
   \__/   /_/  \_\  \___/
  AI Coding Assistant  v0.1.0
```

一个基于终端的 AI 编程助手，使用 Python + [Textual](https://textual.textualize.io/) 构建，支持多 Provider（Anthropic / Alibaba Cloud 阿里云百炼 / MiniMax / OpenAI-compatible）、工具调用、MCP 协议、Skills、长期记忆和 Plan Mode。由 wangxuejian 个人开发维护。

---

## 目录

1. [环境要求](#1-环境要求)
2. [安装与启动](#2-安装与启动)
3. [配置说明](#3-配置说明)
4. [代码架构总览](#4-代码架构总览)
5. [启动执行顺序与流程](#5-启动执行顺序与流程)
6. [Agent 调度与运行原理](#6-agent-调度与运行原理)
7. [工具系统（Tools）](#7-工具系统tools)
8. [MCP 协议集成](#8-mcp-协议集成)
9. [Skills 系统](#9-skills-系统)
10. [长期记忆系统（Memory）](#10-长期记忆系统memory)
11. [Daily 每日内容系统](#11-daily-每日内容系统)
12. [TUI 界面层](#12-tui-界面层)
13. [Plan Mode（计划模式）](#13-plan-mode计划模式)
14. [权限系统](#14-权限系统)
15. [会话管理](#15-会话管理)
16. [所有斜杠命令（Slash Commands）](#16-所有斜杠命令slash-commands)
17. [配置文件详解](#17-配置文件详解)
18. [目录结构](#18-目录结构)
19. [运行示例](#19-运行示例)

---

## 1. 环境要求

### Python 版本
- **Python 3.11+**（推荐 3.12）

### 依赖库

```
textual>=0.80.0     # TUI 框架
anthropic>=0.40.0   # Anthropic SDK（也作为 MiniMax 的兼容层）
rich>=13.0.0        # 富文本渲染
mcp>=1.0.0          # Model Context Protocol 客户端
PyYAML>=6.0         # Skills frontmatter 解析
openai              # OpenAI SDK（阿里云百炼 / OpenAI 兼容路由）
httpx               # HTTP 客户端（daily.py 超时控制）
```

安装方式：
```bash
pip install -r requirements.txt
# 或者
pip install textual anthropic rich mcp PyYAML openai httpx
```

### 操作系统
- **Linux / macOS**：完整支持
- **Windows**：完整支持（BashTool 自动使用 PowerShell/cmd，输出编码自动检测 UTF-8 / GBK）

---

## 2. 安装与启动

WXJ 提供三种安装方式，推荐使用 **方式 B**（pip 全局安装）以便直接通过 `wxj` 命令调用。

---

### 方式 A — 直接运行（无需安装，临时使用）

```bash
# 克隆项目
git clone https://github.com/wangxuejian/wxj-tui-agent.git
cd wxj-tui-agent

# 安装依赖
pip install -r requirements.txt

# 启动
python main.py
```

---

### 方式 B — pip 正式安装（推荐，注册全局 `wxj` 命令）

```bash
# 克隆项目
git clone https://github.com/wangxuejian/wxj-tui-agent.git
cd wxj-tui-agent

# 正式安装（打包后安装，适合生产使用）
pip install .

# 安装完成后即可全局调用
wxj
wxj --version
wxj --setup
```

---

### 方式 C — pip 开发模式安装（推荐开发者使用）

开发模式下修改代码后**无需重新安装**，改动立即生效。

```bash
# 克隆项目
git clone https://github.com/wangxuejian/wxj-tui-agent.git
cd wxj-tui-agent

# 开发模式安装（editable install）
pip install -e .

# 同样注册全局 wxj 命令
wxj
wxj --version
```

---

### 将 wxj 命令加入系统 PATH

pip 安装后，`wxj` 可执行文件会放在 pip 的 `Scripts`（Windows）或 `bin`（Linux/macOS）目录。
若终端提示「找不到 wxj 命令」，按以下步骤添加 PATH：

**Windows（PowerShell，永久生效）**

```powershell
# 查看 pip Scripts 目录位置
pip show wxj-tui | Select-String Location
# 输出示例：Location: D:\anaconda\envs\llm\Lib\site-packages
# Scripts 目录在同级：D:\anaconda\envs\llm\Scripts

# 将 Scripts 目录永久写入用户 PATH
$old = [Environment]::GetEnvironmentVariable('PATH','User')
[Environment]::SetEnvironmentVariable('PATH', "$old;D:\anaconda\envs\llm\Scripts", 'User')

# 重新打开终端后验证
wxj --version
```

**Linux / macOS（永久生效）**

```bash
# 查看安装位置
pip show wxj-tui | grep Location
# 一般在 ~/.local/lib/python3.x/site-packages
# 对应的 bin 目录：~/.local/bin

# 写入 ~/.bashrc 或 ~/.zshrc
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc

# 验证
wxj --version
```

**Anaconda 虚拟环境（任意平台）**

```bash
# 激活环境后安装，wxj 命令自动在该环境可用
conda activate llm
pip install -e /path/to/wxj-tui-agent
wxj --version

# Windows 下可直接用绝对路径调用，无需激活环境
D:\anaconda\envs\llm\Scripts\wxj.exe --version
```

---

### 启动参数速查

```bash
# 交互式 TUI 模式（推荐）
wxj

# 首次运行，直接打开设置界面
wxj --setup

# 指定工作目录启动
wxj --cwd /path/to/project

# 覆盖模型
wxj --model qwen-plus

# 无 TUI 的 Headless 模式（单次问答，输出到 stdout）
wxj -p "帮我解释这段代码"
echo "优化这个函数" | wxj -p

# 查看版本
wxj --version

# （备用）直接用 python 启动
python main.py
```

---

## 3. 配置说明

### 首次运行
启动后按 **Ctrl+S** 或输入 `/setup` 打开配置界面。设置弹窗分三个标签页。

#### 🤖 Tab 1 — Model & API

| 字段 | 说明 |
|------|------|
| Provider | `anthropic` / `aliyun` / `minimax` / `openai` |
| API Key | 对应 Provider 的 API 密鑰 |
| Base URL | API 端点（选择 Provider 后自动填入默认值） |
| Model | 模型名称（如 `claude-3-5-sonnet-20241022` / `qwen-plus`） |
| Max Tokens | 单次最大生成 token 数（默认 8192） |
| Enable Thinking | 是否开启 CoT 思考（支持 Anthropic claude-3-7+ / Aliyun qwen3 / MiniMax） |
| Thinking Budget | 思考 token 预算（默认 1024） |
| Enable Web Search | 联网搜索开关（仅阿里云 Qwen 支持，默认关闭） |
| Temperature | 采样温度（-1 = 不设置，使用 Provider 默认） |
| Top P | Top-P 采样参数（-1 = 不设置） |

#### 🔌 Tab 2 — MCP Servers

在此页签可以可视化地管理所有 MCP 工具服务器：

| 功能 | 说明 |
|------|------|
| **服务器列表** | 显示已配置的所有服务器：名称、类型、命令/URL、连接状态 |
| **状态标识** | ✓ ok = 已连接，✗ failed = 连接失败，- = 未测试/跳过 |
| **🔄 Auto: ON / ⏸ Auto: OFF** | 切换该服务器是否在启动时自动连接（点击即时切换，保存后生效）|
| **⚡ Connect** | 立即连接该服务器（当前会话生效）|
| **⏏ Disconnect** | 立即断开该服务器（当前会话生效）|
| **🗑 Delete** | 标记删除该服务器（保存后从配置文件移除）|
| **➕ Add Server** | 填写表单后直接添加，不测试连接 |
| **🔌 Test Connection** | 尝试连接，成功后自动添加并显示工具数 |

**表单字段：**
- `Name`：服务器唯一标识（工具名前缀）
- `Type`：`stdio` / `sse` / `http` / `ws`
- `stdio` 类型：填 Command（如 `python`）+ Args（如 `server.py`）
- `sse/http/ws` 类型：填 URL + 可选 Headers JSON
- `Auto-connect on startup`：开关，控制该服务器是否在启动时自动连接（默认开启）

**保存后：**
- 新增且 autoconnect=ON 的服务器会自动尝试连接，✓ / ✗ 显示结果
- 新增且 autoconnect=OFF 的服务器会添加到配置但**不**自动连接
- 已有服务器从 ON 改为 OFF → 立即断开；从 OFF 改为 ON → 立即连接
- 删除的服务器会自动断开，并从 config.json 中移除
- 下次启动时，`autoconnect: true` 的服务器自动连接，`false` 的跳过

#### 💡 Tab 3 — Context

配置历史消息压缩阈值：
- **Summarize after (turns)**：对话轮数超过此值时，后台异步触发摘要压缩（默认 10 轮）
- **Hard limit**：消息总数超过此值时，在摘要后强制截断历史上下文（默认 20 条）

> **提示**：这两个值也可以在状态栏直接点击 `ctx:10/20` 标签快速切换预设（5/10、10/20、15/30、20/40）。

### 多 Profile 管理
SetupDialog 支持保存/切换多个命名 Profile，方便在不同 Provider 之间切换。

### 环境变量（优先级高于配置文件）
```bash
export ANTHROPIC_API_KEY="sk-ant-..."
export ANTHROPIC_BASE_URL="https://api.anthropic.com"
export ANTHROPIC_MODEL="claude-3-5-sonnet-20241022"
export ANTHROPIC_AUTH_TOKEN="..."  # bearer token 模式
```

### 配置文件位置
```
~/.config/wxj-agent/config.json
~/.config/wxj-agent/memory/          # 长期记忆文件
~/.config/wxj-agent/skills/          # 用户自定义 Skills
~/.config/wxj-agent/sessions/        # 会话历史文件
```

---

## 4. 代码架构总览

```
python-tui-agent/
├── main.py                   # 入口点：参数解析、启动 TUI 或 Headless
│
├── agent/                    # 核心 Agent 逻辑层
│   ├── config.py             # 配置管理（AgentConfig, ModelProfile, load/save）
│   ├── messages.py           # 消息类型定义（UserMessage, AssistantMessage, TodoItem 等）
│   ├── query_engine.py       # Agent 核心：LLM 调用 + 工具调用循环（Anthropic + OpenAI 双路径）
│   ├── memory.py             # 长期记忆系统（会话摘要 / 习惯 / 个人档案）
│   ├── skills.py             # Skills 加载器（Markdown YAML frontmatter 解析）
│   ├── mcp_client.py         # MCP 协议客户端（stdio / SSE / HTTP / WebSocket）
│   ├── daily.py              # 每日内容生成（新闻、问候语、主题词）
│   └── tools/                # 内置工具集
│       ├── __init__.py       # DEFAULT_TOOLS 注册表
│       ├── base.py           # Tool 抽象基类、PermissionResult、ConfirmFn
│       ├── bash_tool.py      # BashTool：执行 shell 命令
│       ├── file_read_tool.py # FileRead：读取文件
│       ├── file_write_tool.py# FileWrite：写入文件
│       ├── file_edit_tool.py # FileEdit：局部编辑文件（str_replace）
│       ├── glob_tool.py      # Glob：文件 glob 搜索
│       └── grep_tool.py      # Grep：正则内容搜索
│
└── tui/                      # Textual TUI 层
    ├── app.py                # AgentApp 主应用（布局 + 命令路由 + 查询调度）
    ├── views.py              # 消息视图（UserBubble, AssistantBubble, ToolCallCard, PermissionCard）
    ├── input_bar.py          # 输入栏（多行输入 + Tab 补全 + 历史记录）
    ├── dialogs.py            # 弹窗（SetupDialog, HelpDialog, DirectoryDialog）
    ├── logo_panel.py         # 顶部 Logo / 新闻 / 问候语面板
    └── plan_mode.py          # Plan Mode 侧边栏（PlanTool + PlanPanel）
```

### 层次关系图

```
┌─────────────────────────────────────────────────────┐
│                    main.py                          │
│  parse_args → run_tui() / run_headless()            │
└────────────────────────┬────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────┐
│               tui/app.py  AgentApp                  │
│  ┌──────────────────────────────────────────────┐   │
│  │  LogoPanel (logo_panel.py)                  │   │
│  ├──────────────────────────────────────────────┤   │
│  │  MessageList (views.py)  │  PlanPanel        │   │
│  ├──────────────────────────────────────────────┤   │
│  │  InputBar (input_bar.py)                    │   │
│  └──────────────────────────────────────────────┘   │
│                         │                           │
│   on_input_submitted → _run_query()                 │
└────────────────────────┬────────────────────────────┘
                         │ run_worker (async)
┌────────────────────────▼────────────────────────────┐
│            agent/query_engine.py  QueryEngine       │
│                                                     │
│  stream_query()                                     │
│    ├── _stream_query_anthropic()  (native SDK)      │
│    └── _stream_query_openai()     (openai SDK)      │
│                         │                           │
│     agentic loop: LLM → tools → LLM → ...          │
└────────────────────────┬────────────────────────────┘
                         │
        ┌────────────────┴─────────────────┐
        ▼                                  ▼
  agent/tools/                    agent/mcp_client.py
  BashTool, FileRead...            MCPTool (remote)
```

---

## 5. 启动执行顺序与流程

### TUI 模式完整启动序列

```
python main.py
    │
    ├─1─ parse_args()               解析 CLI 参数
    │
    ├─2─ load_config()              读取 ~/.config/wxj-agent/config.json
    │      ├── 文件不存在 → 使用默认值
    │      ├── 存在 active_profile → apply_profile() 应用存档配置
    │      └── 检查环境变量 ANTHROPIC_* 覆盖
    │
    ├─3─ os.chdir(cfg.cwd)          切换到配置的工作目录
    │
    ├─4─ AgentApp(config=cfg)        构造主应用
    │      ├── MCPManager()          初始化 MCP 管理器
    │      ├── SkillLoader()         初始化 Skills 加载器
    │      ├── _build_engine()       构造 QueryEngine
    │      │     └── MemoryManager() 初始化长期记忆
    │      └── PlanTool()            构造 Plan Mode 工具
    │
    ├─5─ app.run()                   启动 Textual 事件循环
    │
    ├─6─ AgentApp.on_mount()        首次挂载回调
    │      ├── _update_status()      更新状态栏
    │      ├── _show_welcome() / _show_ready()  显示欢迎信息
    │      ├── _check_daily_staleness()  检查 daily.md 是否过期
    │      └── _connect_mcp_servers()  自动连接配置的 MCP 服务器
    │
    └─7─ 进入交互循环，等待用户输入
```

### 用户输入处理流程

```
用户按 Enter
    │
    ├── InputBar._ChatTextArea._on_key("enter")
    │      └── post_message(SubmitRequest())
    │
    ├── InputBar.on_chat_text_area_submit_request()
    │      ├── 获取输入文本
    │      ├── 保存到历史记录
    │      └── post_message(InputSubmitted(text))
    │
    └── AgentApp.on_input_submitted(event)
           ├── hasattr(event, 'text') 防御检查
           ├── text.startswith('/') → _handle_slash_command()
           └── 普通文本 → _run_query(text)
```

---

## 6. Agent 调度与运行原理

### 核心：Agentic Loop（代理循环）

`QueryEngine.stream_query()` 实现了经典的「LLM 调用 → 工具执行 → 结果返回 → 再次调用」的循环，轮次上限规则如下：

| 权限模式 | 第 1-30 轮 | 第 30 轮触发 | 第 31-100 轮 | 超过 100 轮 |
|---------|-----------|------------|-------------|------------|
| `ask_always` / `allow_safe` / `deny_all` | 正常运行 | 硬终止 | 不可用 | 不可用 |
| `allow_all` | 正常运行 | 弹出内联确认卡，用户选择是否继续 | 用户确认后继续 | 强制终止 |

```
stream_query(messages, system_prompt, callbacks...)
    │
    ├─1─ _compress_messages()      上下文超限时自动压缩（安全裁剪不破坏 tool_use/result 配对）
    │
    ├─2─ 路由判断
    │      ├── provider in ("aliyun","openai") → _stream_query_openai()
    │      └── otherwise                       → _stream_query_anthropic()
    │
    └─3─ agentic loop（普通模式最多 30 轮，allow_all 模式最多 100 轮）
           │
           ├─ [第 30 轮时，若 allow_all 模式]
           │    弹出内联确认卡（IterationLimit），等待用户点击
           │    Allow Once/All → 继续到 100 轮
           │    Deny → 立即终止
           │
           ├─ on_turn_start()        通知 UI 新的 LLM 轮次开始
           │
           ├─ 发起流式 LLM 请求
           │      逐 chunk 处理：
           │        text_delta  → on_text(chunk)           实时流入 AssistantBubble
           │        tool_use    → 积累 JSON input buffer
           │        stop        → 解析完整 ToolUseBlock
           │
           ├─ on_turn_end(has_tools) 通知 UI 本轮结束，触发 Markdown 渲染
           │
           ├─ 无工具调用 or stop_reason=="end_turn" → break，结束循环
           │
           └─ 有工具调用 → 逐个执行工具
                  │
                  ├─ _make_confirm_fn()  包装权限检查
                  │      ├── auto_approved set 中 → 直接允许
                  │      └── 否则 → 调用 confirm_fn（弹 PermissionCard）
                  │
                  ├─ tool.execute(input, confirm_fn)  执行工具
                  │
                  ├─ on_tool_result(id, result, is_error)  更新 ToolCallCard
                  │
                  └─ 组装 UserMessage(tool_results) → 追加到 messages，进入下一轮
```

### Anthropic 原生路径 vs OpenAI 兼容路径

| 方面 | Anthropic（anthropic SDK） | OpenAI-compatible（openai SDK） |
|------|---------------------------|--------------------------------|
| Provider | `anthropic`, `minimax` | `aliyun`, `openai` |
| 消息格式 | `messages` API（content blocks） | `chat.completions` API（tool_calls） |
| 工具格式 | `input_schema` | OpenAI `function.parameters` |
| 工具结果 | `tool_result` content block in user msg | `role: "tool"` 独立消息 |
| 思考参数 | `thinking={type,budget_tokens}` 顶层 | `extra_body.enable_thinking` |
| 联网搜索 | 不支持 | `extra_body.enable_search`（仅 aliyun） |

### 上下文压缩机制

当消息数超过 `max_context_messages`（默认 40）时：
1. `_compress_messages()` 调用 `_find_safe_trim_point()` 找到安全裁切点（不破坏 tool_use/result 配对）
2. 保留头部第一条消息（锚点）+ 尾部最近 N 条
3. 被裁剪的消息异步发送给 LLM 进行摘要，追加到 `conversation_summary.md`
4. 状态栏更新上下文统计

### 工作目录注入

每次调用 `_run_query_async()` 时，当前工作目录 `self._cwd` 会被格式化注入系统提示词：

```python
base_prompt = _SYSTEM_PROMPT.format(cwd=self._cwd)
```

工具执行（BashTool 等）默认在此目录下运行。

---

## 7. 工具系统（Tools）

### 工具基类

所有工具继承 `agent/tools/base.py` 中的 `Tool` 抽象类：

```python
class Tool(ABC):
    name: str                    # 工具名称（LLM 调用时使用）
    description: str             # 工具描述（注入 LLM 系统提示）
    input_schema: dict           # JSON Schema（LLM 生成参数时遵循）
    requires_permission: bool    # 是否需要用户确认

    @abstractmethod
    async def execute(self, tool_input: dict, confirm_fn) -> str:
        ...

    def to_api_format(self) -> dict:
        # 返回 Anthropic API 工具定义格式
        ...
```

### 内置工具一览

| 工具名 | 文件 | 功能 | 需要权限 |
|--------|------|------|---------|
| `Bash` | bash_tool.py | 执行 shell 命令（120s 超时，ANSI 剥离，Windows GBK 兼容） | 是 |
| `Read` | file_read_tool.py | 读取文件内容（支持行范围 start_line/end_line） | 否 |
| `Write` | file_write_tool.py | 写入/覆盖文件（自动创建父目录） | 是 |
| `Edit` | file_edit_tool.py | 局部编辑（str_replace，支持多处替换） | 是 |
| `Glob` | glob_tool.py | 文件 glob 搜索（支持递归，返回路径列表） | 否 |
| `Grep` | grep_tool.py | 正则内容搜索（返回文件名 + 行号 + 匹配行） | 否 |

另外还有 2 个虚拟工具（非 file 工具，由其他模块注册）：
- `TodoWrite`（plan_mode.py）：AI 管理 Plan Mode 任务列表
- MCP 工具：动态注册，命名格式 `{server_name}__{tool_name}`

### 工具注册流程

```python
# agent/tools/__init__.py
DEFAULT_TOOLS: list[Tool] = [
    BashTool(), FileReadTool(), FileWriteTool(),
    FileEditTool(), GlobTool(), GrepTool(),
]

# QueryEngine.__init__
self.tools = list(DEFAULT_TOOLS) + extra_tools + mcp_tools
self._tool_map = {t.name: t for t in self.tools}
```

`extra_tools` 在 `AgentApp._build_engine()` 中传入 `[self._plan_tool]`。

### 自定义工具

继承 `Tool` 并实现 `execute()`，然后在创建 `QueryEngine` 时通过 `extra_tools` 参数注入即可。

---

## 8. MCP 协议集成

[Model Context Protocol (MCP)](https://modelcontextprotocol.io/) 允许通过标准协议连接外部工具服务器，一个 WXJ 实例可以**同时连接多个 MCP 服务器**，所有服务器的工具会一起注册到 Agent 的工具集中。

### 支持的传输协议

| 类型 | 说明 | 适用场景 |
|------|------|--------|
| `stdio` | 本地子进程（标准输入输出） | 本地脚本、npx 包，最常用 |
| `sse` | HTTP Server-Sent Events | 远程或本地 HTTP 服务 |
| `http` | Streamable HTTP（MCP 1.x） | MCP 1.x 规范服务 |
| `ws` | WebSocket | 双向实时通信场景 |

### 多服务器配置（config.json）

在 `/setup` 的 MCP Servers 区域或直接编辑 `~/.config/wxj-agent/config.json`，可以同时配置多个服务器：

```json
{
  "mcp_servers": {
    "filesystem": {
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
      "autoconnect": true
    },
    "test": {
      "type": "stdio",
      "command": "python",
      "args": ["test_mcp_server.py"],
      "autoconnect": true
    },
    "remote-api": {
      "type": "sse",
      "url": "http://localhost:8765/sse",
      "headers": {"Authorization": "Bearer mytoken"},
      "autoconnect": false
    }
  }
}
```

> **`autoconnect` 字段**（默认 `true`）：
> - `true`：启动时自动连接该服务器
> - `false`：加载配置但跳过自动连接，需要时可在 `/setup` 中点击 **⚡ Connect** 手动连接
> - 旧配置无此字段时默认视为 `true`，向下兼容

启动时所有 `autoconnect: true` 的服务器会**自动连接**，工具统一注册进 Agent。

### 运行时命令详解

| 命令 | 说明 |
|------|------|
| `/mcp list` | 列出所有已连接的服务器和工具总数 |
| `/mcp tools` | 列出**所有服务器**的全部工具（名称 + 描述 + 参数）|
| `/mcp tools <server>` | 只列出指定服务器的工具 |
| `/mcp connect <name> <json>` | 运行时连接新服务器 |
| `/mcp disconnect <name>` | 断开指定服务器 |
| `/mcp reconnect` | 重新连接**所有**服务器（网络恢复后使用）|
| `/mcp reconnect <name>` | 重新连接指定服务器 |

#### `/mcp list` 输出示例

```
Connected MCP servers (use '/mcp tools' to list all tools):
  test      ✓ connected   4 tool(s)
  filesystem ✓ connected  6 tool(s)

  Total: 2 server(s), 10 tool(s) available
```

#### `/mcp tools test` 输出示例

```
test — 4 tool(s):
  test__get_time (params: format)
    Return the current date and time.
  test__calculator (params: operation, a, b)
    Perform basic arithmetic: add, subtract, multiply, divide, power, sqrt.
  test__list_directory (params: path, show_hidden)
    List files and directories at a given path.
  test__echo (params: message)
    Echo back the provided message. Useful for testing connectivity.
```

**加粗参数**表示必填，普通字体表示可选。

### 运行时连接示例

```bash
# stdio 方式（本地 Python 服务器）
/mcp connect test {"type":"stdio","command":"D:\\anaconda\\python.exe","args":["test_mcp_server.py"]}

# SSE 方式（先启动服务：python test_mcp_server.py --sse）
/mcp connect test {"type":"sse","url":"http://localhost:8765/sse"}

# npx 方式（自动下载 MCP 官方服务器）
/mcp connect fs {"type":"stdio","command":"npx","args":["-y","@modelcontextprotocol/server-filesystem","/tmp"]}

# 连接成功后自动提示：
# MCP server test connected. 4 tool(s) available.
# Use '/mcp tools test' to see tool details.
```

### 内置测试服务器

项目自带 `test_mcp_server.py`，提供 4 个测试工具，支持 **stdio、SSE、WebSocket** 三种模式：

| 工具 | 功能 |
|------|------|
| `test__get_time` | 获取当前时间（可自定义格式）|
| `test__calculator` | 四则运算 / 幂 / 开方 |
| `test__list_directory` | 列出目录文件 |
| `test__echo` | 回显消息（测试连通性）|

```bash
# stdio 模式：TUI 会自动作为子进程启动，无需手动运行
# SSE 模式：先在另一个终端启动服务
python test_mcp_server.py --sse --port 8765
# WebSocket 模式：先在另一个终端启动服务
python test_mcp_server.py --ws --port 8766
```

对应连接方式：

```bash
# stdio
/mcp connect test {"type":"stdio","command":"python","args":["test_mcp_server.py"]}
# SSE
/mcp connect test {"type":"sse","url":"http://localhost:8765/sse"}
# WebSocket
/mcp connect test {"type":"ws","url":"ws://localhost:8766/ws"}
```

### 工具命名规则

MCP 工具在 Agent 中的名称格式为：**`{server_name}__{tool_name}`**

- `filesystem` 服务器的 `read_file` → `filesystem__read_file`
- `test` 服务器的 `calculator` → `test__calculator`

LLM 调用工具时直接使用这个全名，用户在对话中无需关注，直接描述需求即可。

### 多服务器并发工作示例

```
用户: 用 test 的 calculator 算 99*99，同时用 filesystem 列出 /tmp 目录

→ Agent 同一轮调用两个工具：
  test__calculator(operation=multiply, a=99, b=99)  → 9801
  filesystem__list_directory(path=/tmp)             → [文件列表]
```

---

## 9. Skills 系统

Skills 是存放在 `~/.config/wxj-agent/skills/` 目录下的 `.md` 文件，每个文件定义一个可供用户调用的专用提示词模板。

### Skill 文件格式

```markdown
---
name: code-review
description: "专业代码审查，覆盖安全、性能、可读性"
when_to_use: "当用户需要对代码进行全面审查时"
allowed_tools: [Read, Grep, Glob]
argument_hint: "<file-or-directory>"
---

# Code Review Skill

你是一位资深软件工程师，请对提供的代码进行全面审查：

1. **安全性**：检查 SQL 注入、XSS、权限漏洞等
2. **性能**：识别 N+1 查询、内存泄漏、不必要的计算
3. **可读性**：命名规范、注释质量、代码结构
4. **最佳实践**：SOLID 原则、错误处理

请给出具体的问题描述和改进建议。
```

### YAML Frontmatter 字段

| 字段 | 必填 | 说明 |
|------|------|------|
| `name` | 是 | Skill 标识名（`/skill name` 中使用的名称） |
| `description` | 否 | 简短描述（显示在 `/skill` 列表中） |
| `when_to_use` | 否 | 使用时机提示 |
| `allowed_tools` | 否 | 推荐使用的工具列表 |
| `argument_hint` | 否 | 参数提示（显示在帮助中） |

### 调用方式

```
/skill                             # 列出所有可用 Skills
/skill code-review src/main.py     # 执行指定 Skill，参数作为 prompt
```

Skill 的 Markdown body 会作为系统提示词前缀，与默认系统提示词合并后一起发送给 LLM。

---

## 10. 长期记忆系统（Memory）

`MemoryManager`（`agent/memory.py`）管理三个持久化的 Markdown 文件：

### 记忆文件

| 文件 | 路径 | 更新策略 | 内容 |
|------|------|---------|------|
| `conversation_summary.md` | `~/.config/wxj-agent/memory/` | 滚动合并式（每次压缩时新摘要 + 旧摘要合并精简，最终全量覆写） | 历史对话的 LLM 摘要要点（始终保持精简，不会无限增长） |
| `user_habits.md` | 同上 | 合并式（最多 20 条 bullet） | 用户编码习惯、工具偏好、工作流特征 |
| `user_info.md` | 同上 | 稳定式（闭环更新，只在有强证据时才修改） | 用户个人档案（语言偏好、技术栈、沟通风格） |

### 注入机制

每次调用 LLM 之前，`_build_system_prompt()` 调用 `MemoryManager.build_memory_section()` 将三个文件的内容拼接为：

```
## Long-term Memory
## Past Conversation Summary
...
## User Behavioral Habits
...
## User Personal Profile
...
```

注入到系统提示词末尾，让 LLM 了解用户背景。

### 异步更新

每次对话结束后，`AgentApp` 异步触发：
```python
self.run_worker(self._update_memory_async(updated), thread=False, exclusive=False)
```
后台调用 LLM 更新 `user_habits.md` 和 `user_info.md`，不阻塞主界面。

### 上下文压缩时的摘要

当消息超过 `max_context_messages` 时，被裁剪的旧消息通过 `compress_and_summarize()` 发送给 LLM 生成摘要，追加到 `conversation_summary.md`。

---

## 11. Daily 每日内容系统

`agent/daily.py` 负责生成每日新闻、问候语和主题词，内容显示在顶部 Logo 面板的左侧。

### 文件位置

`~/.config/wxj-agent/memory/daily.md`

### 格式规范

```markdown
## Date: 2025-04-04
## Greeting: Happy Friday! Ship something awesome before the weekend.
## Themes: spring, creativity, technology, innovation, code
## News:
- 苹果发布 M4 Ultra 芯片
- GPT-4o 更新内存功能
- Rust 2024 Edition 发布
...
## Context:
A spring Friday full of possibilities. The open-source community is thriving today.
```

### 加载策略

| 时机 | 行为 |
|------|------|
| 启动时 | `load_daily()` 检查 daily.md 日期是否为今天；是则使用缓存，否则不调用 LLM（显示内置 fallback） |
| `/newdaily` | `force_update()` 强制调用 LLM，联网搜索 15-20 条今日新闻 |
| LLM 失败 | 写入内置 fallback 内容，不影响其他功能 |

### /newdaily 执行流程

```
/newdaily
    ├── 互斥检查（_newdaily_running）
    ├── 设置 Logo 面板状态为 BUSY（黄色）
    ├── asyncio.wait_for(force_update(config), timeout=600)
    │      └── _generate_daily()
    │             ├── aliyun/openai → OpenAI SDK + enable_search=True
    │             └── anthropic/minimax → Anthropic SDK
    ├── 成功 → 状态 OK（绿色），刷新 NewsPanel
    ├── 超时（>10分钟）→ 状态 STALE，提示使用更快的模型
    └── 异常（含 CancelledError）→ 捕获 BaseException，释放互斥锁
```

> **注意**：联网搜索 15-20 条新闻在阿里云 Qwen 上约需 2-5 分钟，请耐心等待或在 `/setup` 中切换 `qwen-turbo` / `qwen-flash`。

---

## 12. TUI 界面层

### 布局结构

```
┌─────────────────────────────────────────────────────────┐
│ Header (时钟)                                           │
├─────────────────────────────────────────────────────────┤
│ LogoPanel                                               │
│ [NewsPanel (1fr)] [GreetingArea (1fr)] [LogoArea (2fr)] │
├──────────────────────────────────┬──────────────────────┤
│                                  │                      │
│  MessageList                     │  PlanPanel (35列)    │
│  (可滚动消息列表)                 │  (Plan Mode 隐藏)    │
│                                  │                      │
├──────────────────────────────────┴──────────────────────┤
│ InputBar                                                │
│ [> 多行文本输入区]                                       │
│ Enter: send  Shift+Enter: newline  Tab: complete  ↑↓    │
├─────────────────────────────────────────────────────────┤
│ StatusBar                                               │
│ [model] [mcp] [cwd]   [context] [perm-mode] [session]  │
└─────────────────────────────────────────────────────────┘
```

### 键盘快捷键

| 快捷键 | 功能 |
|--------|------|
| `Ctrl+Q` | 退出 |
| `Ctrl+S` | 打开设置（SetupDialog） |
| `F1` 或 `Ctrl+\` | 打开帮助（HelpDialog） |
| `F3` 或 `Ctrl+K` | 切换 Plan Mode 面板 |
| `Ctrl+L` | 清空对话历史 |
| `Ctrl+C`（输入栏内） | 中断当前请求（abort） |
| `Enter` | 提交输入 |
| `Shift+Enter` | 在输入框内换行 |
| `Tab` | 触发斜杠命令补全 / 路径补全 |
| `↑ / ↓` | 在命令历史中导航（或在补全列表中上下选择） |

> **为什么不用 Ctrl+P / Ctrl+H？**
> `Ctrl+P` 会被大多数 IDE（VS Code、PyCharm）和部分终端拦截成命令面板。
> `Ctrl+H` 在很多终端中等价于 Backspace（ASCII 0x08），无法传入应用。

### 状态栏可点击标签

状态栏底部有多个可点击标签，无需进入 `/setup` 即可快速切换：

| 标签 | 点击效果 |
|------|--------|
| `⚙ Ask` / `✔ Safe` / `✔✔ All` / `✗ None` | 循环切换权限模式（ask_always → allow_safe → allow_all → deny_all） |
| `📝 Plan:Auto` / `★ Plan:Priority` / `⚡ Plan:Direct` | 循环切换 Plan Mode 行为（auto → priority → direct） |
| `ctx:10/20` | 循环切换压缩阈值预设（5/10 → 10/20 → 15/30 → 20/40） |

### 消息渲染

| 消息类型 | 组件 | 说明 |
|---------|------|------|
| 用户消息 | `UserBubble` | 蓝色左边框，显示"You" |
| AI 回复 | `AssistantBubble` | 绿色左边框，流式追加文本，完成后渲染 Markdown |
| 工具调用 | `ToolCallCard` | 可折叠卡片，显示工具名/参数/结果，支持 Ctrl+C 复制 |
| 权限确认 | `PermissionCard` | 内联确认卡，三个按钮：Allow Once / Allow All / Deny |
| 系统消息 | `Static` | 彩色状态提示（dim/yellow/red/green） |
| 思考中 | `ThinkingIndicator` | 动画 loading 指示器 |

### InputBar 特性

- **多行输入**：TextArea 实现，Shift+Enter 换行
- **Tab 补全**：
  - 输入 `/` 开头时：显示斜杠命令补全列表
  - 输入 `/cd ` 后：显示文件系统路径补全
- **历史记录**：最多 200 条，`↑/↓` 在第一/最后行时切换历史
- **补全列表导航**：补全列表打开时，`↑/↓` 优先导航补全项而非历史

### DirectoryDialog

`/cd`（无参数）弹出目录选择弹窗：
- 左侧目录树（DirectoryTree）
- 顶部路径输入框（Enter 跳转任意路径）
- Tab 补全路径
- `↑ Parent` 按钮：上级目录
- **Windows 盘符导航**：退到盘根时显示 C: / D: / E: 等盘符列表

---

## 13. Plan Mode（计划模式）

### 概念

Plan Mode 是一个右侧侧边栏，显示 AI 管理的任务列表（Todo List）。AI 可通过调用 `TodoWrite` 工具来创建和更新任务。

### 启用方式

```
/plan     # 切换显示/隐藏
Ctrl+K    # 同上
```

### Plan Mode 三档模式

可通过状态栏点击 Plan 标签循环切换，也可在配置文件中设置 `todo_mode` 字段：

| 模式 | 状态栏标签 | config.json 字段 | 行为 |
|------|---------|--------------|------|
| **Auto**（默认） | `📝 Plan:Auto` | `"todo_mode": "auto"` | AI 自即判断何时需要建任务列表，多步骤任务自动使用 |
| **Priority** | `★ Plan:Priority` | `"todo_mode": "priority"` | AI 被强烈鼓励对**每一个**多步骤任务应用 TodoWrite 先建计划，适合复杂项目完全可视化 |
| **Direct** | `⚡ Plan:Direct` | `"todo_mode": "direct"` | AI 专注于快速简洁回复和单次工具调用，遇到复杂任务会建议切换模式 |

> 点击状态栏的 Plan 标签可循环切换三档，并在聊天记录中显示当前模式的详细说明。

### TodoWrite 工具参数

```json
{
  "todos": [
    {"id": "t1", "content": "分析需求文档", "status": "COMPLETE"},
    {"id": "t2", "content": "编写核心逻辑", "status": "IN_PROGRESS"},
    {"id": "t3", "content": "添加单元测试", "status": "PENDING"}
  ],
  "merge": true
}
```

### 状态图标

| 状态 | 图标 | 颜色 |
|------|------|------|
| PENDING | ○ | dim |
| IN_PROGRESS | ◐ | yellow |
| COMPLETE | ● | green |
| CANCELLED | ✗ | red |

---

## 14. 权限系统

### 四种权限模式

| 模式 | 说明 | 适用场景 |
|------|------|---------|
| `ask_always` | 每次工具调用都弹确认（默认） | 日常使用，安全第一 |
| `allow_safe` | 只读工具自动通过，危险工具询问 | 信任 AI 的探索性工作 |
| `allow_all` | 全部自动通过（危险！） | 已知安全的自动化任务 |
| `deny_all` | 全部拒绝，AI 只能对话 | 纯问答场景 |

安全工具（`SAFE_TOOLS`）：`Read`, `Glob`, `Grep`, `WebSearch`, `TodoRead`

### 切换方式

- 点击状态栏右侧的 `⚙ Ask` 标签循环切换
- 或在 `/setup` 的 Security 区域选择

### PermissionCard 交互

当工具需要权限时，在消息列表中内联显示确认卡片：

- **Allow Once [Y]**：本次允许
- **Allow All [A]**：本工具永久允许（本次会话）
- **Deny [N]**：拒绝

---

## 15. 会话管理

### 自动保存

每次对话完成后，`_save_session()` 将消息历史保存至：
```
~/.config/wxj-agent/sessions/session_YYYYMMDD_HHMMSS.json
```

### /stop 与 /resume

```
/stop     # 保存断点快照（当前消息列表 + 原始查询），终止当前流式响应
/resume   # 从断点恢复，继续执行
```

### /abort

```
/abort    # 立即中断当前 LLM 流（QueryEngine._abort = True）
Ctrl+C    # 同上（在输入栏内）
```

### /history

显示当前会话所有消息的简短摘要（role + 前 80 字符）。

---

## 16. 所有斜杠命令（Slash Commands）

| 命令 | 参数 | 说明 |
|------|------|------|
| `/help` | — | 显示帮助弹窗 |
| `/setup` | — | 打开设置弹窗（API Key、模型、MCP、Skills 等） |
| `/clear` | — | 清空聊天记录（不清除文件记忆） |
| `/cd` | `[path]` | 切换工作目录；无参数时打开目录选择弹窗 |
| `/plan` | — | 切换 Plan Mode 侧边栏 |
| `/skill` | `[name] [args]` | 执行 Skill；无参数列出所有 Skills |
| `/mcp` | `list\|tools [server]\|connect\|disconnect\|reconnect [server]` | 管理 MCP 服务器 |
| `/newdaily` | — | 联网搜索生成今日新闻（约 2-5 分钟） |
| `/logo` | — | 循环切换 Logo 样式 |
| `/history` | — | 显示当前会话消息摘要 |
| `/stop` | — | 保存断点并中止当前请求 |
| `/resume` | — | 从上一个 `/stop` 断点恢复 |
| `/abort` | — | 立即中断当前 LLM 请求 |
| `/exit` | — | 退出程序 |

---

## 17. 配置文件详解

`~/.config/wxj-agent/config.json` 完整字段说明：

```json
{
  // ── 活跃配置（当前使用的 Provider 参数）──
  "api_key": "sk-...",
  "base_url": "https://api.anthropic.com",
  "model": "claude-3-5-sonnet-20241022",
  "auth_type": "x-api-key",       // "x-api-key" | "bearer"
  "max_tokens": 8192,
  "provider": "anthropic",         // "anthropic"|"aliyun"|"minimax"|"openai"

  // ── 思考模式 ──
  "enable_thinking": false,
  "thinking_budget": 1024,

  // ── 联网搜索（阿里云 Qwen only）──
  "enable_search": false,

  // ── 采样参数（-1 = 不设置，使用 Provider 默认）──
  "temperature": -1.0,
  "top_p": -1.0,

  // ── 全局设置 ──
  "theme": "dark",                 // "dark" | "light"
  "permission_mode": "ask_always", // "ask_always"|"allow_safe"|"allow_all"|"deny_all"
  "max_context_messages": 40,
  "cwd": "/home/user/projects",
  "skills_dir": "",                // 留空则使用 ~/.config/wxj-agent/skills/
  "auto_approve_tools": [],        // 永久自动批准的工具名列表

  // ── MCP 服务器 ──
  "mcp_servers": {
    "filesystem": {
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
      "env": {},
      "autoconnect": true   // true: 启动自动连接； false: 不自动连接（默认 true）
    }
  },

  // ── Plan Mode 行为 ──
  // "auto": AI 自判断（默认）； "priority": 强制计划； "direct": 快速回复
  "todo_mode": "auto",

  // ── 多 Profile 管理 ──
  "active_profile": "my-claude",   // 当前激活的 Profile 名称
  "profiles": {
    "my-claude": {
      "name": "my-claude",
      "provider": "anthropic",
      "api_key": "sk-ant-...",
      "base_url": "https://api.anthropic.com",
      "model": "claude-3-5-sonnet-20241022",
      "auth_type": "x-api-key",
      "max_tokens": 8192,
      "enable_thinking": false,
      "thinking_budget": 1024,
      "enable_search": false,
      "temperature": -1.0,
      "top_p": -1.0
    },
    "aliyun-qwen": {
      "name": "aliyun-qwen",
      "provider": "aliyun",
      "api_key": "sk-...",
      "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
      "model": "qwen-plus",
      "auth_type": "bearer",
      "max_tokens": 8192,
      "enable_thinking": false,
      "thinking_budget": 1024,
      "enable_search": false,
      "temperature": -1.0,
      "top_p": -1.0
    }
  }
}
```

### Provider 内置默认值

| Provider | Base URL | Auth Type | 推荐模型 |
|----------|----------|-----------|---------|
| `anthropic` | `https://api.anthropic.com` | `x-api-key` | `claude-3-5-sonnet-20241022` |
| `aliyun` | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `bearer` | `qwen-plus` |
| `minimax` | `https://api.minimaxi.chat/v1` | `bearer` | `MiniMax-M2.7` |
| `openai` | `https://api.openai.com/v1` | `bearer` | `gpt-4o` |

---

## 18. 目录结构

```
python-tui-agent/
│
├── main.py                        # 入口：CLI 解析，TUI/Headless 模式启动
├── requirements.txt               # 依赖列表
│
├── agent/                         # Agent 核心层
│   ├── __init__.py
│   ├── config.py                  # AgentConfig, ModelProfile, load_config, save_config
│   ├── messages.py                # UserMessage, AssistantMessage, ToolUseBlock, TodoItem 等
│   ├── query_engine.py            # QueryEngine: agentic loop, 上下文压缩, 双 SDK 路由
│   ├── memory.py                  # MemoryManager: conversation_summary / habits / info
│   ├── skills.py                  # SkillLoader: 扫描并解析 skills/*.md
│   ├── mcp_client.py              # MCPManager, MCPClient, MCPTool
│   ├── daily.py                   # DailyManager: load_daily, force_update, parse_*
│   └── tools/
│       ├── __init__.py            # DEFAULT_TOOLS 列表导出
│       ├── base.py                # Tool ABC, PermissionResult, ConfirmFn
│       ├── bash_tool.py           # BashTool (subprocess, 120s, ANSI strip)
│       ├── file_read_tool.py      # FileReadTool
│       ├── file_write_tool.py     # FileWriteTool
│       ├── file_edit_tool.py      # FileEditTool (str_replace)
│       ├── glob_tool.py           # GlobTool
│       └── grep_tool.py           # GrepTool
│
└── tui/                           # Textual UI 层
    ├── __init__.py
    ├── app.py                     # AgentApp: 布局, 命令路由, 查询调度, 权限处理
    ├── views.py                   # UserBubble, AssistantBubble, ToolCallCard, PermissionCard, MessageList
    ├── input_bar.py               # InputBar, _ChatTextArea, CompletionList, InputSubmitted
    ├── dialogs.py                 # SetupDialog, HelpDialog, DirectoryDialog
    ├── logo_panel.py              # LogoPanel, NewsPanel, GreetingArea, LogoArea
    └── plan_mode.py               # PlanTool, PlanPanel, TodoItemWidget
```

---

## 19. 运行示例

以下示例展示 Agent 在真实场景中如何一步步运行，包括 LLM 思考 → 工具调用 → 结果反馈 → 继续回答的完整链路。

---

### 示例一：查找并修复代码 Bug

**用户输入：**
```
我的 parse_config.py 第 42 行报了 KeyError，帮我找原因并修复
```

**Agent 内部运行过程：**

```
[LLM 第 1 轮]
  LLM 决策：需要先读文件，了解上下文
  → 调用 Read(path="parse_config.py")

  ┌─ ToolCallCard: Read ───────────────────────────────┐
  │ path: parse_config.py                              │
  │ ✓ 返回 68 行代码                                    │
  └────────────────────────────────────────────────────┘

[LLM 第 2 轮]
  LLM 分析代码，发现第 42 行 `config["timeout"]` 未做默认值处理
  决策：直接修复，使用 Edit 工具做局部替换
  → 调用 Edit(path="parse_config.py", old_str="config[\"timeout\"]",
              new_str="config.get(\"timeout\", 30)")

  ┌─ PermissionCard ─────────────────────────────────────┐
  │ Edit parse_config.py                                  │
  │ [Allow Once]  [Allow All]  [Deny]                     │
  └────────────────────────────────────────────────────────┘
  用户点击：Allow Once

  ┌─ ToolCallCard: Edit ────────────────────────────────┐
  │ ✓ 替换成功，1 处修改                                  │
  └────────────────────────────────────────────────────┘

[LLM 第 3 轮 / stop_reason=end_turn]
  输出最终回复：
  "已将第 42 行的 `config["timeout"]` 改为 `config.get("timeout", 30)`，
   当配置文件中缺少 timeout 字段时将使用默认值 30 秒，不再抛出 KeyError。"
```

**关键点**：LLM 经过 3 轮循环，每轮结束后判断是否还有工具调用；第 3 轮无工具调用，循环终止。

---

### 示例二：多步骤任务 + Plan Mode

**用户输入：**
```
帮我把 utils/ 目录下所有 Python 文件的 print 语句替换为 logging.info，并跑一下测试
```

**Agent 内部运行过程：**

```
[LLM 第 1 轮]
  LLM 判断这是多步骤任务，先建任务清单
  → 调用 TodoWrite(todos=[
      {"id":"t1", "content":"扫描 utils/ 目录的 .py 文件",        "status":"IN_PROGRESS"},
      {"id":"t2", "content":"逐文件替换 print → logging.info",    "status":"PENDING"},
      {"id":"t3", "content":"运行测试套件验证改动",                "status":"PENDING"}
    ], merge=false)

  ┌─ PlanPanel（右侧边栏刷新）────────────────────────────┐
  │  ◐ 扫描 utils/ 目录的 .py 文件                        │
  │  ○ 逐文件替换 print → logging.info                    │
  │  ○ 运行测试套件验证改动                                │
  └────────────────────────────────────────────────────────┘

  → 调用 Glob(pattern="utils/**/*.py")

  ┌─ ToolCallCard: Glob ────────────────────────────────┐
  │ ✓ 找到 8 个文件                                      │
  │ utils/file_utils.py, utils/net_utils.py, ...        │
  └────────────────────────────────────────────────────┘

[LLM 第 2 轮]
  → 调用 TodoWrite(更新 t1=COMPLETE, t2=IN_PROGRESS, merge=true)
  → 对每个文件调用 Grep(pattern="print\\(", path="utils/...")
    确认有 print 语句后，调用 Edit 进行替换
    （每次 Edit 前弹出 PermissionCard，用户点击 Allow All 后自动通过）

  ┌─ PlanPanel 更新 ───────────────────────────────────────┐
  │  ● 扫描 utils/ 目录的 .py 文件                          │
  │  ◐ 逐文件替换 print → logging.info                      │
  │  ○ 运行测试套件验证改动                                  │
  └────────────────────────────────────────────────────────┘

[LLM 第 3 轮]
  → 调用 TodoWrite(更新 t2=COMPLETE, t3=IN_PROGRESS, merge=true)
  → 调用 Bash(command="python -m pytest tests/ -v")

  ┌─ ToolCallCard: Bash ─────────────────────────────────┐
  │ command: python -m pytest tests/ -v                   │
  │ ✓ 全部通过：24 passed in 1.82s                        │
  └──────────────────────────────────────────────────────┘

[LLM 第 4 轮 / stop_reason=end_turn]
  → 调用 TodoWrite(更新 t3=COMPLETE, merge=true)
  输出最终回复：
  "已完成：8 个文件共替换 23 处 print → logging.info，
   测试全部通过（24 passed）。注意已在每个文件顶部自动添加了 `import logging`。"
```

**关键点**：LLM 自主拆解任务并维护 Plan 状态，用户在侧边栏实时看到进度；权限模式切换为 `allow_all` 后无需逐次点击确认。

---

### 示例三：纯问答（无工具调用）

**用户输入：**
```
解释一下 Python 的 GIL 是什么，什么场景下影响性能
```

**Agent 内部运行过程：**

```
[LLM 第 1 轮 / stop_reason=end_turn]
  LLM 判断：这是纯知识问题，不需要调用任何工具
  直接流式输出回复文字（逐 chunk 实时显示在 AssistantBubble 中）：

  "GIL（Global Interpreter Lock）是 CPython 解释器的一把全局锁...
   在 CPU 密集型任务中，多线程因为 GIL 无法真正并行...
   解决方案：multiprocessing / C 扩展 / 使用 PyPy..."

  → on_turn_end(has_tools=False) → 触发 Markdown 渲染
  → 循环检测：no tool_use → break
```

**关键点**：只有一轮，没有工具调用，循环立即终止。Agentic Loop 的最简路径。

---

### 示例四：上下文压缩（后台异步）

**场景**：用户与 Agent 连续对话了 5 轮（达到 `compress_threshold` 默认值）。

```
第 1 轮对话结束
  → _maybe_schedule_compression() 检查：turn_count=1，未到阈值，跳过

第 2、3、4 轮同上

第 5 轮对话结束
  → _maybe_schedule_compression()：turn_count=5，达到阈值！
  → 快照本批 5 轮消息，重置 turn_count=0
  → asyncio.ensure_future(compress_and_summarize(batch))  ← 后台启动，不阻塞用户

  后台任务运行中（用户可以继续提问）：
    Step 1: LLM 摘要本批 5 轮消息 → new_batch_summary
    Step 2: 读取已有 conversation_summary.md → existing_summary
    Step 3: LLM 合并精简 existing + new_batch → merged_summary（≤20条要点）
    Step 4: 覆写 conversation_summary.md

第 6 轮用户开始提问
  若后台任务仍在运行：
    ┌─ 系统消息（dim）──────────────────────────────────────┐
    │ ⏳ Background memory compression is still running —   │
    │    waiting for it to finish before your next message... │
    └────────────────────────────────────────────────────────┘
    状态栏：ctx: ⏳ compressing...
    → 等待后台任务完成
    → 状态栏恢复正常，LLM 调用携带最新 summary
  若后台任务已完成：直接发送，无感知

第 10 轮对话结束（又过了 5 轮）
  → 再次触发压缩：新 5 轮摘要 + 上一次的 summary → 再次合并精简
  → summary 文件保持精炼，不会无限增长
```

**关键点**：压缩完全在后台进行，用户正常对话；多次压缩结果会滚动合并，始终只保留一份精炼的 summary 文件。

---

### 示例五：权限拒绝与中断

**用户输入：**
```
删除 /tmp/old_logs/ 目录下所有文件
```

**Agent 内部运行过程（权限模式：ask_always）：**

```
[LLM 第 1 轮]
  → 调用 Bash(command="rm -rf /tmp/old_logs/")

  ┌─ PermissionCard ─────────────────────────────────────┐
  │ Bash: rm -rf /tmp/old_logs/                           │
  │ [Allow Once]  [Allow All]  [Deny]                     │
  └────────────────────────────────────────────────────────┘
  用户点击：Deny

  → 工具返回结果："User denied permission to run this tool."

[LLM 第 2 轮 / stop_reason=end_turn]
  LLM 收到拒绝结果，回复：
  "好的，我已取消删除操作。如果你需要清理日志，
   可以告诉我具体想保留哪些文件，我会更谨慎地执行。"
```

**中断场景**：
```
用户在 LLM 流式输出过程中按 Ctrl+C
  → QueryEngine._abort = True
  → 当前流式循环检测到 abort 标志，抛出 AbortError
  → 流式输出立即停止，已显示的内容保留
  → 输入栏恢复可用状态
```

---

## 常见问题

**Q: 第一次启动提示找不到 API Key？**
A: 启动后按 `Ctrl+S` 打开设置，填写 Provider 和 API Key。

**Q: /newdaily 一直运行没有完成？**
A: 联网搜索 15-20 条新闻需要 2-5 分钟（硬上限 10 分钟）。可在 `/setup` 中切换到 `qwen-turbo` 或 `qwen-flash` 加速。

**Q: BashTool 在 Windows 上输出乱码？**
A: BashTool 自动检测 UTF-8 / GBK 编码，通常可以正确显示。如遇问题请确认终端设置为 UTF-8。

**Q: 如何禁止 AI 联网搜索？**
A: 在 `/setup` 的 Web Search 区域关闭开关（默认已关闭）。`/newdaily` 命令会强制开启联网搜索。

**Q: 如何连接自定义 OpenAI 兼容 API（如 Ollama、LocalAI）？**
A: 在 `/setup` 中选择 Provider 为 `openai`，填写对应的 Base URL（如 `http://localhost:11434/v1`）和任意 API Key。

**Q: 如何设置 MCP 服务器不在启动时自动连接？**
A: 在 `/setup` MCP 标签页点击该服务器的 **🔄 Auto: ON** 按鈕将其切换为 **⏸ Auto: OFF**，保存后生效。下次启动时该服务器不会自动连接，需要时可在界面点击 **⚡ Connect** 手动连接。

**Q: Plan Mode 和普通对话模式有什么区别？**
A: Plan Mode 是一个右侧面板，用于推荐 AI 对多步骤任务建立可视化的任务列表。它不影响对话本身，可随时开启或关闭。切换三档模式（Auto/Priority/Direct）可调整 AI 使用 TodoWrite 的积极性。
