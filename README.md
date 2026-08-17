# Windows 原生 Claude Code 手机远程控制

把 Windows 上的 Claude Code 变成一台可远程的工作站：手机新建 session 后，电脑上升起的窗口尽量和你平时右键“在此处打开 Git Bash”再输入 `claude` 的体验一致。

## 这条链路现在长什么样

```text
手机 MobileCLI App
    ↓
MobileCLI daemon 收到 SpawnSession(claude)
    ↓
Windows Terminal 打开 Git Bash profile
    ↓
Git Bash 读取 ~/.bashrc
    ↓
MOBILECLI_AUTO_RUN=claude 触发一次性自动启动
    ↓
exec mobilecli claude
    ↓
mobilecli wrapper 注册 PTY / 连接 daemon
    ↓
Claude Code 进入交互式 session
```

这仓库的目标不是“再造一个终端”，而是**让手机启动出来的 session 复用你电脑上右键打开 Git Bash 的那条原生入口**，再用一个一次性的环境变量把 `claude` 自动跑起来。

## 为什么要这样做

之前手机端自己拼 `bash -lc ...`、`mobilecli ... claude` 之类的链路，和你电脑上手动打开 Git Bash 再输入 `claude` 不一致，导致：

- 鼠标点位不对
- 颜色/主题看起来不一样
- 键盘行为和本机手动打开不完全一致

现在改成：

- **电脑端窗口本体**：直接复用右键菜单同款 `wt.exe -d "%V" -p "Git Bash"`
- **Claude 启动动作**：由 `~/.bashrc` 里的一次性 `MOBILECLI_AUTO_RUN=claude` 触发

这样手机新建 session 时，终端宿主、shell 初始化、输入行为都尽量对齐到你本机手动操作那条路。

## 关键文件

| 文件 | 作用 |
|---|---|
| `README.md` | 整个链路和复现步骤 |
| `hook-notify.py` | Claude 停止时通过 Bark 推送到手机 |
| `mobilecli-sync.py` | 手机同步开关 |
| `tailscale_shim.cs` | xEdge / Tailscale 兼容垫片 |

## 你电脑上右键 Git Bash 的实际入口

注册表里实际是：

```text
"C:\Users\mac\AppData\Local\Microsoft\WindowsApps\wt.exe" -d "%V" -p "Git Bash"
```

这就是本仓库对齐的目标入口。

## `~/.bashrc` 里的自动启动

当 Windows Terminal 打开 Git Bash 后，`.bashrc` 会先加载你的普通别名：

```bash
alias claude='mobilecli claude'
```

然后再看一次性环境变量：

```bash
if [ -n "$MOBILECLI_AUTO_RUN" ] && [ -z "$MOBILECLI_AUTO_RUN_DONE" ]; then
  export MOBILECLI_AUTO_RUN_DONE=1
  unset MOBILECLI_AUTO_RUN
  exec mobilecli claude
fi
```

这段只负责让手机新开的窗口自动进入 Claude；你平时在电脑里手动打开 Git Bash 时，它不会影响正常使用。

## MobileCLI 这边做了什么

`daemon.rs::spawn_session_windows` 现在只负责：

1. 打开和右键菜单一致的 Windows Terminal Git Bash profile
2. 设置 `MOBILECLI_AUTO_RUN=claude`
3. 让 Git Bash 自己跑到 `mobilecli claude`

手机侧不再手写一大串 `bash -lc` / `mobilecli claude` wrapper，减少和本机手动流程的偏差。

## 推送通知链路

Claude 停止响应时，`hook-notify.py` 会读取 `last_assistant_message`：

- 像在等你拍板 → 推 `Claude 在等你`
- 只是完成任务 → 推 `Claude 已完成`

通知通过 Bark 发到手机，`BARK_KEY` 从 `~/.claude/settings.json` 的 `env` 里读取，不硬编码进脚本。

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

把 `mobilecli.exe` 放到 `C:\mobilecli\`，并确保 daemon 能启动。

### 4. 配好 Shell Hook

让 `mobilecli` 的 auto-launch 逻辑写入 `.bashrc` / `$PROFILE`，至少要有：

```bash
alias claude='mobilecli claude'
```

### 5. 在 `~/.bashrc` 加一次性自动启动块

```bash
if [ -n "$MOBILECLI_AUTO_RUN" ] && [ -z "$MOBILECLI_AUTO_RUN_DONE" ]; then
  export MOBILECLI_AUTO_RUN_DONE=1
  unset MOBILECLI_AUTO_RUN
  exec mobilecli claude
fi
```

### 6. 设置 Bark

把 Bark Device Key 放进 `~/.claude/settings.json`：

```json
{
  "env": {
    "BARK_KEY": "你的 Device Key"
  }
}
```

### 7. 手机新建 Claude session

手机端选择 `Claude Code`，电脑上应该升起和右键 Git Bash 入口一致的窗口，然后自动进入 Claude。

## 验证标准

你要看的不是“有没有窗口”，而是这几个点：

- 颜色和主题和电脑手动右键打开的一致
- 鼠标点位和输入光标行为一致
- 上下键、回车、Esc、Ctrl-C 行为一致
- Claude 自动启动
- 手机收到 Bark 推送

## 备注

- `BARK_KEY` 只放在本机 `settings.json`，不进仓库
- `~/.bashrc` 的自动启动块只做一次性触发，不改你平时手动打开 Git Bash 的习惯
- 如果你要继续复刻电脑手动入口，优先改 shell / 启动入口，不要再在 daemon 里硬拼一个新的终端行为
