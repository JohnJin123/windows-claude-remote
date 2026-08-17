# -*- coding: utf-8 -*-
"""mobilecli 同步开关：控制出门后 Claude 是否推送通知到手机。

用法：
  python mobilecli-sync.py on      # 开启同步（出门）
  python mobilecli-sync.py off     # 关闭同步（在家）
  python mobilecli-sync.py status  # 查看当前状态
"""
import os, sys

FLAG = os.path.expanduser(r'~/.mobilecli/sync-enabled')


def main():
    arg = sys.argv[1].lower() if len(sys.argv) > 1 else 'status'
    if arg == 'on':
        with open(FLAG, 'w', encoding='utf-8') as f:
            f.write('enabled\n')
        print('同步已开启：Claude 每次回答完会推送到手机。')
    elif arg == 'off':
        if os.path.exists(FLAG):
            os.remove(FLAG)
        print('同步已关闭：不再推送。')
    else:
        print('同步：' + ('开启（出门）' if os.path.exists(FLAG) else '关闭（在家）'))


if __name__ == '__main__':
    main()
