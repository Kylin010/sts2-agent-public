"""商店体检（10/3，claude-value，B-010 同类问题的非战斗流程审计）：每个种子直接进商店，把每件商品各买一次，核对
「扣钱 = 标价」「东西到手」「买完标成售出」；买完还在架上就再买一次，看能不能重复拿。另外抓引擎日志里的异常。

源码里的顺序（decompiled/v0.111.0/MegaCrit.Sts2.Core.Entities.Merchant）：
  药水 = 先 PotionCmd.TryToProcure（进药水栏）再 LoseGold；卡牌 = 先 CardPileCmd.Add 再 LoseGold；遗物 = 先 LoseGold 再 RelicCmd.Obtain；
  MerchantEntry.OnTryPurchaseWrapper 在 OnTryPurchase 成功返回后才 ClearAfterPurchase（标售出）。
  所以「给了东西之后、扣钱 / 标售出之前」抛异常 = 白拿而且还能再买。引擎 DoBuyPotion 把异常吞掉（注释：后台模式下买药水有时空引用），
  DoBuyRelic / DoRemoveCard 在后台线程上跑购买、推进约 1 秒后 task.Wait(2000) 干等，和 B-010 同一种写法。

用法：python3 tools/shop_audit.py <sts2-cli 目录（已编译）> [种子数，默认 30] [输出 json]
"""
import json, subprocess, sys, threading, time
CLI = sys.argv[1]; N = int(sys.argv[2]) if len(sys.argv) > 2 else 30; OUT = sys.argv[3] if len(sys.argv) > 3 else None
DLL = f'{CLI}/src/Sts2Headless/bin/Debug/net9.0/Sts2Headless.dll'
p = subprocess.Popen(['/opt/dotnet9/dotnet', DLL], cwd=CLI, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
err = []
threading.Thread(target=lambda: [err.append(l.rstrip()) for l in p.stderr], daemon=True).start()


def send(c):
    p.stdin.write(json.dumps(c) + '\n'); p.stdin.flush()
    while True:
        l = p.stdout.readline()
        if not l: raise RuntimeError('引擎退出')
        l = l.strip()
        if l.startswith('{'):
            try: return json.loads(l)
            except Exception: pass


while True:
    l = p.stdout.readline().strip()
    if l.startswith('{') and '"ready"' in l: break


def act(a, **k): return send({'cmd': 'action', 'action': a, **({'args': k} if k else {})})


def pl(st): return st.get('player') or {}
def n_pot(st): return sum(1 for x in pl(st).get('potions') or [] if x and (x.get('id') or x.get('name')))
def n_deck(st): return len(pl(st).get('deck') or [])
def n_rel(st): return len(pl(st).get('relics') or [])


def finish(st, path):
    """购买途中弹出的选牌 / 选包 / 奖励：选第一个，直到回到商店"""
    for _ in range(6):
        d = st.get('decision')
        if d == 'card_select': st = act('select_cards', indices='0')
        elif d == 'bundle_select': st = act('select_bundle', bundle_index=0)
        elif d == 'card_reward': st = act('skip_card_reward')
        else: break
        path.append(d)
    return st


def entry(st, kind, idx):
    return next((x for x in st.get({'card': 'cards', 'relic': 'relics', 'potion': 'potions'}[kind]) or [] if x.get('index') == idx), None)


res = []
for k in range(1, N + 1):
    send({'cmd': 'start_run', 'character': 'Ironclad', 'ascension': 10, 'seed': f'SHOP{k:04d}'})
    send({'cmd': 'set_player', 'hp': 60, 'max_hp': 80, 'gold': 3000, 'potions': []})
    st = send({'cmd': 'enter_room', 'type': 'shop'})
    if st.get('decision') != 'shop':
        res.append({'seed': k, 'note': f"进不去：{st.get('decision')} {str(st.get('message'))[:80]}"}); continue
    items = [('potion', x['index']) for x in st.get('potions') or []] + [('card', x['index']) for x in st.get('cards') or []] \
        + [('relic', x['index']) for x in st.get('relics') or []]
    for kind, idx in items:
        # 每件商品前把金币设回 3000（已知起点）；药水前清空药水栏，避免「栏满买不了」。set_player 不改牌组和遗物，
        # 所以牌组张数、遗物数沿用上一次购买回传的商店局面
        send({'cmd': 'set_player', 'gold': 3000, **({'potions': []} if kind == 'potion' else {})})
        e0 = len(err)
        g0, p0, d0, r0 = 3000, (0 if kind == 'potion' else n_pot(st)), n_deck(st), n_rel(st)
        ent = entry(st, kind, idx) if kind != 'remove' else None
        cost = (ent or {}).get('cost') if kind != 'remove' else st.get('card_removal_cost')
        if kind != 'remove' and (not ent or not ent.get('is_stocked', True)):
            continue
        args = {f'{kind}_index': idx} if kind != 'remove' else {}
        action = {'potion': 'buy_potion', 'card': 'buy_card', 'relic': 'buy_relic', 'remove': 'remove_card'}[kind]
        path = []
        st1 = act(action, **args)
        resp_err = st1.get('message') if st1.get('type') == 'error' else None
        st1 = finish(st1, path)
        time.sleep(0.2)
        g1 = pl(st1).get('gold', g0)
        got = {'potion': n_pot(st1) - p0, 'card': n_deck(st1) - d0, 'relic': n_rel(st1) - r0, 'remove': d0 - n_deck(st1)}[kind]
        ent1 = entry(st1, kind, idx) if kind != 'remove' else None
        still = bool(ent1 and ent1.get('is_stocked', True)) if kind != 'remove' else bool(st1.get('card_removal_cost'))
        faults = [x for x in err[e0:] if 'Exception' in x or 'faulted' in x or 'NullReference' in x]
        r = {'seed': k, 'kind': kind, 'idx': idx, 'id': (ent or {}).get('id'), 'cost': cost, 'gold_spent': g0 - g1, 'got': got,
             'still_stocked': still, 'resp_error': resp_err, 'path': path, 'fault': faults[0][:200] if faults else None,
             'decision_after': st1.get('decision')}
        if got > 0 and still and kind != 'remove':             # 到手了还在架上：再买一次
            st2 = finish(act(action, **args), [])
            r['rebuy_got'] = {'potion': n_pot(st2) - n_pot(st1), 'card': n_deck(st2) - n_deck(st1), 'relic': n_rel(st2) - n_rel(st1)}[kind]
            r['rebuy_spent'] = pl(st1).get('gold', 0) - pl(st2).get('gold', 0)
            st1 = st2
        flag = (r['got'] > 0 and r['gold_spent'] < (cost or 0)) or (r['got'] > 0 and still and kind != 'remove') or (r['got'] <= 0 and r['gold_spent'] > 0) or r['fault']
        if flag: print(k, kind, r['id'], '花', r['gold_spent'], '/', cost, '到手', r['got'], '仍在架上' if still else '', r.get('rebuy_got', ''), (r['fault'] or '')[:80], flush=True)
        res.append(r)
        st = st1
    # 删牌：同一个商店连删两次（原版每店只能删一次：删完由商店界面 NMerchantCardRemoval.OnCardRemovalUsed → SetUsed 标「用过」，
    # 后台没有界面，NRun.Instance?. 直接跳过，Used 永远是 false）
    send({'cmd': 'set_player', 'gold': 3000})
    rm = []
    for _ in range(2):
        s1 = act('remove_card')
        if s1.get('decision') != 'card_select':
            rm.append(None); break
        s1 = act('select_cards', indices='0')
        rm.append((n_deck(s1), pl(s1).get('gold'), s1.get('card_removal_cost')))
    res.append({'seed': k, 'kind': 'remove_twice', 'ok_second': len(rm) == 2 and rm[1] is not None, 'detail': rm})
send({'cmd': 'quit'})
done = [r for r in res if 'kind' in r and r['kind'] != 'remove_twice']
def cnt(f): return sum(1 for r in done if f(r))
print(f'种子 {N}，购买 {len(done)} 次（药水 {cnt(lambda r: r["kind"] == "potion")} 卡牌 {cnt(lambda r: r["kind"] == "card")} 遗物 {cnt(lambda r: r["kind"] == "relic")}）；'
      f'同店第二次删牌成功 {sum(1 for r in res if r.get("kind") == "remove_twice" and r.get("ok_second"))} / {sum(1 for r in res if r.get("kind") == "remove_twice")} 个商店')
print(f'  到手但少扣钱 {cnt(lambda r: r["got"] > 0 and r["gold_spent"] < (r["cost"] or 0))}；到手后仍在架上 {cnt(lambda r: r["got"] > 0 and r["still_stocked"] and r["kind"] != "remove")}；'
      f'能重复买 {cnt(lambda r: (r.get("rebuy_got") or 0) > 0)}；扣钱没到手 {cnt(lambda r: r["got"] <= 0 and r["gold_spent"] > 0)}；引擎异常 {cnt(lambda r: r["fault"])}；进不去 {sum(1 for r in res if "note" in r)}')
if OUT: json.dump(res, open(OUT, 'w'), ensure_ascii=False, indent=0)
