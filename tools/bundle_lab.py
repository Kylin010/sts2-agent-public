"""组合迭代。

每一代：
  1. 以当前最好配置为基准，随机生成 K 个「组合」：每个参数以一定概率换成候选里的另一个值（一次改很多个）；再加一个不改的对照。
  2. 所有组合跑同一批固定种子（开发种子前 N 个，和固定批训练同一批），合成一个任务清单只调用一次 dist（run.py --lab 的整局任务）。
  3. 打分：每局「走到多远」= (幕 − 1) × 17 + 层 + 10 ×（过了几幕）+ 40 × 赢；和对照同种子配对比较。
  4. 最好的组合比对照好（平均分高、且同种子更远的局数多于更近的）→ 成为新基准，写进 lab/bundle/best.json；下一代围绕它变异。
用法：python3 tools/bundle_lab.py --gens 10 --k 6 --seeds 30 [--p 0.4]
  只练第一幕：
  python3 tools/bundle_lab.py --stop-act 1 --seed-file lab/bundle/a1-seeds.txt --k 5 --p 0.35
  打完第一幕就停；打分 = 过关 100 + 剩余血量，没过 = 走到的层数；只影响后面几幕的参数不放进去变（避免为了第一幕牺牲第二幕的构筑）
记录：lab/bundle/LOG.md（每代每个组合改了什么、分数、配对比较），lab/bundle/best.json（当前最好配置）。
采用到正式默认值（params.json）由我确认后再做（tools/bundle_lab.py --apply）。
"""
import argparse, json, math, os, random, subprocess, sys, time
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = f'{HERE}/lab/bundle'; os.makedirs(OUT, exist_ok=True)

# 候选改动：参数 → 可选值（第一个是现在的默认值）
SPACE = {
    'potion_monster_need': [0.6, 0.8, 1.0],            # 普通战省药（只在这一下要掉很多 / 会死时喝）
    'potion_elite_need': [0.4, 0.3, 0.6],
    'ready_w': [0.0, 1.0, 2.0, 3.0],                    # 选牌准备度：输出不够时看重伤害牌
    'ready_aoe_bonus': [0.0, 0.5, 1.0],
    'simeval_upgrade': [False, True],                  # 篝火升级用模拟实打
    'simeval_samples': [2, 3, 4],                      # 10/3 色彩哲学家研究：2 样本时多一张从不打出的牌实打差 42 血——噪声大
    'simeval_next_w': [0.4, 0.25, 0.6],                # 选牌时「下一幕」的权重
    'simeval_prior_w': [0.5, 0.25, 1.0],               # 选牌时模型先验的权重
    'learn_skip_kinds': [['route'], [], ['route', 'rest']],   # 路线 / 篝火不用学到的偏好（按规则 + 实测掉血）
    'route_dmg_elite': [[25, 40, 55], [45, 55, 65], [32, 50, 60], [20, 35, 50]],   # 10/3 默认改成实测（开推演后第一幕精英掉 24~27，第二幕 35~42）
    'route_dmg_monster': [[12, 22, 32], [22, 30, 35], [16, 27, 33]],
    'route_death_cost': [400, 250, 600],
    'shop_card_min': [0.5, 0.0, 1.0],
    'shop_max_cards': [2, 1, 3],
    'br_terminal_pen': [0.0, 0.3],
    'br_trap_pen': [0.0, 0.3],
    'br_skip_a2': [0.0, 0.3],
    'upg_doc_bonus': [0.0, 0.2],
    'search_k': [5, 7],
    'lantern_fight_hp': [0.9, 1.01],
    # 10/3 第二批：休息 / 路线价值 / 选牌模拟 / 推演 / 喝药 / 战斗打法
    'heal_below': [0.55, 0.45, 0.65],
    'heal_below_before_boss': [0.75, 0.65, 0.85, 0.95],
    'route_rest_below': [0.55, 0.45, 0.65],
    'route_v_relic': [25, 35, 15, 50],
    'route_elite_bonus': [0, [40, 0, 0], [40, 20, 0], [40, 40, 0], [80, 40, 0]],   # 每幕分开：[第一幕, 第二幕, 第三幕]
    'route_v_shop': [15, 25, 8],
    'route_shop_cap': [3.0, 1.0, 2.0],                # 商店价值随金币涨（每 150 金一份，最多几份）；10/3 默认改 3
    'search_reserve': [True, False],                  # 推演方案打完后，没打的牌是否留着不打
    'search_empty_margin': [3.0, 1000.0, 1.0],        # 「什么都不打」当候选的门槛（1000 = 原来总是当候选）
    # 10/3 准备度分数制路线（血 + 牌 + 遗物 + 药水，够精英线就打精英，低于战斗线就躲战斗）
    'route_ready_elite': [[60, 65, 70], [55, 60, 65], [65, 70, 75]],
    'route_ready_monster': [[35, 40, 45], [30, 35, 40], [40, 45, 50]],
    'route_ready_bonus': [40, 20, 60],
    'route_ready_acts': [[1, 2, 3], [1], [1, 3]],
    'route_ready_pen': [15, 8, 25],
    'route_shop_min_gold': [50, 75],
    # 计分权重
    'route_w_hp': [40, 30, 50],
    'route_w_dmg': [25, 20, 32],
    'route_w_blk': [10, 6, 15],
    'route_w_relic': [1.25, 0.8, 2.0],
    'route_w_pot': [4, 2, 6],
    'route_w_multi_aoe': [15, 10, 25],
    'route_w_multi_dmg': [15, 10, 20],
    'route_w_single_scale': [5, 0, 10],
    'route_elite_matchup': [True, False],
    'ready_aoe_dyn': [0.6, 0.3, 1.0, 0.0],
    'combo_scale': [1.0, 0.5, 1.5],
    'combo_pick_w': [0.0, 1.0, 2.0],                  # 选牌时联动 / 核心成型加分（kb/combos.json）
    'core_w': [0.0, 0.5, 1.0, 2.0],                   # 输出核心规则（docs/输出核心研究.md 第五节，加在模拟之后）
    'deck_mc': [False, True],                         # 蒙特卡洛牌组强度（Codex 25 号）
    'boss_prep_w': [0.0, 1.0, 2.0],                   # 第二幕 Boss 备战选牌（高手录像研究 S1 / S2）
    'rest_learn_acts': [[1, 2, 3], [1], [1, 3]],       # 哪几幕篝火用学到的偏好（其余按规则，多升级）
    'potion_save_a2': [False, True],                  # 第二幕路上少喝药，留给 Boss（高手录像研究 D2）
    'ancient_wr_on': [False, True],                   # 古神按社区「选了之后的胜率」挑遗物
    'crab_facing_big_only': [True, False],
    'crab_hold_potions': [True, False],
    'disintegration_in': [True, False],
    'crab_kill_timing': [True, False],
    'route_hp_util_k': [0.0, 0.6],                    # 非线性血量价值（Codex 25 号）
    'core_complete_bonus': [0.6, 1.0],
    'crab_facing_w': [1.0, 0.0],                      # 帝皇蟹朝向（0 = 不管朝向）
    'kd_curse_smart': [False, True],                  # 知识恶魔按牌组选诅咒（10/3 单场：旧顺序 65% vs 按牌组 48%，默认关）
    'slumber_wake_pen': [8, 0, 16],                   # 熟睡甲虫：没打死却打穿格挡（早醒）的扣分
    'imbalanced_seq': [True, False],                  # 失衡：挡到「它和前面的来伤」就算晕（原来要全部挡满）
    'route_v_upgrade': [8, 12, 5],
    'route_v_card_elite': [6, 10, 3],
    'simeval_pick_scale': [5.0, 3.0, 8.0],
    'simeval_boss_w': [0.5, 0.3, 0.7, 0.85],
    'search_samples': [2, 3],
    'search_death': [60, 40, 90],
    'potion_boss_rounds': [2, 1, 3],
    'potion_heal_below': [0.4, 0.3, 0.5],
    'reward_skip_below': [0.28, 0.2, 0.36],
    'imit_w': [1.0, 0.5, 1.5],
    'self_hp_weight': [0.6, 0.4, 0.8],
    # 10/3 第三批：战斗估值（推演的展开也用规划器，所以这些同时影响出牌和推演）
    'use_encounter_params': [True, False],            # 按遭遇的专属参数是推演之前随机搜出来的，可能过时了
    'block_mult': [1.0, 1.2, 0.85],
    'kill_bonus': [6, 10, 3],
    'power_weight': [1.2, 1.5, 0.9],
    'self_hp_weight_low': [1.5, 2.0, 1.0],
    'search_future_weight': [1.0, 0.6, 1.5],
    'vuln_future': [2.0, 3.0, 1.0],
    'draw_value': [1.5, 2.0, 1.0],
}


LATER_ONLY = {'simeval_next_w', 'br_skip_a2'}             # 只练前几幕时不动这些（它们管的是后面几幕的准备）


def reach_stop(r):
    """只打到某一幕时的分：每过一幕 100；打完要求的幕再加剩余血量；死在半路加走到的层数
    （打到第二幕：死在第一幕 = 层数，过第一幕死在第二幕 = 100 + 层数，过第二幕 = 200 + 剩血）"""
    if r.get('cleared') or r.get('win'): return 100 * (r.get('cleared') or 1) + (r.get('hp') or 0)
    return 100 * ((r.get('act') or 1) - 1) + (r.get('floor') or 0)


def reach(r):
    act, fl = r.get('act') or 1, r.get('floor') or 0
    return (act - 1) * 17 + fl + 10 * (act - 1) + (40 if r.get('win') else 0)


def run_generation(tag, bundles, seeds, stop_act=0):
    """一代的所有组合放进同一个任务清单，只调用一次 dist（10/3：原来每个组合各开一次 dist，7 个同时跑，
    每个都按「只有自己」往机器上派进程，工作机 负载 176、交换区用满）。每个任务 = 一个种子 + 一组参数"""
    spec = f'lab/bundle/spec-{tag}.json'
    tasks = [{'seed': s, 'cand': name} for s in seeds for name, _, _ in bundles]
    random.Random(len(tasks)).shuffle(tasks)          # 10/3：不打乱的话 dist 按下标取模分份，组数和份数有公约数时每份只有一个组（各组跑的种子不同、先后不同）
    json.dump({'candidates': {name: cfg for name, cfg, _ in bundles}, 'tasks': tasks, 'stop_act': stop_act or None}, open(f'{HERE}/{spec}', 'w'), ensure_ascii=False)
    out = open(f'{OUT}/dist-{tag}.out', 'w')
    subprocess.run([sys.executable, 'dist.py', '0', '--lab', spec, '--tag', tag, '--set', 'search_on=true'], cwd=HERE, stdout=out, stderr=subprocess.STDOUT)
    p = f'{HERE}/results/{tag}.jsonl'
    rows = [json.loads(l) for l in open(p)] if os.path.exists(p) else []
    res = {name: [] for name, _, _ in bundles}
    for r in rows:
        t = tasks[r['task']] if isinstance(r.get('task'), int) else None
        if t: r.setdefault('cand', t['cand']); r['seed'] = t['seed']
        if r.get('cand') in res: res[r['cand']].append(r)
    return res


def sign_p(b, wo):
    """符号检验（单侧）：同种子更好 b 局、更差 wo 局，纯靠运气差这么多的概率"""
    n = b + wo
    return 1.0 if n == 0 else sum(math.comb(n, i) for i in range(b, n + 1)) / 2 ** n


def mutate(base, p, space=SPACE):
    cfg = dict(base); changed = {}
    for k, vals in space.items():
        if random.random() < p:
            alt = [v for v in vals if v != base.get(k, vals[0])]
            if alt:
                cfg[k] = random.choice(alt); changed[k] = cfg[k]
    if not changed:                                   # 至少改一个
        k = random.choice(list(space)); alt = [v for v in space[k] if v != base.get(k, space[k][0])]
        cfg[k] = random.choice(alt); changed[k] = cfg[k]
    return cfg, changed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--gens', type=int, default=10); ap.add_argument('--k', type=int, default=6)
    ap.add_argument('--seeds', type=int, default=30); ap.add_argument('--p', type=float, default=0.4)
    ap.add_argument('--stop-act', type=int, default=0, help='只打到第几幕（0 = 整局）')
    ap.add_argument('--seed-file', default=None, help='种子清单（默认开发种子前 --seeds 个）')
    ap.add_argument('--start-gen', type=int, default=0, help='从第几代接着跑（每代结束后自动用最新代码重启自己时用）')
    ap.add_argument('--extra', default=None, help='第一代额外加的固定组合（JSON：{名字: {参数: 值}}），用来干净地验证某个假设')
    ap.add_argument('--apply', action='store_true', help='把 best.json 写进 params.json')
    a = ap.parse_args()
    best_path = f'{OUT}/best.json' if not a.stop_act else f'{OUT}/best-a{a.stop_act}.json'
    space = {k: v for k, v in SPACE.items() if not (a.stop_act == 1 and k in LATER_ONLY)}
    score = reach_stop if a.stop_act else reach
    if a.apply:
        best = json.load(open(best_path))['cfg']
        P = json.load(open(f'{HERE}/params.json')); P.update(best)
        json.dump(P, open(f'{HERE}/params.json', 'w'), ensure_ascii=False, indent=2)
        print('已写入 params.json：', best); return
    dev = open(f'{HERE}/{a.seed_file}').read().split() if a.seed_file else open(f'{HERE}/data/dev_seeds.txt').read().split()[:a.seeds]
    sp_path = f'{HERE}/{a.seed_file[:-4]}-split.json' if a.seed_file else None
    split = json.load(open(sp_path)) if sp_path and os.path.exists(sp_path) else None    # 种子分组：之前输的（难）/ 之前过的（易）
    P = json.load(open(f'{HERE}/params.json'))
    base = json.load(open(best_path))['cfg'] if os.path.exists(best_path) else {k: P.get(k, v[0]) for k, v in space.items()}
    log = open(f'{OUT}/LOG.md', 'a')
    w = lambda s: (print(s, flush=True), log.write(s + '\n'), log.flush())
    fp = f'{OUT}/force.json'                          # 我改了默认值、要求新一代的基准也跟着改：写进这个文件（用过就改名）
    if os.path.exists(fp):
        try:
            fo = json.load(open(fp)); base.update(fo)
            json.dump({'cfg': base, 'gen': a.start_gen, 'note': 'force.json 改过', 'time': time.strftime('%m-%d %H:%M')}, open(best_path, 'w'), ensure_ascii=False, indent=1)
            w(f"  第 {a.start_gen + 1} 代开跑前按 force.json 改基准：{fo}")
        except Exception as e:
            w(f"  force.json 读不了：{e!r}")
        os.rename(fp, f"{OUT}/force-used-{time.strftime('%m%d%H%M')}.json")
    if not a.start_gen: w(f"\n## {time.strftime('%m-%d %H:%M')} 组合迭代开始{f'（只打到第 {a.stop_act} 幕）' if a.stop_act else ''}：每代 {a.k} 个组合 + 对照，"
      f"种子 {len(dev)} 个（{a.seed_file or '开发种子'}），候选参数 {len(space)} 个，每个参数改动概率 {a.p}")
    for g in range(a.start_gen, a.gens):
        t = time.time(); stamp = time.strftime('%H%M')
        inj = f'{OUT}/inject.json'                    # 中途想验证新假设：把 {名字: {参数: 值}} 写进这个文件，下一代开跑时加进去（用过就改名）
        injected = {}; k_this = a.k; noadopt = set()
        if os.path.exists(inj):
            try:
                injected = json.load(open(inj)); k_this = int(injected.pop('_k', a.k))   # '_k'：这一代随机组合几个（假设组多时少放随机的）
                noadopt = set(injected.pop('_noadopt', []))   # 只用来测量、不准采用的组（例如「推演泄漏（旧）」）
            except Exception as e:
                w(f"  inject.json 读不了：{e!r}")
            os.rename(inj, f'{OUT}/inject-used-g{g + 1}-{stamp}.json')
        bundles = [('对照', dict(base), {})] + [(f'组合{i + 1}',) + mutate(base, a.p, space) for i in range(k_this)]
        if g == 0 and a.extra:
            bundles += [(name, {**base, **ch}, ch) for name, ch in json.loads(a.extra).items()]
        bundles += [(name, {**base, **ch}, ch) for name, ch in injected.items()]
        w(f"- 第 {g + 1} 代开跑：{len(bundles)} 组 × {len(dev)} 个种子 = {len(bundles) * len(dev)} 局")
        res = run_generation(f'bdl{f"a{a.stop_act}" if a.stop_act else ""}-g{g + 1}-{stamp}', bundles, dev, a.stop_act)
        ctrl = {r['seed']: r for r in res.get('对照') or [] if 'crash' not in r}
        rows = []
        for name, cfg, ch in bundles:
            rs = {r['seed']: r for r in res.get(name) or [] if 'crash' not in r}
            com = [s for s in rs if s in ctrl]
            if not rs: continue
            sc = sum(score(r) for r in rs.values()) / len(rs)
            better = sum(1 for s in com if score(rs[s]) > score(ctrl[s])); worse = sum(1 for s in com if score(rs[s]) < score(ctrl[s]))
            a1 = sum(1 for r in rs.values() if r.get('win') or (r.get('act') or 1) >= 2); a2 = sum(1 for r in rs.values() if r.get('win') or (r.get('act') or 1) >= 3)
            wins = sum(bool(r.get('win')) for r in rs.values())
            rows.append((sc, name, cfg, ch, better, worse, a1, a2, wins, len(rs)))
            if a.stop_act:                                 # 只打到某一幕：赢 = 过关，另外看「难种子救回几个、易种子丢了几个」
                hp = [r.get('hp') or 0 for r in rs.values() if r.get('win')]
                extra = ''
                if split:                                  # 按种子分组（之前死在哪）看这一组的变化：每组「过第一幕 / 过第二幕」
                    def grp(seeds):
                        ss = [x for x in seeds if x in rs]
                        f1 = sum(1 for x in ss if rs[x].get('win') or (rs[x].get('act') or 1) >= 2)
                        return f"{f1}/{len(ss)}" + (f"、{sum(1 for x in ss if rs[x].get('win'))}" if a.stop_act >= 2 else '')
                    extra = '，分组 ' + '；'.join(f"{k} {grp(v)}" for k, v in split.items())
                prog = f"过第一幕 {a1}/{len(rs)}，过第二幕 {wins}" if a.stop_act >= 2 else f"过第 {a.stop_act} 幕 {wins}/{len(rs)}"
                w(f"- 第 {g + 1} 代 {name}：分 {sc:.1f}，{prog}{extra}，过关剩血平均 {sum(hp) / max(len(hp), 1):.0f}，"
                  f"同种子比对照 更好 {better} 更差 {worse}（运气概率 {sign_p(better, worse):.2f}）；改动 {ch}")
            else:
                w(f"- 第 {g + 1} 代 {name}：分 {sc:.1f}，过第一幕 {a1}/{len(rs)}，过第二幕 {a2}，赢 {wins}，同种子比对照 更远 {better} 更近 {worse}；改动 {ch}")
        c0 = next((r for r in rows if r[1] == '对照'), None)
        ok = lambda r: c0 and r[0] > c0[0] and r[4] > r[5] and sign_p(r[4], r[5]) <= P.get('bundle_sign_p', 0.2) \
            and (not a.stop_act or (r[8] >= c0[8] and r[6] >= c0[6]))   # 分更高、同种子明显更好（10/3：60 个种子噪声大，同配置过第一幕 48 vs 43）、每一幕过关数不少
        # 10/3 第四代：原来只看分最高的那个组，它不合格就不采用——「分数制只用第一幕」合格却被跳过。改成在合格的组里挑分最高的
        top = max((r for r in rows if not r[1].startswith('对照') and r[1] not in noadopt and ok(r)), key=lambda r: r[0], default=None)
        if top:
            base = top[2]
            json.dump({'cfg': base, 'gen': g + 1, 'score': top[0], 'ctrl': c0[0], 'time': time.strftime('%m-%d %H:%M')}, open(best_path, 'w'), ensure_ascii=False, indent=1)
            w(f"  **第 {g + 1} 代采用 {top[1]}**（{top[0]:.1f} vs 对照 {c0[0]:.1f}），{time.time() - t:.0f} 秒")
        else:
            w(f"  第 {g + 1} 代没有组合明显好过对照，基准不变（{time.time() - t:.0f} 秒）")
        # 每代结束用最新代码重启自己（候选参数、打分改了不用手动停）；基准存在 best 文件里，接得上
        argv = list(sys.argv)
        for flag in ('--start-gen', '--extra'):
            while flag in argv:
                i = argv.index(flag); del argv[i:i + 2]
        log.close()
        os.execv(sys.executable, [sys.executable] + argv + ['--start-gen', str(g + 1)])


if __name__ == '__main__':
    main()
