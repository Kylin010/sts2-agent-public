# 每个遭遇的「人类掉血基准」：测试版铁甲战士进阶 10 玩家对局里，赢家 / 全部玩家每场平均掉多少血。
# 用英文怪物名组合当键，和引擎状态里的敌人名字对上。在项目根目录运行：python3 agent/build_baselines.py
import json, gzip, collections
ENC = json.load(open('sources/spire-codex/data-beta/v0.111.0/eng/encounters.json'))
ZH = {e['id']: e['name'] for e in json.load(open('sources/spire-codex/data-beta/v0.111.0/zhs/encounters.json'))}
key_of = {e['id']: ' + '.join(sorted({m['name'] for m in e.get('monsters') or []})) for e in ENC}
S = collections.defaultdict(lambda: {'w': [], 'a': []})
for line in gzip.open('sources/community-runs/ironclad-a10-v0.111.0.jsonl.gz', 'rt'):
    d = json.loads(line)
    if d.get('modifiers'): continue
    for a, act in enumerate(d.get('map_point_history') or []):
        for p in act:
            rm = (p.get('rooms') or [{}])[0]
            if rm.get('room_type') not in ('monster', 'elite', 'boss'): continue
            k = str(rm.get('model_id', '')).replace('ENCOUNTER.', '')
            dm = ((p.get('player_stats') or [{}])[0]).get('damage_taken', 0)
            S[k]['a'].append(dm)
            if d.get('win'): S[k]['w'].append(dm)
out = {}
for k, v in S.items():
    if len(v['a']) < 20: continue
    out[k] = {'zh': ZH.get(k, k), 'names': key_of.get(k, ''), 'win_avg': round(sum(v['w']) / max(len(v['w']), 1), 1),
              'all_avg': round(sum(v['a']) / len(v['a']), 1), 'n_win': len(v['w'])}
json.dump(out, open('agent/data/baselines.json', 'w'), ensure_ascii=False, indent=1)
print(len(out), '个遭遇；例：', list(out.items())[:2])
