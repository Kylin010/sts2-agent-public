"""读取可调参数（params.json），命令行 --set 键=值 可以覆盖。所有策略模块都从这里取数。

按遭遇的专属参数：kb/encounter_params.json（lab.py 用随机搜索找出来的），战斗里由 policy/combat.py 临时换上，
打完这一步自动恢复（scoped）。
"""
import contextlib, json, os
HERE = os.path.dirname(os.path.abspath(__file__))
P = json.load(open(f'{HERE}/params.json'))
_ENC_PATH = f'{HERE}/kb/encounter_params.json'
ENC = {k: v for k, v in (json.load(open(_ENC_PATH)) if os.path.exists(_ENC_PATH) else {}).items() if not k.startswith('_')}


def override(pairs):
    for kv in pairs or []:
        k, v = kv.split('=', 1)
        try:
            P[k] = json.loads(v)          # 数字、列表、带引号的字符串
        except ValueError:
            P[k] = v                      # 不带引号的字符串


@contextlib.contextmanager
def scoped(d):
    """临时把参数换成 d 里的值，离开 with 块时恢复"""
    if not d:
        yield; return
    old = {k: P[k] for k in d if k in P}; new = [k for k in d if k not in P]
    P.update(d)
    try:
        yield
    finally:
        P.update(old)
        for k in new: P.pop(k, None)


def for_encounter(enc):
    """这个遭遇的专属参数（没有就是空的）；P['use_encounter_params'] 为 false 时不用"""
    if not enc or not P.get('use_encounter_params', True): return {}
    return ENC.get(str(enc), {}).get('params', {})
