"""把学到的偏好里某几类清零（发现学偏了时用，10/2：路线「别打精英」、篝火「别升级」是战斗变强前学的，已经过时）。

用法：python3 tools/reset_prefs.py route rest          # 清掉 route:* 和 rest:* 开头的权重
先把原文件备份到 lab/rl/prefs-before-reset-时间.json，再改 data/learned_prefs.json。
"""
import json, os, shutil, sys, time
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = f'{HERE}/data/learned_prefs.json'
kinds = sys.argv[1:]
if not kinds: sys.exit('要清哪几类？例如：python3 tools/reset_prefs.py route rest')
bak = f'{HERE}/lab/rl/prefs-before-reset-{time.strftime("%m%d-%H%M%S")}.json'
shutil.copy(PATH, bak)
d = json.load(open(PATH)); w = d.get('w', {})
gone = [k for k in w if k.split(':', 1)[0] in kinds]
for k in gone: w.pop(k)
d['w'] = w; d.setdefault('resets', []).append({'time': time.strftime('%m-%d %H:%M'), 'kinds': kinds, 'removed': len(gone)})
json.dump(d, open(PATH, 'w'), ensure_ascii=False, indent=0)
print(f'清掉 {len(gone)} 个权重（{kinds}），剩 {len(w)} 个；原文件备份在 {bak}')
