"""好坏一起比：每个遭遇，人类赢家 / 人类输家 / 我们 的平均掉血和死亡率。
用法：python3 tools/goodbad.py results/xxx.jsonl [更多结果文件]；人类数据 = 社区 v0.111.0 铁甲 A10（sources/community-runs/ironclad-a10-v0.111.0.jsonl.gz）"""
import gzip, json, collections, sys
sys.path.insert(0, '/opt/slay-the-spire-2/agent')
import run
H = collections.defaultdict(lambda: {'w': [], 'l': [], 'wd': 0, 'ld': 0})
for l in gzip.open('/opt/slay-the-spire-2/sources/community-runs/ironclad-a10-v0.111.0.jsonl.gz', 'rt'):
    r = json.loads(l); win = bool(r.get('win')); kb = str(r.get('killed_by_encounter') or '').replace('ENCOUNTER.', '')
    pts = [p for act in r.get('map_point_history') or [] for p in act]
    for i, p in enumerate(pts):
        for rm in p.get('rooms') or []:
            enc = str(rm.get('model_id') or '')
            if not enc.startswith('ENCOUNTER.'): continue
            enc = enc[10:]; ps = (p.get('player_stats') or [{}])[0]
            died = (not win) and i == len(pts) - 1 and kb == enc
            d = ps.get('damage_taken') or 0
            (H[enc]['w'] if win else H[enc]['l']).append(d)
            if died: H[enc]['ld'] += 1
O = collections.defaultdict(lambda: {'d': [], 'dead': 0})
for f in sys.argv[1:]:
    for l in open(f):
        r = json.loads(l); cs = r.get('combats') or []
        for i, c in enumerate(cs):
            k = run.match_baseline(c)
            if not k: continue
            died = (not r.get('win')) and i == len(cs) - 1 and r.get('room') == c.get('room')
            O[k]['d'].append(c.get('dmg') or 0); O[k]['dead'] += died
avg = lambda x: sum(x) / len(x) if x else float('nan')
rows = []
for k, o in O.items():
    h = H.get(k)
    if not h or len(h['w']) < 20: continue
    hw, hl, us = avg(h['w']), avg(h['l']), avg(o['d'])
    pos = (us - hw) / (hl - hw) if hl != hw else float('nan')      # 0 = 像赢家，1 = 像输家
    rows.append((len(o['d']) * (us - hw), k, len(o['d']), us, o['dead'] / len(o['d']), hw, hl, h['ld'] / max(1, len(h['l'])), pos, len(h['w']), len(h['l'])))
rows.sort(reverse=True)
print(f"{'遭遇':34s} {'我们场':>5s} {'我们掉血':>7s} {'我们死':>6s} | {'人类赢家':>7s} {'人类输家':>7s} {'输家死':>6s} | 位置(0赢家 1输家) | 我们比赢家多掉血合计")
for tot, k, n, us, ud, hw, hl, hld, pos, nw, nl in rows[:25]:
    print(f"{k:34s} {n:5d} {us:7.1f} {ud:6.1%} | {hw:7.1f} {hl:7.1f} {hld:6.1%} | {pos:5.2f} | {tot:7.0f}")
print('…… 我们比人类赢家掉得少的：')
for tot, k, n, us, ud, hw, hl, hld, pos, nw, nl in rows[-6:]:
    print(f"{k:34s} {n:5d} {us:7.1f} {ud:6.1%} | {hw:7.1f} {hl:7.1f} {hld:6.1%} | {pos:5.2f} | {tot:7.0f}")
