"""第二幕 Boss 研究 · 大样本：社区整局数据（ironclad-a10-v0.111.0.jsonl.gz，楼层级）里打帝皇蟹 / 知识恶魔的每一场。

录像里输的局太少（帝皇蟹 5 场、知识恶魔 8 场），「赢家 vs 输家」的进场状态用这里的大样本：
    进场血量、最大血量、牌组（core_data 正推，进 Boss 前）、遗物数、这场用了哪些药水、打了几回合、掉了多少血。
胜负：Boss 节点之后还有第三幕 = 赢；整局死在这个 Boss = 输；其余（放弃等）不算。
只用单人、非放弃、无修改器的局。
用法：from boss_runs import load_boss_runs；python3 boss_runs.py 打印样本数
缓存：BOSS_RUNS_CACHE（默认 /tmp/sts2-boss-runs.pkl）
"""
import gzip, json, os, sys, pickle, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import core_data

CACHE = os.environ.get('BOSS_RUNS_CACHE', '/tmp/sts2-boss-runs.pkl')
BOSSES = {'KAISER_CRAB_BOSS': 'crab', 'KNOWLEDGE_DEMON_BOSS': 'kd'}


def _build():
    out = []
    with gzip.open(core_data.SRC, 'rt') as f:
        for line in f:
            d = json.loads(line)
            if d.get('was_abandoned') or len(d.get('players') or []) != 1 or d.get('modifiers'): continue
            mph = d.get('map_point_history') or []
            if len(mph) < 2: continue
            boss_pt = next((p for p in mph[1] if p.get('map_point_type') == 'boss'), None)
            if boss_pt is None: continue
            enc = str(((boss_pt.get('rooms') or [{}])[0]).get('model_id') or '').replace('ENCOUNTER.', '')
            if enc not in BOSSES: continue
            r = core_data.parse(d, keep_points=True)
            if r['c2'] is None: continue
            kb = str(d.get('killed_by_encounter') or '').replace('ENCOUNTER.', '')
            if len(mph) >= 3: res = 'win'
            elif not d.get('win') and kb == enc: res = 'loss'
            else: continue
            pt = r['points'][r['c2_idx']]
            s = (boss_pt.get('player_stats') or [{}])[0]
            room = (boss_pt.get('rooms') or [{}])[0]
            out.append({'boss': BOSSES[enc], 'result': res, 'hp_in': pt['hp_in'], 'maxhp': pt['maxhp'], 'deck': r['c2'],
                        'relics': pt['relics'], 'dmg': s.get('damage_taken') or 0, 'turns': room.get('turns_taken'),
                        'pots_used': [str(p).replace('POTION.', '') for p in s.get('potion_used') or []],
                        'max_slots': (d['players'][0].get('max_potion_slot_count')), 'hash': d.get('run_hash'),
                        'elites_a2': r['elites_a2'], 'ups': pt['ups']})
    return out


def load_boss_runs(rebuild=False):
    if not rebuild and os.path.exists(CACHE) and os.path.getmtime(CACHE) > max(os.path.getmtime(core_data.SRC), os.path.getmtime(__file__)):
        with open(CACHE, 'rb') as fh: return pickle.load(fh)
    out = _build()
    with open(CACHE, 'wb') as fh: pickle.dump(out, fh, protocol=pickle.HIGHEST_PROTOCOL)
    return out


if __name__ == '__main__':
    rs = load_boss_runs(rebuild=True)
    print(collections.Counter((r['boss'], r['result']) for r in rs))
