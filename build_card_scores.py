# 从玩家对局算「选牌分」：奖励里出现这张牌时，赢家 / 高手拿它的比例（分幕）。在项目根目录运行：python3 agent/build_card_scores.py
# 原理：拿取率反映的是「做决定的那一刻」的判断，不受活得长短影响；高手（真实胜率 ≥60% 的 7 人）样本少，所以和赢家的拿取率加权合并。
import json, gzip, collections
cid = lambda x: (x.get('id') if isinstance(x, dict) else str(x)).replace('CARD.', '')
def picks(path, only_win):
    c = collections.defaultdict(lambda: [0, 0])          # (卡, 幕) -> [拿, 出现]
    skip = [0, 0]
    for line in gzip.open(path, 'rt'):
        d = json.loads(line)
        if d.get('modifiers') or (only_win and not d.get('win')): continue
        for a, act in enumerate(d.get('map_point_history') or []):
            for p in act:
                ch = ((p.get('player_stats') or [{}])[0]).get('card_choices') or []
                if not ch: continue
                skip[1] += 1; skip[0] += not any(x.get('was_picked') for x in ch)
                for x in ch:
                    k = (cid(x.get('card', {})), min(a + 1, 3)); c[k][1] += 1; c[k][0] += bool(x.get('was_picked'))
    return c, skip
W, ws = picks('sources/community-runs/ironclad-a10-v0.111.0.jsonl.gz', True)
E, es = picks('sources/community-runs/elite-top7-all.jsonl.gz', False)
out = {}
for (card, act), (w, n) in W.items():
    e, m = E.get((card, act), [0, 0])
    # 赢家的拿取率当先验，高手的样本按 3 倍权重加进去（贝叶斯式加权平均）
    score = (w + 3 * e + 1) / (n + 3 * m + 2)
    out.setdefault(card, {})[str(act)] = {'score': round(score, 3), 'n_win': n, 'n_elite': m}
json.dump(out, open('agent/data/card_scores.json', 'w'), ensure_ascii=False, indent=1)
print(f'赢家跳过率 {ws[0]/ws[1]:.0%}，高手跳过率 {es[0]/es[1]:.0%}；{len(out)} 张牌')
top = sorted(((v['1']['score'], k) for k, v in out.items() if '1' in v and v['1']['n_win'] >= 30), reverse=True)
print('第一幕最高分：', top[:15]); print('第一幕最低分：', top[-10:])

# 涅奥（开局）选项：选了它的局最终胜率（贝叶斯平滑，先验 = 整体胜率 21%，权重 50 局）
neow = collections.defaultdict(lambda: [0, 0])
for line in gzip.open('sources/community-runs/ironclad-a10-v0.111.0.jsonl.gz', 'rt'):
    d = json.loads(line)
    if d.get('modifiers'): continue
    pts = (d.get('map_point_history') or [[]])[0]
    for ch in (((pts[0].get('player_stats') or [{}])[0].get('ancient_choice') or []) if pts else []):
        if ch.get('was_chosen'):
            k = ch.get('TextKey'); neow[k][0] += bool(d.get('win')); neow[k][1] += 1
base = 0.205
ns = {k: {'score': round((w + 50 * base) / (n + 50), 3), 'n': n} for k, (w, n) in neow.items()}
json.dump(ns, open('agent/data/neow_scores.json', 'w'), indent=1)
print('涅奥：', sorted(((v['score'], k) for k, v in ns.items()), reverse=True)[:8])
