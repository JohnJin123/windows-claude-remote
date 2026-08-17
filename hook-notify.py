# -*- coding: utf-8 -*-
"""Claude Code hook → 手机 Bark 推送桥接（最终版）。

只监听 Stop hook，用 last_assistant_message（claude 最后说的话）区分：
- 拍板（以问句结尾 / 含请求决策词）→ 推「Claude 在等你」
- 单纯完成（陈述任务完成）→ 推「Claude 已完成」

开关文件 ~/.mobilecli/sync-enabled：存在=出门推送，不存在=在家静默。
"""
import sys, json, os, urllib.request, urllib.parse
from datetime import datetime

LOG = os.path.expanduser(r'~/.mobilecli/hook-events.log')
SYNC_FLAG = os.path.expanduser(r'~/.mobilecli/sync-enabled')
# Bark Device Key 从环境变量读取（在 ~/.claude/settings.json 的 env 里配置），
# 避免把推送凭证硬编码进脚本、随仓库泄露。
BARK_KEY = os.environ.get('BARK_KEY', '')


def read_hook_input():
    try:
        # Windows 上 Python 默认用 GBK 读 stdin，而 Claude Code 传的是 UTF-8，
        # 必须显式用 UTF-8 解码，否则中文（尤其全角问号）会乱码。
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
    """判断 claude 最后的消息是否在等你拍板（问句/请求决策）。"""
    t = (text or '').strip()
    if not t:
        return False
    # 取最后 200 字符（问句可能被 markdown 括号/多行包裹，不能只看末字符）
    tail = t[-200:]
    if '？' in tail or '?' in tail or '吗' in tail or '呢' in tail:
        return True
    for kw in ('是否', '要不要', '请确认', '请选择', '请决定', '告诉我', '你想', '需要我', '你来定', '好奇', '你觉得'):
        if kw in tail:
            return True
    return False


def send_bark(title, body):
    url = 'https://api.day.app/{}/{}/{}'.format(
        BARK_KEY,
        urllib.parse.quote(title, safe=''),
        urllib.parse.quote(body, safe=''),
    )
    urllib.request.urlopen(url, timeout=10)


def main():
    data = read_hook_input()
    event = data.get('hook_event_name', '?')
    last_msg = data.get('last_assistant_message', '')

    log({
        'time': datetime.now().isoformat(timespec='seconds'),
        'hook_event_name': event,
        'last_msg_tail': (last_msg or '')[-80:],
        'notified': None,
    })

    if not os.path.exists(SYNC_FLAG):
        return

    if not BARK_KEY:
        log({'time': datetime.now().isoformat(timespec='seconds'),
             'hook_event_name': event, 'notified': 'error',
             'error': 'BARK_KEY 环境变量未设置'})
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
