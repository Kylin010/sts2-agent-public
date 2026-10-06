"""依赖游戏数据的测试先过这一关。

kb/cards.json、relics.json、potions.json 带游戏文本，不随仓库分发（见 README「生成知识库」）。
policy/kb.py 一导入就读这三个文件，没生成时凡是 import policy 的测试都会直接报 FileNotFoundError。
这里改成「跳过」并写明原因：被 unittest / pytest 收集时记为 skipped；单独运行某个测试文件时打印原因后正常退出。
"""
import sys
import unittest
from pathlib import Path

KB = Path(__file__).resolve().parents[1] / 'kb'
MISSING = [f'kb/{n}' for n in ('cards.json', 'relics.json', 'potions.json') if not (KB / n).exists()]
REASON = f'缺少 {"、".join(MISSING)}，先按 README「生成知识库」生成'
SKIP_PREFIX = '跳过：'

# 只有个别测试用到 policy 时，用这个装饰单个测试，别的照常跑
needs_kb = unittest.skipIf(MISSING, REASON)


def require_kb(module_name):
    """整个文件都依赖游戏数据时，在 import policy 之前调用，参数传 __name__。"""
    if not MISSING:
        return
    if module_name == '__main__':        # python3 tests/test_xxx.py 直接运行
        print(SKIP_PREFIX + REASON)
        sys.exit(0)
    raise unittest.SkipTest(REASON)     # 模块级 SkipTest：unittest / pytest 都会把整个文件记成 skipped
