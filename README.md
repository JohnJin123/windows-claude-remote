# Windows 原生 Claude Code 手机远程控制

把 Windows 上的 Claude Code 变成一台可远程的「工作站」——出门后手机实时查看/操作同一个 session，Claude 需要拍板或任务完成时推送通知到手机。

> **为什么强调「Windows 原生」？** 能「手机远程控制 Claude Code」的方案（[MobileCLI](https://github.com/MobileCLI/mobilecli)、ServerCC、tmux + Tailscale 全家桶）几乎都假设你在 macOS/Linux。这个仓库专治 Windows 原生会踩的一串坑，每条都是实测踩出来的：xEdge（国产 Tailscale fork）适配、`\\?\` 扩展路径让 session 目录回落 `C:\Windows`、`CREATE_NEW_CONSOLE` 空窗口、OSC 11 颜色序列泄漏进输入栏、Expo 推送因 APNs 凭据失效改用 Bark……照着抄能省一整天。

```
iPhone MobileCLI ── xEdge 隧道 ──► Windows MobileCLI daemon ──► Claude Code ──► DeepSeek 中转 API
        │                              │  ▲
        │  实时 attach / 输入            │  │ 手机发起 session 时，
        └──────────────────────────────┘  │ 电脑弹出 Git Bash 窗口显示 claude
                                          └─ Claude 停止时 → hook → Bark 推送到手机
```

核心组件：

| 组件 | 作用 |
|---|---|
| **MobileCLI**（Rust daemon v0.2.1） | session 管理 + 手机 WebSocket attach |
| **xEdge**（干将互联，Tailscale 国产 fork） | 虚拟组网，让手机穿透到电脑 |
| **Bark**（iOS 推送 app） | 接收 Claude 通知（Expo/APNs 凭据失效，弃用） |
| **Claude Code hook** | 在 Claude 停止时触发推送脚本 |

---

## 前置条件

- Windows 10/11，用户可访问 `C:\mobilecli\`
- Git for Windows（含 mintty + bash），Windows Terminal
- Python 3.x
- Rust GNU 工具链（`x86_64-pc-windows-gnu`）+ MinGW-w64 gcc（重编译 MobileCLI 时用）
- iPhone：MobileCLI app、Bark app、xEdge

---

## 阶段 1：xEdge 组网

1. 电脑和手机都安装 xEdge（干将互联）。
2. 电脑虚拟 IP 设为 `100.64.0.1`，手机 `100.64.0.2`。
3. **iOS 必须真正打开 VPN 开关**（状态栏出现 VPN 图标才算连上，只「允许 VPN 配置」不算）。
4. 验证：电脑 `xedge status` 能看到手机，`ping 100.64.0.2` 通。

---

## 阶段 2：MobileCLI 安装 + 配对

1. `mobilecli.exe` 放到 `C:\mobilecli\`。
2. 配置文件 `C:\Users\<你>\.mobilecli\config.json`，关键字段：

```json
{
  "connection_mode": "tailscale",
  "tailscale_ip": "100.64.0.1",
  "filesystem": {
    "allowed_roots": ["C:\\Users\\<你>\\Desktop\\Claude"],
    "whole_home_enabled": false
  }
}
```

3. 生成配对凭证 + 二维码（`make_pairing.py`），扫描后手机 app 连上 daemon。凭证含 `push:register` scope。

---

## 阶段 3：tailscale 垫片（xEdge 兼容）

MobileCLI 的 daemon 硬编码调用 `tailscale status --json` 来探测 Tailscale 网段，但 xEdge 不提供 `tailscale` 命令。用一个 C# 垫片骗过它，让它把监听地址绑定到 xEdge 虚拟 IP。

`tailscale_shim.cs`：

```csharp
using System;

class TailscaleShim
{
    static int Main(string[] args)
    {
        Console.Out.Write(
            "{\"BackendState\":\"Running\"," +
            "\"Self\":{\"ID\":\"xedge-shim\",\"HostName\":\"<YOUR-HOSTNAME>\"}," +
            "\"TailscaleIPs\":[\"100.64.0.1\"]}"
        );
        return 0;
    }
}
```

编译（Windows 自带 csc.exe）：

```
csc.exe /out:C:\mobilecli\tailscale.exe tailscale_shim.cs
```

确保 daemon 启动时 `C:\mobilecli` 在 PATH 最前面（见阶段 8 自启动脚本），让垫片优先于真实 Tailscale CLI。

---

## 阶段 4：防火墙

MobileCLI 监听 9847 端口。Windows 防火墙规则名大小写不敏感，旧的「阻止」规则会拦 xEdge 入站（阻止优先于允许）。先删干净再重加：

```
netsh advfirewall firewall delete rule name="mobilecli"
netsh advfirewall firewall add rule name="MobileCLI" dir=in action=allow protocol=TCP localport=9847
```

---

## 阶段 5：MobileCLI 源码修复 + 重编译

源码默认有几处 Windows 上会踩坑的地方，需打补丁后重编译。

**编译环境**（Rust GNU + MinGW gcc）：

```powershell
$env:PATH = "C:\Users\<你>\.cargo\bin;D:\chain\winlibs-x86_64-posix-seh-gcc-13.2.0-llvm-16.0.6-mingw-w64ucrt-11.0.0-r1\mingw64\bin;" + $env:PATH
Set-Location "<mobilecli 源码>\cli"
cargo build --release
```

### 修复 A：Windows 扩展路径前缀（`daemon.rs`）

`default_mobile_spawn_working_dir()` 里 `canonicalize()` 会返回 `\\?\C:\...` 扩展路径，cmd.exe 当 UNC 拒绝，导致 session 默认目录回落 `C:\Windows`。剥掉 `\\?\` 前缀：

```rust
path.canonicalize()
    .ok()
    .and_then(|p| p.to_str().map(|s| {
        s.strip_prefix("\\\\?\\").unwrap_or(s).to_string()
    }))
```

### 修复 B：手机发起 session 时，电脑弹出 Git Bash 窗口（`daemon.rs`）

原实现 `spawn_session_windows` 用 `CREATE_NEW_CONSOLE` 直接 spawn `mobilecli.exe`，但新进程继承 daemon 的（后台）stdout 句柄，新窗口是空的。改成用 mintty 拉起一个 Git Bash 窗口运行 mobilecli：

```rust
let mut inner = format!("\"{}\" --name \"{}\" --quiet", mobilecli_bin, session_name);
if let Some(dir) = working_dir {
    inner.push_str(&format!(" --dir \"{}\"", dir));
}
inner.push(' ');
inner.push_str(effective_command);
for a in &effective_args {
    inner.push_str(" \"");
    inner.push_str(a);
    inner.push('"');
}

let mintty = r"C:\Program Files\Git\usr\bin\mintty.exe";
let bash = r"C:\Program Files\Git\bin\bash.exe";
let mut cmd = std::process::Command::new(mintty);
cmd.arg("-e").arg(bash).arg("-lc").arg(&inner);
```

### 修复 C：过滤 OSC 10/11 颜色序列泄漏（`pty_wrapper.rs`）

Claude Code 有个已知 bug（[#12910](https://github.com/anthropics/claude-code/issues/12910)）：终端背景色查询响应 `\x1b]11;rgb:...\x07` 会泄漏进输入栏。在 PTY 输出回显到本地终端前把它滤掉：

```rust
fn strip_osc_color_queries(data: &[u8]) -> Vec<u8> {
    let mut out = Vec::with_capacity(data.len());
    let mut i = 0;
    while i < data.len() {
        if data[i] == 0x1b
            && i + 1 < data.len() && data[i + 1] == b']'
            && i + 2 < data.len() && data[i + 2] == b'1'
            && i + 3 < data.len() && (data[i + 3] == b'0' || data[i + 3] == b'1')
            && i + 4 < data.len() && data[i + 4] == b';'
        {
            let mut j = i + 5;
            while j < data.len() {
                if data[j] == 0x07 { j += 1; break; }
                if data[j] == 0x1b && j + 1 < data.len() && data[j + 1] == b'\\' { j += 2; break; }
                j += 1;
            }
            i = j;
            continue;
        }
        out.push(data[i]);
        i += 1;
    }
    out
}
```

在 PTY 输出处理处应用：

```rust
Some(data) = output_rx.recv() => {
    let filtered = strip_osc_color_queries(&data);
    stdout.write_all(&filtered)?;   // 写过滤后的，不再泄漏
    ...
}
```

### 编译 + 替换 + 重启

```powershell
# 停 daemon、替换二进制
Get-Process mobilecli | Stop-Process -Force
Copy-Item "target\release\mobilecli.exe" "C:\mobilecli\mobilecli.exe" -Force

# 清理 Claude Code 子会话标记（否则 daemon 异常），再重启
Remove-Item Env:CLAUDE_CODE_CHILD_SESSION -ErrorAction SilentlyContinue
Remove-Item Env:CLAUDE_CODE_ENTRYPOINT -ErrorAction SilentlyContinue
$env:PATH = "C:\mobilecli;" + $env:PATH
Start-Process "C:\mobilecli\mobilecli.exe" -ArgumentList "daemon","--port","9847" -WindowStyle Hidden
```

---

## 阶段 6：push 通知（Claude Code hook + Bark）

MobileCLI 自带的「等待状态检测」只认英文触发词，中文输出的 Claude Code 永远匹配不到，所以走 hook 桥接：Claude 每次**停止响应**时，hook 触发一个脚本，脚本判断「是拍板还是单纯完成」，再用 Bark 推送到手机。

### 推送脚本 `hook-notify.py`

```python
# -*- coding: utf-8 -*-
import sys, json, os, urllib.request, urllib.parse
from datetime import datetime

LOG = os.path.expanduser(r'~/.mobilecli/hook-events.log')
SYNC_FLAG = os.path.expanduser(r'~/.mobilecli/sync-enabled')
# Bark Key 从环境变量读（settings.json 的 env 里配置），避免硬编码进脚本
BARK_KEY = os.environ.get('BARK_KEY', '')

def read_hook_input():
    try:
        raw = sys.stdin.buffer.read().decode('utf-8', errors='replace')
        return json.loads(raw) if raw.strip() else {}
    except Exception:
        return {}

def log(entry):
    try:
        with open(LOG, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False, default=str) + '\n')
    except Exception:
        pass

def is_asking(text):
    t = (text or '').strip()
    if not t:
        return False
    tail = t[-200:]
    if '？' in tail or '?' in tail or '吗' in tail or '呢' in tail:
        return True
    for kw in ('是否', '要不要', '请确认', '请选择', '请决定', '告诉我', '你想', '需要我', '你来定', '好奇', '你觉得'):
        if kw in tail:
            return True
    return False

def send_bark(title, body):
    url = 'https://api.day.app/{}/{}/{}'.format(
        BARK_KEY, urllib.parse.quote(title, safe=''), urllib.parse.quote(body, safe=''))
    urllib.request.urlopen(url, timeout=10)

def main():
    data = read_hook_input()
    event = data.get('hook_event_name', '?')
    last_msg = data.get('last_assistant_message', '')

    log({'time': datetime.now().isoformat(timespec='seconds'),
         'hook_event_name': event, 'last_msg_tail': (last_msg or '')[-80:], 'notified': None})

    if not os.path.exists(SYNC_FLAG):
        return

    if not BARK_KEY:
        log({'time': datetime.now().isoformat(timespec='seconds'),
             'hook_event_name': event, 'notified': 'error', 'error': 'BARK_KEY 未设置'})
        return

    if event == 'Stop':
        if is_asking(last_msg):
            title, body = 'Claude 在等你', '需要你的输入或拍板'
        else:
            title, body = 'Claude 已完成', '任务完成，无需你处理'
    else:
        title, body = 'Claude 在等你', '需要你的输入或拍板'

    try:
        send_bark(title, body)
        log({'time': datetime.now().isoformat(timespec='seconds'),
             'hook_event_name': event, 'notified': 'ok', 'title': title})
    except Exception as e:
        log({'time': datetime.now().isoformat(timespec='seconds'),
             'hook_event_name': event, 'notified': 'error', 'error': str(e)})

if __name__ == '__main__':
    main()
```

> 关键点：Windows 上 Python 默认用 GBK 读 stdin，而 Claude Code 传 UTF-8，**必须显式 `sys.stdin.buffer.read().decode('utf-8')`**，否则中文（尤其全角问号 `？`）会乱码，导致拍板判断失效。

### 在 `~/.claude/settings.json` 里挂 Stop hook

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          { "type": "command", "command": "python C:/<路径>/hook-notify.py" }
        ]
      }
    ]
  }
}
```

### Bark 设置

手机装 Bark app，拿到 Device Key（app 首页的推送地址 `https://api.day.app/<Key>/` 中间那串）。把它配到 `~/.claude/settings.json` 的 `env` 里作为环境变量，脚本运行时自动读取：

```json
{
  "env": {
    "BARK_KEY": "你的 Device Key"
  }
}
```

这样脚本本身不含任何凭证，可以安全进 git。

> **为什么不用 Expo/APNs**：MobileCLI 自带的 Expo 推送，实测 APNs 返回 `InvalidProviderToken`（开发者侧 APNs 凭据失效，app 级问题，本地无法修），所以换成 Bark。

---

## 阶段 7：alias 让 `claude` 透明走 mobilecli + 开关

手机要能实时 attach 到 session，session 必须由 `mobilecli claude` 起。让用户照常敲 `claude`，实际透明执行 `mobilecli claude`：

`~/.bashrc`：

```bash
alias claude='mobilecli claude'
alias sync-on='python C:/<路径>/mobilecli-sync.py on'
alias sync-off='python C:/<路径>/mobilecli-sync.py off'
```

PowerShell `$PROFILE`：

```powershell
function claude { mobilecli claude @args }
function sync-on { python C:/<路径>/mobilecli-sync.py on }
function sync-off { python C:/<路径>/mobilecli-sync.py off }
```

（mobilecli 内部用 `CommandBuilder::new("claude")` 直接 exec，不走 shell alias，且设了 `MOBILECLI_SESSION=1` 防递归，所以不会死循环。）

### 开关脚本 `mobilecli-sync.py`

```python
import os, sys
FLAG = os.path.expanduser(r'~/.mobilecli/sync-enabled')

def main():
    arg = sys.argv[1].lower() if len(sys.argv) > 1 else 'status'
    if arg == 'on':
        open(FLAG, 'w', encoding='utf-8').write('enabled\n')
        print('同步已开启')
    elif arg == 'off':
        if os.path.exists(FLAG):
            os.remove(FLAG)
        print('同步已关闭')
    else:
        print('同步：' + ('开启（出门）' if os.path.exists(FLAG) else '关闭（在家）'))

if __name__ == '__main__':
    main()
```

---

## 阶段 8：daemon 自启动

`%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\mobilecli-daemon.cmd`：

```bat
@echo off
set "PATH=C:\mobilecli;%PATH%"
start "" /min "C:\mobilecli\mobilecli.exe" daemon --port 9847
```

（登录时启动，环境干净、无 Claude Code 子会话标记；`PATH` 前置 `C:\mobilecli` 让 tailscale 垫片生效。）

---

## 日常使用

```
出门前：  sync-on                      # 开通知
          claude                       # 照常敲（= mobilecli claude）

Claude 拍板等你 → 手机收到「Claude 在等你」
Claude 跑完任务 → 手机收到「Claude 已完成」
手机点开 MobileCLI → attach 同一 session → 实时看 + 发消息继续跑
手机上发起新 session → 电脑弹出 Git Bash 窗口显示 claude

回家后：  sync-off                     # 关通知
```

---

## 已知问题 / 备注

- **Expo 推送不可用**：APNs `InvalidProviderToken`，是 MobileCLI 上游凭据问题，已换 Bark。
- **OSC 11 乱码**：Claude Code bug #12910，已在 `pty_wrapper.rs` 里过滤（修复 C）。
- **通知靠文本判断拍板/完成**：`is_asking` 用启发式（问号/疑问词），非 100% 精准，但覆盖常见中文问句。
- **daemon 需干净环境启动**：若发现 transcript saving off / 无法输入，检查是否残留 `CLAUDE_CODE_CHILD_SESSION` 环境变量。
