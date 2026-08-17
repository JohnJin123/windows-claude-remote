# Windows 原生 Claude Code 手机远程控制

把 Windows 上的 Claude Code 变成一台可远程的工作站：手机新建 session 后，电脑上升起的窗口和你平时右键“在此处打开 Git Bash”再输入 `claude` 的体验一致，且自动进入 Claude、完成或等你拍板时通过 Bark 推送到手机。

## 这条链路现在长什么样

```text
手机 MobileCLI App
    ↓
MobileCLI daemon 收到 SpawnSession(claude)
    ↓
daemon 写一次性标记文件 ~/.mobilecli/spawn-once
    ↓
Windows Terminal 打开 Git Bash profile（和右键同款）
    ↓
Git Bash 读取 ~/.bashrc，检测到标记文件
    ↓
exec /c/mobilecli/mobilecli.exe claude   （并删除标记）
    ↓
mobilecli wrapper 注册 PTY / 连接 daemon
    ↓
Claude Code 进入交互式 session
```

这仓库的目标不是“再造一个终端”，而是**让手机启动出来的 session 复用你电脑上右键打开 Git Bash 的那条原生入口**，再靠一个一次性标记文件把 `claude` 自动跑起来。

## 关键文件

| 文件 | 作用 |
|---|---|
| `README.md` | 整条链路、复现步骤、排障记录 |
| `hook-notify.py` | Claude 停止时通过 Bark 推送到手机（带失败重试） |
| `mobilecli-sync.py` | 手机同步开关（出门开 / 在家关） |
| `tailscale_shim.cs` | xEdge / Tailscale 兼容垫片 |

## 电脑上右键 Git Bash 的实际入口

注册表里实际是：

```text
"C:\Users\mac\AppData\Local\Microsoft\WindowsApps\wt.exe" -d "%V" -p "Git Bash"
```

这就是本仓库对齐的目标入口。

## 为什么用“标记文件”而不是环境变量或 wt 命令行

历史上有过两种自动启动方案，都因 Windows Terminal 的机制而失败，最后改为标记文件：

1. **`MOBICLI_AUTO_RUN` 环境变量**（daemon `cmd.env(...)` 注入）：Windows Terminal 是**单实例**的。当已有一个实例在跑时，新 tab 由旧实例创建，继承的是**旧实例的环境**，daemon 注入的环境变量根本到不了 Git Bash，`$MOBICLI_AUTO_RUN` 为空 → 不自动启动。

2. **wt 命令行直接传命令**（`wt ... -- bash -lc "exec ..."`）：wt 会对 `--` 后面的 commandline 用 cmd 规则重新解析，导致 `-lc` 参数里的**尾部引号被吃掉**（报错 `Command not found: claude"`），从 Windows 原生进程（daemon/cmd/PowerShell）调用时必现。

3. **标记文件（当前方案）**：daemon 打开窗口前先写 `~/.mobilecli/spawn-once`，Git Bash 读 `.bashrc` 时检测到就自动进 claude 并删标记。完全不依赖 wt 的参数传递或单实例环境，最稳。

## `~/.bashrc` 里的自动启动

当 Windows Terminal 打开 Git Bash 后，`.bashrc` 先加载别名：

```bash
alias claude='/c/mobilecli/mobilecli.exe claude'
```

再检测一次性标记文件：

```bash
# 手机启动的 Git Bash：如果存在一次性标记文件，则自动进入 Claude。
# daemon 在打开手机窗口前会创建 ~/.mobilecli/spawn-once 文件；本块消费后删除。
if [ -f "$HOME/.mobilecli/spawn-once" ] && [ -z "$MOBILECLI_SPAWN_DONE" ]; then
  export MOBILECLI_SPAWN_DONE=1
  rm -f "$HOME/.mobilecli/spawn-once"
  exec /c/mobilecli/mobilecli.exe claude
fi
```

这段只负责让手机新开的窗口自动进入 Claude；你平时在电脑里手动打开 Git Bash 时，因为没有标记文件，不会触发。

## MobileCLI daemon 这边做了什么

`daemon.rs::spawn_session_windows` 现在只负责：

1. 写一次性标记文件 `~/.mobilecli/spawn-once`
2. 打开和右键菜单一致的 Windows Terminal Git Bash profile

手机侧不再手写 `bash -lc` / `mobilecli claude` wrapper，减少和本机手动流程的偏差。

## 推送通知链路（Bark）

Claude 停止响应时（Stop hook），`hook-notify.py` 会读取 `last_assistant_message`：

- 像在等你拍板（问句结尾 / 含决策词）→ 推 `Claude 在等你`
- 只是完成任务 → 推 `Claude 已完成`

通知通过 Bark 发到手机，`BARK_KEY` 从 `~/.claude/settings.json` 的 `env` 里读取，不硬编码进脚本。

### 推送可靠性

Bark 服务器 `api.day.app` 的 SSL 连接**不稳定**（随机 `EOF occurred in violation of protocol` / `handshake timed out`），导致推送偶发失败。`hook-notify.py` 的 `send_bark` 带**失败重试**（最多 4 次，指数退避 + 抖动），实测第 1 次失败后第 2 次重试即可成功。

### hook 配置

在 `~/.claude/settings.json` 里挂 Stop hook：

```json
{
  "env": { "BARK_KEY": "你的 Device Key" },
  "hooks": {
    "Stop": [ { "hooks": [ { "command": "python C:/Users/mac/mobilecli-setup/hook-notify.py", "type": "command" } ] } ]
  }
}
```

## 复现步骤

### 1. 安装依赖

- Windows 10/11
- Git for Windows
- Windows Terminal
- Python 3
- Rust GNU 工具链 + MinGW-w64 gcc
- iPhone 上安装 MobileCLI、Bark、xEdge

### 2. 设置 xEdge

电脑和手机都连上同一个 xEdge 网络，确认手机能到电脑虚拟 IP。

### 3. 配好 MobileCLI

把 `mobilecli.exe` 放到 `C:\mobilecli\`，并确保 daemon 能启动（启动文件夹里有 `mobilecli-daemon.cmd`）。

### 4. 配好 Shell 别名

在 `~/.bashrc` 里：

```bash
alias claude='/c/mobilecli/mobilecli.exe claude'
```

### 5. 在 `~/.bashrc` 加一次性标记自动启动块

```bash
if [ -f "$HOME/.mobilecli/spawn-once" ] && [ -z "$MOBILECLI_SPAWN_DONE" ]; then
  export MOBILECLI_SPAWN_DONE=1
  rm -f "$HOME/.mobilecli/spawn-once"
  exec /c/mobilecli/mobilecli.exe claude
fi
```

### 6. 设置 Bark

把 Bark Device Key 放进 `~/.claude/settings.json`，并挂上 Stop hook（见上文「hook 配置」）。

### 7. 手机新建 Claude session

手机端选择 `Claude Code`，电脑上应该升起和右键 Git Bash 入口一致的窗口，然后自动进入 Claude。输出完成 / 等你拍板时，手机收到 Bark 通知。

## 验证标准

- 颜色和主题和电脑手动右键打开的一致
- 鼠标点位和输入光标行为一致
- 上下键、回车、Esc、Ctrl-C 行为一致
- Claude 自动启动（不需要手动敲 `claude`）
- 手机收到 Bark 推送

## 排障记录

### daemon 换了新逻辑但不生效

替换 `C:\mobilecli\mobilecli.exe` 后，**必须重启 daemon** 才加载新代码。当前在跑的 daemon 可能是旧实例（看它的启动时间是否早于 exe 的替换时间）。重启方式：

```bat
:: 停旧 daemon，再启新 daemon（独立进程，避免断开当前远程会话）
powershell -NoProfile -ExecutionPolicy Bypass -File "C:\Users\mac\AppData\Local\Temp\mobilecli-restart.ps1"
```

重启会短暂断开手机远程会话，脚本独立进程能跑完，之后手机重新 attach 即可。

### 手机新建 session 收不到 Bark 通知

先看 `~/.mobilecli/hook-events.log` 里那条记录是 `notified: ok` 还是 `notified: error`：

- `notified: error` + SSL 错误 → 是 Bark 服务器抖动，新版 `hook-notify.py` 已有重试，重新验证即可。
- 日志里根本没有新建 session 的记录 → 说明 Stop hook 没触发，检查 `settings.json` 的 hook 配置是否对该 session 生效。

### wt 引号报错 `Command not found: claude"`

这是 wt 命令行传命令被解析坏的典型症状，**不要**再用 `wt ... -- bash -lc "exec ...claude"` 传命令，改用标记文件方案。

## 备注

- `BARK_KEY` 只放在本机 `settings.json`，不进仓库
- `~/.bashrc` 的自动启动块只在检测到标记文件时触发，不改你平时手动打开 Git Bash 的习惯
- 如果你要继续复刻电脑手动入口，优先改 shell / 启动入口，不要再在 daemon 里硬拼一个新的终端行为
