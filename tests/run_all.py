"""逐个运行 tests/test_*.py，每个文件一个独立进程。

不放进同一个进程跑：有的测试在导入时改全局参数（比如 test_codex_ports 把 cv_weight 设成 0），
同一进程里会带到后面的测试。运行：
    cd <仓库根目录> && python3 tests/run_all.py
"""
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from tests._gamedata import SKIP_PREFIX  # noqa: E402


def main():
    counts = {'通过': 0, '跳过': 0, '失败': 0}
    reasons = set()
    for f in sorted(HERE.glob('test_*.py')):
        r = subprocess.run([sys.executable, str(f)], cwd=HERE.parent, capture_output=True, text=True)
        out = (r.stdout + r.stderr).strip()
        if r.returncode == 0 and r.stdout.startswith(SKIP_PREFIX):
            status, note = '跳过', r.stdout.strip()[len(SKIP_PREFIX):]
        elif r.returncode == 0:
            status, note = '通过', ''
        else:
            status, note = '失败', '\n'.join('    ' + l for l in out.splitlines()[-15:])
        counts[status] += 1
        print(f'{status}  {f.name}')
        if status == '跳过':
            reasons.add(note)
        elif status == '失败':
            print(note)
    for reason in sorted(reasons):
        print('跳过原因：' + reason)
    print('合计：' + '，'.join(f'{k} {v}' for k, v in counts.items()))
    return 1 if counts['失败'] else 0


if __name__ == '__main__':
    sys.exit(main())
