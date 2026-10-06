"""Crystal Sphere clicks from the visible fog mask and exposed fragments."""


def choose(state):
    """10/4：默认用 v2（policy/crystal_v2.py，后验采样补全露头的物品；research/水晶球事件.md）；v2 出错退回下面的铺地毯点法"""
    from params import P
    if P.get('crystal_v2', True):
        try:
            from policy import crystal_v2
            return crystal_v2.choose(state)
        except Exception as e:                     # 以后版本改了物品表等：退回旧点法，不让一局因此崩掉
            import sys
            print(f'[crystal_v2 退回旧点法] {e}', file=sys.stderr)
    return choose_v1(state)


def choose_v1(state):
    width, height = state.get('width'), state.get('height')
    if not isinstance(width, int) or not isinstance(height, int) or width <= 0 or height <= 0:
        raise ValueError('Missing visible crystal board dimensions')
    if state.get('divinations_left', 0) <= 0:
        raise ValueError('No remaining crystal divination')
    cells = {(c['x'], c['y']): c for c in state.get('cells') or []}
    if len(cells) != width * height or any((x, y) not in cells
            for x in range(width) for y in range(height)):
        raise ValueError('Incomplete visible crystal board')
    candidates = []
    for x in range(width):
        for y in range(height):
            covered = [cells[cx, cy] for cx in range(max(0, x-1), min(width, x+2))
                       for cy in range(max(0, y-1), min(height, y+2))]
            new = sum(bool(c.get('hidden')) for c in covered)
            # A visible fragment suggests the surrounding fog may cover the
            # rest of that item. Hidden cells carry no item information.
            fragments = sum(bool(c.get('visible_item')) for c in covered if not c.get('hidden'))
            center_distance = abs(x-(width-1)/2) + abs(y-(height-1)/2)
            candidates.append((new + 0.5*fragments, new, -center_distance, -y, -x, x, y))
    _, _, _, _, _, x, y = max(candidates)
    return 'crystal_click', {'x': x, 'y': y, 'tool': 'Big'}
