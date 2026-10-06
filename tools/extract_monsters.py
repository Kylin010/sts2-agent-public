#!/usr/bin/env python3
"""从《杀戮尖塔2》v0.111.0 反编译源码提取全部怪物 / 遭遇数据，输出给自动打牌程序用。

用法:
    python3 tools/extract_monsters.py            # 生成 kb/monsters.json 和 kb/encounters_src.json
    python3 tools/extract_monsters.py --check    # 只解析并打印统计，不写文件
    python3 tools/extract_monsters.py --out DIR  # 输出到别的目录（调试用）

只用标准库：正则 + 一个很小的 C# 语句遍历器 + 用 Python ast 求值的表达式求值器。
解析不了的地方用 kb/overrides/monsters_manual.json 手工补（深度合并，手工值优先）。
说明文档见 kb/README_monsters.md。
"""
import ast
import copy
import json
import os
import re
import sys

ROOT = '/opt/slay-the-spire-2'
SRC = f'{ROOT}/decompiled/v0.111.0'
MON_DIR = f'{SRC}/MegaCrit.Sts2.Core.Models.Monsters'
ENC_DIR = f'{SRC}/MegaCrit.Sts2.Core.Models.Encounters'
ACT_DIR = f'{SRC}/MegaCrit.Sts2.Core.Models.Acts'
POW_DIR = f'{SRC}/MegaCrit.Sts2.Core.Models.Powers'
CARD_DIR = f'{SRC}/MegaCrit.Sts2.Core.Models.Cards'
ASC_ENUM = f'{SRC}/MegaCrit.Sts2.Core.Entities.Ascension/AscensionLevel.cs'
MODELDB = f'{SRC}/MegaCrit.Sts2.Core.Models/ModelDb.cs'
LOC_ZH = f'{ROOT}/sources/github/wuhao21_sts2-cli/localization_zhs'
LOC_EN = f'{ROOT}/sources/github/wuhao21_sts2-cli/localization_eng'
KB = f'{ROOT}/agent/kb'
OUT_MON = f'{KB}/monsters.json'
OUT_ENC = f'{KB}/encounters_src.json'
OVERRIDE = f'{KB}/overrides/monsters_manual.json'

GAME_VERSION = 'v0.111.0'
ASC_LEVELS = (0, 10)          # 输出 a0 / a10 两套
ACT_NUMBER = {'Overgrowth': 1, 'Underdocks': 1, 'Hive': 2, 'Glory': 3}
TEST_MONSTERS = {'BigDummy', 'OneHpMonster', 'TenHpMonster', 'SingleAttackMoveMonster',
                 'MultiAttackMoveMonster', 'DeprecatedMonster'}
PET_MONSTERS = {'Osty', 'Byrdpip', 'PaelsLegion'}

INTENT_TYPES = {
    'SingleAttackIntent': ('attack', 'Attack'),
    'MultiAttackIntent': ('attack', 'Attack'),
    'DeathBlowIntent': ('death_blow', 'DeathBlow'),
    'BuffIntent': ('buff', 'Buff'),
    'DebuffIntent': ('debuff', 'Debuff'),
    'DefendIntent': ('defend', 'Defend'),
    'EscapeIntent': ('escape', 'Escape'),
    'HealIntent': ('heal', 'Heal'),
    'HiddenIntent': ('hidden', 'Hidden'),
    'SummonIntent': ('summon', 'Summon'),
    'SleepIntent': ('sleep', 'Sleep'),
    'StunIntent': ('stun', 'Stun'),
    'StatusIntent': ('status', 'StatusCard'),
    'CardDebuffIntent': ('card_debuff', 'CardDebuff'),
    'UnknownIntent': ('unknown', 'Unknown'),
}

# 和战斗无关、只影响画面/音效的条件，抽效果时丢掉
NOISE_COND = re.compile(r'IsLiveCombat|TestMode|[Nn]ode|LocalContext|Vfx|vfx|marker|GlobalPosition|IsMe\b|'
                        r'Instance\b|IsMine|nCreature|speech|SpeechUsed|_hasSpoken|IsGameOver|locString|'
                        r'enumerator|IsOverOrEnding|IsNullOrEmpty|text != null|IsDead|enumerable\.Any|_curseOfKnowledgeSets|'
                        r'^flag$|HpDisplay')


# --------------------------------------------------------------------------- 通用文本工具

def slug(name):
    """C# 类名 -> 游戏 Id.Entry（StringHelper.Slugify 的等价实现）。"""
    return re.sub(r'(?<=[A-Za-z0-9])([A-Z])', r'_\1', name.strip()).upper()


def read(path):
    with open(path, encoding='utf-8') as f:
        return f.read()


def strip_comments(s):
    out = []
    for line in s.split('\n'):
        t = line.strip()
        if t.startswith('//'):
            continue
        out.append(line)
    return '\n'.join(out)


def match_bracket(s, i, open_ch='(', close_ch=')'):
    """s[i] == open_ch，返回配对 close_ch 的下标（跳过字符串）。"""
    depth = 0
    k = i
    n = len(s)
    while k < n:
        c = s[k]
        if c == '"':
            k += 1
            while k < n and s[k] != '"':
                if s[k] == '\\':
                    k += 1
                k += 1
        elif c == "'":
            k += 1
            while k < n and s[k] != "'":
                if s[k] == '\\':
                    k += 1
                k += 1
        elif c == open_ch:
            depth += 1
        elif c == close_ch:
            depth -= 1
            if depth == 0:
                return k
        k += 1
    return -1


def split_args(s):
    """按顶层逗号切分参数（只数 () [] {}，不数尖括号，避免把 < 比较号当泛型）。"""
    args, depth, cur, k = [], 0, [], 0
    while k < len(s):
        c = s[k]
        if c == '"':
            j = k + 1
            while j < len(s) and s[j] != '"':
                if s[j] == '\\':
                    j += 1
                j += 1
            cur.append(s[k:j + 1])
            k = j + 1
            continue
        if c in '([{':
            depth += 1
        elif c in ')]}':
            depth -= 1
        if c == ',' and depth == 0:
            args.append(''.join(cur).strip())
            cur = []
        else:
            cur.append(c)
        k += 1
    if ''.join(cur).strip():
        args.append(''.join(cur).strip())
    return args


def call_args(text, start):
    """text[start] 是 '('，返回 (参数列表, 右括号下标)。"""
    end = match_bracket(text, start)
    return split_args(text[start + 1:end]), end


def norm_ws(s):
    return re.sub(r'\s+', ' ', s).strip()


def strip_lambda(s):
    s = s.strip()
    m = re.match(r'^\(\s*\)\s*=>\s*(.*)$', s, re.S)
    if m:
        return m.group(1).strip()
    m = re.match(r'^\([^()]*\)\s*=>\s*(.*)$', s, re.S)
    if m:
        return m.group(1).strip()
    return s


def strip_bbcode(s):
    return re.sub(r'\[/?[a-zA-Z_]+(?:=[^\]]*)?\]', '', s or '')


# --------------------------------------------------------------------------- C# 语句遍历器

BLOCK_KW = re.compile(r'^(?:else\s+if\b|if\b|else\b|for\b|foreach\b|while\b|switch\b|using\b|do\b|try\b|catch\b|finally\b|lock\b)')


def walk_statements(body):
    """遍历方法体（不含最外层花括号）。
    返回 [(语句文本, 条件列表, 循环列表)]。条件里 else 写成 !(原条件)，
    if 块里有 return 时，同层后续语句自动带上 !(该条件)。"""
    results = []
    frames = [{'kind': 'root', 'header': '', 'sticky': [], 'has_return': False, 'case': None}]
    last_if = {}          # 帧深度 -> 上一个刚关闭的 if 条件链
    buf = []
    paren = 0
    ebrace = 0             # 表达式级别的花括号（对象初始化器、switch 表达式、lambda 体）
    k, n = 0, len(body)

    def cur_conds():
        conds, loops = [], []
        for fr in frames:
            conds.extend(fr['sticky'])
            if fr['kind'] == 'if':
                conds.append(fr['cond'])
            elif fr['kind'] == 'switch' and fr.get('case') is not None:
                conds.append(f"{fr['subject']} == {fr['case']}")
            elif fr['kind'] == 'loop':
                loops.append(fr['header'])
        return conds, loops

    def emit(text):
        t = text.strip()
        if not t:
            return
        m = re.match(r'^(case\s+[^:]+|default)\s*:\s*(.*)$', t, re.S)
        if m and frames[-1]['kind'] == 'switch':
            lab = m.group(1)
            frames[-1]['case'] = lab[4:].strip() if lab.startswith('case') else 'default'
            t = m.group(2).strip()
            if not t:
                return
        if re.match(r'^return\b', t) or t == 'break' or re.match(r'^throw\b', t):
            for fr in reversed(frames):
                if fr['kind'] == 'if':
                    fr['has_return'] = True
                    break
        conds, loops = cur_conds()
        results.append((t, conds, loops))

    while k < n:
        c = body[k]
        if c == '"':
            j = k + 1
            while j < n and body[j] != '"':
                if body[j] == '\\':
                    j += 1
                j += 1
            buf.append(body[k:j + 1])
            k = j + 1
            continue
        if c == "'":
            j = k + 1
            while j < n and body[j] != "'":
                if body[j] == '\\':
                    j += 1
                j += 1
            buf.append(body[k:j + 1])
            k = j + 1
            continue
        if c == '(':
            paren += 1
        elif c == ')':
            paren -= 1
        if c == '{' and paren == 0 and ebrace == 0:
            header = norm_ws(''.join(buf))
            if BLOCK_KW.match(header) or header == '':
                buf = []
                depth = len(frames)
                if header.startswith('else if'):
                    cond = header[len('else if'):].strip()
                    cond = cond[1:-1].strip() if cond.startswith('(') and cond.endswith(')') else cond
                    prev = last_if.get(depth, [])
                    neg = [f'!({p})' for p in prev]
                    frames.append({'kind': 'if', 'cond': ' && '.join(neg + [cond]) if neg else cond,
                                   'chain': prev + [cond], 'sticky': [], 'has_return': False, 'header': header})
                elif header.startswith('if'):
                    cond = header[2:].strip()
                    cond = cond[1:-1].strip() if cond.startswith('(') and cond.endswith(')') else cond
                    frames.append({'kind': 'if', 'cond': cond, 'chain': [cond], 'sticky': [],
                                   'has_return': False, 'header': header})
                elif header.startswith('else'):
                    prev = last_if.get(depth, [])
                    cond = ' && '.join(f'!({p})' for p in prev) if prev else 'else'
                    frames.append({'kind': 'if', 'cond': cond, 'chain': None, 'sticky': [],
                                   'has_return': False, 'header': header})
                elif header.startswith(('for', 'foreach', 'while', 'do')):
                    frames.append({'kind': 'loop', 'header': header, 'sticky': [], 'has_return': False})
                elif header.startswith('switch'):
                    subj = header[6:].strip()
                    subj = subj[1:-1].strip() if subj.startswith('(') and subj.endswith(')') else subj
                    frames.append({'kind': 'switch', 'subject': subj, 'case': None, 'sticky': [],
                                   'has_return': False, 'header': header})
                else:
                    frames.append({'kind': 'block', 'header': header, 'sticky': [], 'has_return': False})
                k += 1
                continue
            ebrace += 1
            buf.append(c)
            k += 1
            continue
        if c == '}' and paren == 0:
            if ebrace > 0:
                ebrace -= 1
                buf.append(c)
                k += 1
                continue
            # 块结束
            if ''.join(buf).strip():
                emit(''.join(buf))
            buf = []
            if len(frames) > 1:
                fr = frames.pop()
                depth = len(frames)
                if fr['kind'] == 'if':
                    if fr.get('chain') is not None:
                        last_if[depth] = fr['chain']
                    else:
                        last_if.pop(depth, None)
                    # if 块里 return 了 → 同层后续语句只有在 !(cond) 时才会执行
                    if fr['has_return'] and fr.get('chain') is not None:
                        frames[-1]['sticky'].append(f"!({fr['cond']})")
                else:
                    last_if.pop(depth, None)
            k += 1
            continue
        if c == ';' and paren == 0 and ebrace == 0:
            emit(''.join(buf))
            buf = []
            k += 1
            continue
        buf.append(c)
        k += 1
    if ''.join(buf).strip():
        emit(''.join(buf))
    return results


# --------------------------------------------------------------------------- 类解析

MOD = r'(?:(?:public|private|protected|internal|static|override|virtual|sealed|new|readonly|abstract|const|async)\s+)'


class CsClass:
    def __init__(self, path):
        self.path = path
        self.file = os.path.basename(path)
        raw = strip_comments(read(path))
        self.raw = raw
        m = re.search(r'public\s+(?:sealed\s+|abstract\s+)?class\s+(\w+)\s*(?::\s*(\w+))?', raw)
        self.name = m.group(1)
        self.base = m.group(2)
        self.abstract = bool(re.search(r'public\s+abstract\s+class', raw))
        i = raw.find('{', m.end())
        j = match_bracket(raw, i, '{', '}')
        self.body = raw[i + 1:j]
        self.props = {}      # name -> {'type','expr' 或 'getter'}
        self.fields = {}     # name -> {'type','init','const'}
        self.methods = {}    # name -> {'sig','params','body','override'}
        self._parse_members()

    def _parse_members(self):
        b = self.body
        # 方法
        for m in re.finditer(r'^[ \t]*' + MOD + r'+([\w<>\[\]?,.]+)\s+(\w+)\s*\(([^)]*)\)\s*\n\s*\{', b, re.M):
            name = m.group(2)
            if name in ('if', 'for', 'foreach', 'while', 'switch'):
                continue
            ob = b.find('{', m.end() - 1)
            cb = match_bracket(b, ob, '{', '}')
            self.methods[name] = {'ret': m.group(1), 'params': m.group(3), 'body': b[ob + 1:cb],
                                  'override': 'override' in m.group(0), 'sig': norm_ws(m.group(0)[:-1])}
        # 表达式体属性
        for m in re.finditer(r'^[ \t]*' + MOD + r'+([\w<>\[\]?,.]+)\s+(\w+)\s*=>\s*(.*?);[ \t]*$', b, re.M):
            self.props[m.group(2)] = {'type': m.group(1), 'expr': m.group(3).strip()}
        # get 块属性
        for m in re.finditer(r'^[ \t]*' + MOD + r'+([\w<>\[\]?,.]+)\s+(\w+)\s*\n\s*\{\s*\n\s*get\s*\n\s*\{', b, re.M):
            ob = b.rfind('{', 0, m.end())
            cb = match_bracket(b, ob, '{', '}')
            self.props.setdefault(m.group(2), {'type': m.group(1), 'getter': b[ob + 1:cb]})
        # 字段
        for m in re.finditer(r'^[ \t]*' + MOD + r'+([\w<>\[\]?,.]+)\s+(_?\w+)\s*(?:=\s*(.*?))?;[ \t]*$', b, re.M):
            if '=>' in m.group(0) or '(' in m.group(2):
                continue
            name = m.group(2)
            if name in self.props or name in self.methods:
                continue
            head = ' ' + m.group(0).split('=')[0] + ' '
            self.fields[name] = {'type': m.group(1), 'init': m.group(3), 'const': ' const ' in head,
                                 'readonly': ' readonly ' in head}


def load_classes(d):
    out = {}
    for f in sorted(os.listdir(d)):
        if f.endswith('.cs'):
            c = CsClass(os.path.join(d, f))
            out[c.name] = c
    return out


class Merged:
    """把继承链（子类覆盖父类）合并成一个视图。"""

    def __init__(self, cls, all_classes):
        chain = [cls]
        while chain[-1].base in all_classes:
            chain.append(all_classes[chain[-1].base])
        self.chain = chain
        self.cls = cls
        self.name = cls.name
        self.props, self.fields, self.methods = {}, {}, {}
        for c in reversed(chain):
            self.props.update(c.props)
            self.fields.update(c.fields)
            self.methods.update(c.methods)

    def parent_method(self, name):
        for c in self.chain[1:]:
            if name in c.methods:
                return c.methods[name]
        return None


# --------------------------------------------------------------------------- 表达式求值

class Unresolved(Exception):
    pass


ASC_LEVEL = {}


def load_asc_levels():
    s = read(ASC_ENUM)
    body = s[s.find('{') + 1:s.rfind('}')]
    names = [x.strip() for x in body.split(',') if x.strip()]
    for i, nm in enumerate(names):
        ASC_LEVEL[nm] = i


def to_py(expr):
    e = expr.strip()
    e = strip_lambda(e)
    e = e.replace('AscensionHelper.GetValueIfAscension(', 'ASC(')
    e = re.sub(r'AscensionLevel\.(\w+)', lambda m: str(ASC_LEVEL.get(m.group(1), m.group(1))), e)
    e = e.replace('base.CombatState.Players.Count', '1')
    e = re.sub(r'(\d+(?:\.\d+)?)[mfMFdD]\b', r'\1', e)
    e = re.sub(r'\((?:int|decimal|float|double|long)\)', '', e)
    e = re.sub(r'(\w+)\s*\?\?\s*(\w+)', r'COALESCE(\1, \2)', e)
    e = e.replace('&&', ' and ').replace('||', ' or ')
    e = re.sub(r'!(?!=)', ' not ', e)
    e = re.sub(r'\btrue\b', 'True', e)
    e = re.sub(r'\bfalse\b', 'False', e)
    e = re.sub(r'\bnull\b', 'None', e)
    return e.strip()


def default_of(ftype):
    t = ftype.rstrip('?')
    if ftype.endswith('?'):
        return None
    if t in ('int', 'long', 'decimal', 'float', 'double'):
        return 0
    if t == 'bool':
        return False
    return None


class Evaluator:
    def __init__(self, merged, asc, locals_=None, config=None):
        self.m = merged
        self.asc = asc
        self.locals = locals_ or {}
        self.config = config or {}
        self.dynamic = False
        self.stack = set()

    def eval(self, expr):
        py = to_py(expr)
        try:
            tree = ast.parse(py, mode='eval')
        except SyntaxError:
            raise Unresolved(expr)
        v = self._ev(tree.body)
        if isinstance(v, float) and v.is_integer():
            v = int(v)
        return v

    def ident(self, name):
        if name in self.config:
            return self.config[name]
        if name in self.locals:
            return Evaluator(self.m, self.asc, {k: v for k, v in self.locals.items() if k != name},
                             self.config).eval_sub(self.locals[name], self)
        if name in self.stack:
            raise Unresolved(name)
        self.stack.add(name)
        try:
            if name in self.m.props:
                p = self.m.props[name]
                if 'expr' in p:
                    return self.eval_sub(p['expr'], self)
                return self.eval_getter(p['getter'])
            if name in self.m.fields:
                f = self.m.fields[name]
                if not f['const'] and not f.get('readonly'):
                    # 可变字段：返回初始值，但标记为动态
                    self.dynamic = True
                if f['init'] is None:
                    return default_of(f['type'])
                return self.eval_sub(f['init'], self)
        finally:
            self.stack.discard(name)
        raise Unresolved(name)

    def eval_sub(self, expr, parent):
        ev = Evaluator(self.m, self.asc, self.locals, self.config)
        ev.stack = set(parent.stack)
        v = ev.eval(expr)
        if ev.dynamic:
            parent.dynamic = True
        return v

    def eval_getter(self, body):
        stmts = walk_statements(body)
        loc = {}
        for t, conds, loops in stmts:
            if conds or loops:
                raise Unresolved('getter with branches')
            m = re.match(r'^(?:int|decimal|float|var|bool)\s+(\w+)\s*=\s*(.+)$', t, re.S)
            if m:
                loc[m.group(1)] = m.group(2)
                continue
            m = re.match(r'^return\s+(.+)$', t, re.S)
            if m:
                ev = Evaluator(self.m, self.asc, {**self.locals, **loc}, self.config)
                ev.stack = set(self.stack)
                v = ev.eval(m.group(1))
                if ev.dynamic:
                    self.dynamic = True
                return v
        raise Unresolved('getter')

    def _ev(self, node):
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            return self.ident(node.id)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            fn = node.func.id
            if fn == 'ASC' and len(node.args) == 3:
                lvl = self._ev(node.args[0])
                return self._ev(node.args[1]) if self.asc >= lvl else self._ev(node.args[2])
            if fn == 'COALESCE':
                a = self._ev(node.args[0])
                return a if a is not None else self._ev(node.args[1])
            raise Unresolved(fn)
        if isinstance(node, ast.BinOp):
            a, b = self._ev(node.left), self._ev(node.right)
            if a is None or b is None:
                raise Unresolved('None arith')
            op = type(node.op)
            if op is ast.Add:
                return a + b
            if op is ast.Sub:
                return a - b
            if op is ast.Mult:
                return a * b
            if op is ast.Div:
                if isinstance(a, int) and isinstance(b, int):
                    return int(a / b)
                return a / b
            if op is ast.Mod:
                return a % b
            raise Unresolved('op')
        if isinstance(node, ast.UnaryOp):
            v = self._ev(node.operand)
            if isinstance(node.op, ast.USub):
                return -v
            if isinstance(node.op, ast.Not):
                return not v
            if isinstance(node.op, ast.UAdd):
                return v
        if isinstance(node, ast.Compare) and len(node.ops) == 1:
            a, b = self._ev(node.left), self._ev(node.comparators[0])
            op = type(node.ops[0])
            return {ast.Lt: a < b if None not in (a, b) else None, ast.Gt: a > b if None not in (a, b) else None,
                    ast.LtE: a <= b if None not in (a, b) else None, ast.GtE: a >= b if None not in (a, b) else None,
                    ast.Eq: a == b, ast.NotEq: a != b}[op]
        if isinstance(node, ast.BoolOp):
            vals = [self._ev(v) for v in node.values]
            return all(vals) if isinstance(node.op, ast.And) else any(vals)
        if isinstance(node, ast.IfExp):
            return self._ev(node.body) if self._ev(node.test) else self._ev(node.orelse)
        raise Unresolved(ast.dump(node)[:60])


def expand_getter(name, merged):
    """把 get { int x = ...; return x + ...; } 展开成一个表达式（给公式用）。"""
    p = merged.props.get(name)
    if not p or 'getter' not in p:
        return None
    loc = {}
    for t, conds, loops in walk_statements(p['getter']):
        if conds or loops:
            return None
        m = re.match(r'^(?:int|decimal|float|var)\s+(\w+)\s*=\s*(.+)$', t, re.S)
        if m:
            loc[m.group(1)] = m.group(2).strip()
            continue
        m = re.match(r'^return\s+(.+)$', t, re.S)
        if m:
            ex = m.group(1)
            for k, v in loc.items():
                ex = re.sub(r'\b%s\b' % re.escape(k), '(' + v + ')', ex)
            return ex
    return None


def substitute_partial(expr, merged, asc, locals_, _depth=0):
    """求不出值时，把能求值的标识符替换成数字，生成可读公式。"""
    e = strip_lambda(expr)

    def rep(m):
        name = m.group(0)
        if name in ('base', 'Creature', 'CombatState'):
            return name
        try:
            ev = Evaluator(merged, asc, locals_)
            v = ev.ident(name)
            if isinstance(v, (int, float)) and not ev.dynamic:
                return str(int(v) if float(v).is_integer() else v)
        except Unresolved:
            pass
        except Exception:
            pass
        if _depth < 3:
            g = expand_getter(name, merged)
            if g:
                return '(' + substitute_partial(g, merged, asc, locals_, _depth + 1) + ')'
        return name

    e = re.sub(r'AscensionHelper\.GetValueIfAscension\(AscensionLevel\.(\w+),\s*([-\d.]+)m?,\s*([-\d.]+)m?\)',
               lambda m: m.group(2) if asc >= ASC_LEVEL.get(m.group(1), 99) else m.group(3), e)
    e = re.sub(r'(?<![\w.<])[A-Z_]\w*(?![\w(<])', rep, e)
    e = re.sub(r'(\d+)m\b', r'\1', e)
    e = re.sub(r'\(\((\d+)\)\)', r'\1', e)
    return norm_ws(e)


def value(expr, merged, locals_=None, config=None):
    """返回 {"a0":..,"a10":..}；有可变状态时多带 dynamic/formula；完全求不出时返回字符串公式。"""
    if expr is None:
        return None
    out, dyn = {}, False
    try:
        for a in ASC_LEVELS:
            ev = Evaluator(merged, a, locals_, config)
            v = ev.eval(expr)
            if isinstance(v, bool) or v is None:
                raise Unresolved('non-number')
            out[f'a{a}'] = v
            dyn = dyn or ev.dynamic
    except (Unresolved, KeyError, TypeError, ZeroDivisionError, RecursionError):
        f0 = substitute_partial(expr, merged, 0, locals_)
        f10 = substitute_partial(expr, merged, 10, locals_)
        return f0 if f0 == f10 else f'{f0} (A10: {f10})'
    if dyn:
        out['dynamic'] = True
        out['formula'] = norm_ws(strip_lambda(expr))
    return out


def eval_bool(expr, merged, config=None, slot=None):
    e = strip_lambda(expr)
    if slot is not None:
        m = re.fullmatch(r'base\.Creature\.SlotName\s*==\s*"([^"]*)"', e)
        if m:
            return m.group(1) == slot
    e = re.sub(r'\(\(\w+\)base\.Creature\.Monster\)\.', '', e)
    e = re.sub(r'\(\(\w+\)\s*base\.Creature\.Monster\)\.', '', e)
    cfg = dict(config or {})
    # 配置里给的是属性名，条件里可能用字段名（_screamFirst）
    for k, v in list(cfg.items()):
        cfg['_' + k[0].lower() + k[1:]] = v
    m = re.fullmatch(r'(_?\w+)\.HasValue', e)
    if m:
        base = m.group(1).lstrip('_')
        for k in cfg:
            if k.lower().startswith(base.lower().replace('override', '').replace('amount', '')):
                return True
        return False
    try:
        v = Evaluator(merged, 0, None, cfg).eval(e)
        return bool(v) if v is not None else None
    except Exception:
        return None


# --------------------------------------------------------------------------- 本地化

def load_json(path):
    try:
        return json.load(open(path, encoding='utf-8'))
    except Exception:
        return {}


LOC = {}


def load_loc():
    for t in ('monsters', 'powers', 'cards', 'encounters', 'intents'):
        LOC[('zh', t)] = load_json(f'{LOC_ZH}/{t}.json')
        LOC[('en', t)] = load_json(f'{LOC_EN}/{t}.json')


def loc(lang, table, key):
    return LOC.get((lang, table), {}).get(key)


def monster_name_key(cls, mid):
    m = re.search(r'Title\s*=>\s*MonsterModel\.L10NMonsterLookup\("(\w+)\.name"\)', cls.body)
    if m:
        return m.group(1)
    if loc('en', 'monsters', mid + '.name'):
        return mid
    parts = mid.split('_')
    while len(parts) > 1:
        parts = parts[:-1]
        k = '_'.join(parts)
        if loc('en', 'monsters', k + '.name'):
            return k
    return mid


def move_name(name_key, move_id):
    cands = []
    x = move_id
    cands.append(x[:-5] if x.endswith('_MOVE') else x)
    y = re.sub(r'_?\d+$', '', x)
    cands.append(y[:-5] if y.endswith('_MOVE') else y)
    z = re.sub(r'_\d+_MOVE$', '', x)
    cands.append(z)
    cands.append(re.sub(r'\d+$', '', cands[0]))
    for c in cands:
        en = loc('en', 'monsters', f'{name_key}.moves.{c}.title')
        if en:
            return en, loc('zh', 'monsters', f'{name_key}.moves.{c}.title')
    return None, None


# --------------------------------------------------------------------------- 意图

def parse_intent(text, merged):
    text = text.strip()
    m = re.match(r'^new\s+(\w+)\s*\((.*)\)\s*$', text, re.S)
    if not m:
        return {'type': 'unknown', 'raw': norm_ws(text)}
    cls, argstr = m.group(1), m.group(2)
    args = split_args(argstr)
    typ, cli = INTENT_TYPES.get(cls, ('unknown', 'Unknown'))
    out = {'type': typ, 'cli_type': cli}
    if cls == 'SingleAttackIntent':
        out['damage'] = value(args[0], merged)
        out['hits'] = 1
    elif cls == 'MultiAttackIntent':
        out['damage'] = value(args[0], merged)
        hv = value(args[1], merged)
        out['hits'] = hv['a0'] if isinstance(hv, dict) and hv.get('a0') == hv.get('a10') and not hv.get('dynamic') else hv
    elif cls == 'DeathBlowIntent':
        out['damage'] = value(args[0], merged)
        out['hits'] = 1
    elif cls == 'DebuffIntent':
        if args and 'true' in args[0]:
            out['type'], out['cli_type'] = 'debuff_strong', 'DebuffStrong'
    elif cls == 'StatusIntent':
        cv = value(args[0], merged)
        out['count'] = cv['a0'] if isinstance(cv, dict) and cv.get('a0') == cv.get('a10') and not cv.get('dynamic') else cv
    return out


# --------------------------------------------------------------------------- 效果抽取

CMD_RE = re.compile(
    r'(DamageCmd\.Attack\(|PowerCmd\.Apply(?:<(\w+)>)?\(|PowerCmd\.Remove(?:<(\w+)>)?\(|CreatureCmd\.GainBlock\(|'
    r'CardPileCmd\.AddToCombatAndPreview<(\w+)>\(|CardPileCmd\.AddGeneratedCardToCombat\(|CreatureCmd\.Add(?:<(\w+)>)?\(|'
    r'CreatureCmd\.Heal\(|CreatureCmd\.Escape\(|CreatureCmd\.Kill\(|CreatureCmd\.Stun\(|CreatureCmd\.SetMaxAndCurrentHp\(|'
    r'CreatureCmd\.SetMaxHp\(|CardPileCmd\.RemoveFromCombat\(|CardSelectCmd\.FromChooseACardScreen\(|\.Steal\(\)|'
    r'\.DoReattach\(\)|SetMoveImmediate\()')


def clean_conds(conds):
    out = []
    for c in conds:
        c = norm_ws(c)
        if not c or NOISE_COND.search(c):
            continue
        out.append(c)
    return out


class EffectCtx:
    def __init__(self, merged, body, params=''):
        self.m = merged
        self.stmts = walk_statements(body)
        self.locals = {}
        self.loopvars = {}
        for t, conds, loops in self.stmts:
            mm = re.match(r'^(?:[\w<>\[\]?.]+)\s+(\w+)\s*=\s*(.+)$', t, re.S)
            if mm and not t.startswith(('return', 'await')) and '==' not in t.split('=')[0]:
                self.locals[mm.group(1)] = norm_ws(mm.group(2))
            for lp in loops:
                lm = re.match(r'^foreach\s*\(\s*[\w<>?]+\s+(\w+)\s+in\s+(.+)\)$', lp)
                if lm:
                    self.loopvars[lm.group(1)] = norm_ws(lm.group(2))
        # 局部变量里只把数值型的给求值器
        self.num_locals = {k: v for k, v in self.locals.items()
                           if re.fullmatch(r'[-\w\s.+*/()%,?:<>=!&|]+', v) and 'await' not in v}

    def target(self, expr, depth=0):
        e = norm_ws(expr)
        if e in ('targets', 'targets.First()'):
            return 'player'
        if e == 'base.Creature':
            return 'self'
        if 'GetOpponentsOf' in e or 'Players' in e:
            return 'player'
        if 'GetTeammatesOf' in e:
            return 'allies_excl_self' if '!= base.Creature' in e else 'allies_incl_self'
        mm = re.search(r'Monster is (\w+)', e)
        if mm and 'Enemies' in e:
            return 'ally:' + slug(mm.group(1))
        if depth > 4:
            return e
        if e in self.loopvars:
            coll = self.loopvars[e]
            base_t = self.target(re.sub(r'\.Where\(.*$', '', coll), depth + 1)
            if base_t.startswith('allies') and '!= base.Creature' in coll:
                return 'allies_excl_self'
            if 'GetPowerInstances' in coll:
                return 'self'
            return base_t
        if e in self.locals:
            d = self.locals[e]
            mm = re.search(r'Monster is (\w+)', d)
            if mm and 'Enemies' in d:
                return 'ally:' + slug(mm.group(1))
            if 'CreatureCmd.Add' in d:
                return 'summoned'
            if 'player.Creature' in d or 'Player' in d:
                return 'player'
            return self.target(re.sub(r'\.(ToList|Where)\(.*$', '', d) if 'GetTeammatesOf' not in d else d, depth + 1)
        mm = re.match(r'(\w+)\.(Player|PetOwner)', e)
        if mm:
            return 'player'
        if e in ('player.Creature', 'target2', 'item') and e not in self.loopvars:
            return 'player'
        return e

    def amount(self, expr):
        return value(expr, self.m, self.num_locals)

    def mult(self, loops):
        """循环倍数：for (int i = 0; i < N; i++) 乘 N；foreach 目标按单人 = 1。"""
        times, per = 1, []
        for lp in loops:
            mm = re.match(r'^for\s*\(\s*int\s+\w+\s*=\s*0\s*;\s*\w+\s*<\s*([^;]+);', lp)
            if mm:
                v = value(mm.group(1), self.m, self.num_locals)
                if isinstance(v, dict):
                    times *= v['a0']
                    if v.get('dynamic'):
                        per.append(f'循环次数 {mm.group(1)}（可变，初始 {v["a0"]}）')
                else:
                    per.append(f'循环 {mm.group(1)} 次')
                continue
            mm = re.match(r'^foreach\s*\(\s*[\w<>?]+\s+(\w+)\s+in\s+(.+)\)$', lp)
            if mm:
                t = self.target(mm.group(1))
                if t.startswith(('ally', 'allies', 'summoned')):
                    per.append(f'对每个 {t}')
        return times, per


def extract_effects(merged, method_name, all_classes=None, _seen=None, _outer_conds=None, _args=None):
    _seen = set(_seen or ())
    if method_name in _seen:
        return []
    _seen.add(method_name)
    meth = merged.methods.get(method_name)
    if meth is None:
        return []
    ctx = EffectCtx(merged, meth['body'], meth['params'])
    # 方法参数 -> 实参（内联 helper 时用）
    if _args:
        pnames = [p.strip().split()[-1] for p in meth['params'].split(',') if p.strip()]
        for pn, av in zip(pnames, _args):
            ctx.num_locals[pn] = av
            ctx.locals[pn] = av
    effects = []
    own_methods = set(merged.methods)
    for text, conds, loops in ctx.stmts:
        conds_c = clean_conds((_outer_conds or []) + conds)
        times, per = ctx.mult(loops)
        found = []
        for mm in CMD_RE.finditer(text):
            found.append((mm.start(), 'cmd', mm))
        for mm in re.finditer(r'(?<![\w.])(\w+)\(', text):
            nm = mm.group(1)
            if nm in own_methods and nm != method_name and not nm.startswith(('Get', 'Can')) \
                    and merged.methods[nm]['ret'] in ('Task', 'void') and nm not in ('SetColor', 'ScaleTo'):
                found.append((mm.start(), 'call', mm))
        found.sort(key=lambda x: x[0])
        for pos, kind, mm in found:
            eff = None
            if kind == 'call':
                args, _ = call_args(text, mm.end() - 1)
                sub = extract_effects(merged, mm.group(1), all_classes, _seen, conds_c, args)
                effects.extend(sub)
                continue
            tok = mm.group(1)
            if tok.startswith('DamageCmd.Attack'):
                args, end = call_args(text, mm.end() - 1)
                rest = text[end:]
                hm = re.search(r'\.WithHitCount\(', rest)
                hits = 1
                if hm:
                    hargs, _ = call_args(rest, hm.end() - 1)
                    hv = ctx.amount(hargs[0])
                    hits = hv['a0'] if isinstance(hv, dict) and hv['a0'] == hv['a10'] and not hv.get('dynamic') else hv
                eff = {'kind': 'attack', 'damage': ctx.amount(args[0]), 'hits': hits, 'target': 'player'}
            elif tok.startswith('PowerCmd.Apply'):
                args, _ = call_args(text, mm.end() - 1)
                if mm.group(2):
                    power, tgt, amt = mm.group(2), args[1], args[2]
                else:
                    pvar = args[1]
                    d = ctx.locals.get(pvar, '')
                    pm = re.search(r'Power<(\w+)>', d) or re.search(r'\((\w+Power)\)', d) or \
                        re.search(r'(\w+Power)\s+' + re.escape(pvar) + r'\b', merged.methods[method_name]['body'])
                    power = pm.group(1) if pm else pvar
                    tgt, amt = args[2], args[3]
                eff = {'kind': 'apply_power', 'power': power, 'target': ctx.target(tgt), 'amount': ctx.amount(amt)}
                if not mm.group(2):
                    tm = re.search(re.escape(args[1]) + r'\.Target\s*=\s*([^;\n]+)', merged.methods[method_name]['body'])
                    if tm:
                        eff['power_target'] = ctx.target(tm.group(1).strip().rstrip(';'))
            elif tok.startswith('PowerCmd.Remove'):
                args, _ = call_args(text, mm.end() - 1)
                if mm.group(3):
                    eff = {'kind': 'remove_power', 'power': mm.group(3), 'target': ctx.target(args[0])}
                else:
                    pm = re.search(r'GetPower<(\w+)>', args[0])
                    eff = {'kind': 'remove_power', 'power': pm.group(1) if pm else norm_ws(args[0]), 'target': 'self'}
            elif tok.startswith('CreatureCmd.GainBlock'):
                args, _ = call_args(text, mm.end() - 1)
                eff = {'kind': 'block', 'target': ctx.target(args[0]), 'amount': ctx.amount(args[1])}
            elif tok.startswith('CardPileCmd.AddToCombatAndPreview'):
                args, _ = call_args(text, mm.end() - 1)
                pile = re.sub(r'^PileType\.', '', args[1]).lower()
                cnt = ctx.amount(args[2])
                eff = {'kind': 'add_card', 'card': mm.group(4), 'pile': pile,
                       'count': cnt['a0'] if isinstance(cnt, dict) and cnt['a0'] == cnt['a10'] else cnt,
                       'to': ctx.target(args[0])}
            elif tok.startswith('CardPileCmd.AddGeneratedCardToCombat'):
                args, _ = call_args(text, mm.end() - 1)
                d = ctx.locals.get(args[0], '')
                cm = re.search(r'CreateCard<(\w+)>', d)
                pile = args[1]
                if pile in ctx.locals:
                    pile = ctx.locals[pile]
                pile = re.sub(r'PileType\.(\w+)', lambda x: x.group(1).lower(), norm_ws(pile))
                eff = {'kind': 'add_card', 'card': cm.group(1) if cm else args[0], 'pile': pile, 'count': 1, 'to': 'player'}
                if 'CardPilePosition.Random' in text:
                    eff['position'] = 'random'
            elif tok.startswith('CreatureCmd.Add'):
                args, _ = call_args(text, mm.end() - 1)
                eff = {'kind': 'summon', 'monster': slug(mm.group(5)) if mm.group(5) else None, 'count': 1}
                if not mm.group(5):
                    eff['raw'] = norm_ws(args[0])[:120]
            elif tok.startswith('CreatureCmd.Heal'):
                args, _ = call_args(text, mm.end() - 1)
                eff = {'kind': 'heal', 'target': ctx.target(args[0]), 'amount': ctx.amount(args[1])}
            elif tok.startswith('CreatureCmd.Escape'):
                eff = {'kind': 'escape'}
            elif tok.startswith('CreatureCmd.Kill'):
                args, _ = call_args(text, mm.end() - 1)
                eff = {'kind': 'suicide' if ctx.target(args[0]) == 'self' else 'kill', 'target': ctx.target(args[0])}
            elif tok.startswith('CreatureCmd.Stun'):
                args, _ = call_args(text, mm.end() - 1)
                eff = {'kind': 'stun_self'}
                if len(args) > 1:
                    eff['stun_move'] = norm_ws(args[1])
            elif tok.startswith('CreatureCmd.SetMax'):
                args, _ = call_args(text, mm.end() - 1)
                eff = {'kind': 'set_max_hp' if 'SetMaxHp' in tok else 'set_hp', 'target': ctx.target(args[0]),
                       'amount': ctx.amount(args[1])}
            elif tok.startswith('CardPileCmd.RemoveFromCombat'):
                eff = {'kind': 'steal_card'}
            elif tok.startswith('CardSelectCmd.FromChooseACardScreen'):
                eff = {'kind': 'player_choose_card'}
            elif tok == '.Steal()':
                eff = {'kind': 'steal_gold'}
            elif tok == '.DoReattach()':
                eff = {'kind': 'reattach'}
            elif tok.startswith('SetMoveImmediate'):
                args, _ = call_args(text, mm.end() - 1)
                eff = {'kind': 'force_move', 'state': norm_ws(args[0])}
            if eff is None:
                continue
            if times != 1:
                if 'count' in eff and isinstance(eff['count'], int):
                    eff['count'] *= times
                else:
                    eff['times'] = times
            if per:
                eff['per'] = per
            if conds_c:
                eff['when'] = conds_c
            effects.append(eff)
    return effects


# --------------------------------------------------------------------------- 状态机

def parse_state_machine(merged):
    meth = merged.methods.get('GenerateMoveStateMachine')
    if meth is None:
        return None
    body = meth['body']
    stmts = walk_statements(body)
    var2id = {}
    states = {}       # id -> dict
    order = []

    def resolve(tok):
        tok = tok.strip().strip('()').strip()
        tok = re.sub(r'^\((?:MoveState|RandomBranchState|ConditionalBranchState|MonsterState)\)', '', tok).strip('() ')
        return var2id.get(tok, tok)

    returns = []
    for text, conds, loops in stmts:
        t = text
        # 新状态
        new_state = None
        nm = re.search(r'new\s+(MoveState|RandomBranchState|ConditionalBranchState)\s*\(', t)
        if nm:
            args, end = call_args(t, nm.end() - 1)
            kind = nm.group(1)
            sid = args[0].strip().strip('"')
            st = {'kind': kind, 'id': sid}
            if kind == 'MoveState':
                st['perform'] = args[1].strip() if len(args) > 1 else None
                st['intents_src'] = args[2:]
                rest = t[end + 1:]
                if re.match(r'\s*\{[^}]*MustPerformOnceBeforeTransitioning\s*=\s*true', rest):
                    st['must_perform_once'] = True
                fm = re.match(r'\s*\{[^}]*FollowUpStateId\s*=\s*"(\w+)"', rest)
                if fm:
                    st['next'] = fm.group(1)
            elif kind == 'RandomBranchState':
                st['options'] = []
            else:
                st['conditions'] = []
            states[sid] = st
            order.append(sid)
            new_state = sid
        # 绑定变量
        lm = re.match(r'^(?:(?:MoveState|RandomBranchState|ConditionalBranchState|MonsterState)\s+)?(\w+)\s*=(?!=)', t)
        if lm and new_state and not t.startswith('return'):
            var2id[lm.group(1)] = new_state
        elif lm and not new_state and not t.startswith('return') and '.FollowUpState' not in lm.group(0):
            rhs = t[lm.end():].strip()
            if re.fullmatch(r'\(*\s*\w+\s*\)*', rhs) and resolve(rhs) in states:
                var2id[lm.group(1)] = resolve(rhs)
            elif lm.group(1) in ('initialState',) or 'MonsterState' in t[:lm.end()] or 'MoveState' in t[:lm.end()]:
                var2id.setdefault('__expr__' + lm.group(1), rhs)
        # FollowUpState
        srcs = re.findall(r'(\w+)\.FollowUpState\s*=', t)
        if srcs:
            if new_state:
                dst = new_state
            else:
                dm = re.search(r'FollowUpState\s*=\s*\(*\s*(\w+)\s*\)*\s*$', t)
                dst = resolve(dm.group(1)) if dm else None
            for s in srcs:
                sid = resolve(s)
                if sid in states:
                    states[sid]['next'] = dst
        # AddBranch / AddState
        am = re.match(r'^(\w+)\.(AddBranch|AddState)\(', t)
        if am:
            bid = resolve(am.group(1))
            args, _ = call_args(t, am.end() - 1)
            if am.group(2) == 'AddState':
                cond = norm_ws(strip_lambda(args[1])) if len(args) > 1 else 'true'
                c2 = clean_conds(conds)
                if c2:
                    cond = ' && '.join(f'({c})' for c in c2) + f' && ({cond})'
                states.setdefault(bid, {'kind': 'ConditionalBranchState', 'id': bid, 'conditions': []})
                states[bid]['conditions'].append({'move': resolve(args[0]), 'when': cond})
            else:
                states[bid]['options'].append(parse_branch_args(args, resolve, merged))
        if t.startswith('return') and 'MonsterMoveStateMachine' in t:
            returns.append((t, clean_conds(conds)))
        elif t.startswith('return') and 'switch' in t:
            returns.append((t, clean_conds(conds)))
    # 初始状态
    initial_opts = []
    for t, conds in returns:
        exprs = []
        for nm in re.finditer(r'new\s+MonsterMoveStateMachine\s*\(', t):
            args, _ = call_args(t, nm.end() - 1)
            exprs.append(args[1])
        sw = re.search(r'\(([^()]*)\)\s*switch\s*\{(.*)\}', t, re.S)
        if sw:
            subj = sw.group(1)
            for arm in split_args(sw.group(2)):
                if '=>' not in arm:
                    continue
                lab, rhs = arm.split('=>', 1)
                lab = 'default' if lab.strip() == '_' else lab
                inner = re.search(r'new\s+MonsterMoveStateMachine\s*\(\s*\w+\s*,\s*(\w+)\s*\)', rhs)
                tgt = resolve(inner.group(1) if inner else rhs.strip())
                initial_opts.append({'state': tgt, 'when': conds + [f'{subj} == {lab.strip()}']})
            continue
        for ex in exprs:
            ex = ex.strip()
            if '__expr__' + ex in var2id:
                ex = var2id['__expr__' + ex]
            ex = re.sub(r'\((?:MoveState|MonsterState)\)', '', ex).strip()
            while ex.startswith('(') and match_bracket(ex, 0) == len(ex) - 1:
                ex = ex[1:-1].strip()
            tm = re.match(r'^(.+?)\?\s*\(*\s*(\w+)\s*\)*\s*:\s*\(*\s*(\w+)\s*\)*$', ex, re.S)
            if tm:
                c = norm_ws(tm.group(1))
                initial_opts.append({'state': resolve(tm.group(2)), 'when': conds + [c]})
                initial_opts.append({'state': resolve(tm.group(3)), 'when': conds + [f'!({c})']})
            else:
                initial_opts.append({'state': resolve(ex), 'when': conds})
    # 默认初始状态（按字段默认值求条件）
    initial = None
    for o in initial_opts:
        ok = True
        for c in o['when']:
            r = eval_bool(c, merged)
            if r is False:
                ok = False
                break
            if r is None and '%' in c:
                ok = False
                break
        if ok:
            initial = o['state']
            break
    if initial is None and initial_opts:
        initial = initial_opts[-1]['state']
    return {'states': states, 'order': order, 'initial': initial, 'initial_options': initial_opts}


def parse_branch_args(args, resolve, merged):
    st = resolve(args[0])
    rest = args[1:]
    opt = {'move': st, 'repeat': 'CanRepeatForever', 'weight': 1, 'cooldown': 0}

    def is_rt(a):
        return a.strip().startswith('MoveRepeatType.')

    def wval(a):
        v = value(strip_lambda(a), merged)
        if isinstance(v, dict) and not v.get('dynamic') and v['a0'] == v['a10']:
            return v['a0']
        return v if isinstance(v, (dict,)) else norm_ws(strip_lambda(a))

    def ival(a):
        v = value(a, merged)
        return v['a0'] if isinstance(v, dict) else a

    if len(rest) == 1:
        if is_rt(rest[0]):
            opt['repeat'] = rest[0].split('.')[1]
        else:
            opt['repeat'], opt['max_times'] = 'CanRepeatXTimes', ival(rest[0])
    elif len(rest) == 2:
        if is_rt(rest[0]):
            opt['repeat'] = rest[0].split('.')[1]
            opt['weight'] = wval(rest[1])
        elif is_rt(rest[1]):
            opt['cooldown'] = ival(rest[0])
            opt['repeat'] = rest[1].split('.')[1]
        else:
            opt['repeat'], opt['max_times'] = 'CanRepeatXTimes', ival(rest[0])
            opt['weight'] = wval(rest[1])
    elif len(rest) == 3:
        opt['cooldown'] = ival(rest[0])
        if is_rt(rest[1]):
            opt['repeat'] = rest[1].split('.')[1]
        else:
            opt['repeat'], opt['max_times'] = 'CanRepeatXTimes', ival(rest[1])
        opt['weight'] = wval(rest[2])
    rp = opt['repeat']
    opt['cannot_repeat'] = rp == 'CannotRepeat'
    if rp == 'CannotRepeat':
        opt['max_consecutive'] = 1
    elif rp == 'CanRepeatXTimes':
        opt['max_consecutive'] = opt.get('max_times')
    if rp == 'UseOnlyOnce':
        opt['use_only_once'] = True
    return opt


# --------------------------------------------------------------------------- 怪物

AUTO_HOOK_SKIP = {'GenerateMoveStateMachine', 'GenerateAnimator', 'SetupSkins', 'GenerateBestiaryMoveList',
                  'ShouldShowMoveInBestiary', 'OnDieToDoom', 'AfterAddedToRoom', 'SegmentAttack'}


def build_monster(cls, merged, all_classes):
    mid = slug(cls.name)
    key = monster_name_key(cls, mid)
    d = {'id': mid, 'class': cls.name, 'file': cls.file,
         'name': strip_bbcode(loc('en', 'monsters', key + '.name') or cls.name),
         'name_zh': strip_bbcode(loc('zh', 'monsters', key + '.name') or '')}
    if cls.base and cls.base != 'MonsterModel':
        d['inherits'] = slug(cls.base)
    mn = value(merged.props['MinInitialHp']['expr'], merged) if 'expr' in merged.props.get('MinInitialHp', {}) else None
    mx = value(merged.props['MaxInitialHp']['expr'], merged) if 'expr' in merged.props.get('MaxInitialHp', {}) else None
    if isinstance(mn, dict) and isinstance(mx, dict):
        d['hp'] = {f'a{a}': [mn[f'a{a}'], mx[f'a{a}']] for a in ASC_LEVELS}
    else:
        d['hp'] = {'min': mn, 'max': mx}
    # 开场：AfterAddedToRoom
    start_eff = []
    if 'AfterAddedToRoom' in merged.methods:
        own = merged.methods['AfterAddedToRoom']
        if 'AfterAddedToRoom' in cls.methods and 'base.AfterAddedToRoom()' in own['body']:
            pm = merged.parent_method('AfterAddedToRoom')
            if pm is not None:
                parent_merged = Merged(all_classes[merged.chain[1].name], all_classes)
                start_eff.extend(extract_effects(parent_merged, 'AfterAddedToRoom', all_classes))
        start_eff.extend(extract_effects(merged, 'AfterAddedToRoom', all_classes))
    d['start_powers'] = []
    other = []
    for e in start_eff:
        if e['kind'] == 'apply_power' and e['target'] == 'self':
            sp = {'power': e['power'], 'amount': e['amount']}
            for k in ('power_target', 'when', 'per'):
                if k in e:
                    sp[k] = e[k]
            d['start_powers'].append(sp)
        else:
            other.append(e)
    if other:
        d['start_effects'] = other
    # 状态机
    sm = parse_state_machine(merged)
    d['moves'], d['branches'] = {}, {}
    if sm:
        for sid in sm['order']:
            st = sm['states'][sid]
            if st['kind'] == 'MoveState':
                mv = {}
                en, zh = move_name(key, sid)
                if en:
                    mv['name'] = strip_bbcode(en)
                    if zh:
                        mv['name_zh'] = strip_bbcode(zh)
                mv['intents'] = [parse_intent(x, merged) for x in st.get('intents_src', [])]
                perf = st.get('perform') or ''
                if perf in merged.methods:
                    mv['effects'] = extract_effects(merged, perf, all_classes)
                    mv['perform'] = perf
                else:
                    mv['effects'] = []
                mv['next'] = st.get('next')
                if st.get('must_perform_once'):
                    mv['must_perform_once'] = True
                d['moves'][sid] = mv
            elif st['kind'] == 'RandomBranchState':
                d['branches'][sid] = {'kind': 'random', 'options': st['options']}
            else:
                d['branches'][sid] = {'kind': 'conditional', 'conditions': st['conditions']}
        d['initial'] = sm['initial']
        if len({o['state'] for o in sm['initial_options']}) > 1 or any(o['when'] for o in sm['initial_options']):
            d['initial_options'] = [{'state': o['state'], 'when': o['when']} for o in sm['initial_options']]
    else:
        d['initial'] = None
    # 可达性：从开局状态沿 next / 分支走一遍；走不到的招式是代码强制切进去的（眩晕、死亡、复活等）
    if d['moves']:
        start = {d['initial']} | {o['state'] for o in d.get('initial_options', [])}
        seen, todo = set(), [x for x in start if x]
        while todo:
            x = todo.pop()
            if x in seen:
                continue
            seen.add(x)
            if x in d['moves']:
                if d['moves'][x].get('next'):
                    todo.append(d['moves'][x]['next'])
            elif x in d['branches']:
                br = d['branches'][x]
                todo.extend(o['move'] for o in br.get('options', []) + br.get('conditions', []))
        for k, mv in d['moves'].items():
            if k not in seen:
                mv['special_entry'] = True
        for k, br in d['branches'].items():
            if k not in seen:
                br['unused'] = True
    # 钩子（只列名字，给人看；机制写在 notes）
    hooks = []
    for name, meth in merged.methods.items():
        if meth['override'] and name not in AUTO_HOOK_SKIP and name != 'BeforeRemovedFromRoom':
            hooks.append(name)
    for ev in re.findall(r'base\.Creature\.(\w+)\s*\+=', cls.body):
        hooks.append(f'event:{ev}')
    if hooks:
        d['hooks'] = sorted(set(hooks))
    return d


# --------------------------------------------------------------------------- 遭遇

def parse_acts():
    act_enc, act_events, bosses = {}, {}, {}
    for f in sorted(os.listdir(ACT_DIR)):
        s = read(os.path.join(ACT_DIR, f))
        name = f[:-3]
        i = s.find('GenerateAllEncounters')
        if i >= 0:
            j = s.find('});', i)
            for e in re.findall(r'Encounter<(\w+)>', s[i:j]):
                act_enc.setdefault(e, []).append(name)
        i = s.find('AllEvents')
        if i >= 0:
            j = s.find('});', i)
            for e in re.findall(r'Event<(\w+)>', s[i:j]):
                act_events.setdefault(e, []).append(name)
        i = s.find('BossDiscoveryOrder')
        if i >= 0:
            j = s.find('});', i)
            for e in re.findall(r'Encounter<(\w+)>', s[i:j]):
                bosses.setdefault(e, []).append(name)
    s = read(MODELDB)
    i = s.find('AllSharedEvents =>')
    shared = set()
    if i >= 0:
        j = s.find('}));', i)
        shared = set(re.findall(r'Event<(\w+)>', s[i:j]))
    return act_enc, act_events, shared


def find_event_for_encounter(enc_name):
    ev_dir = f'{SRC}/MegaCrit.Sts2.Core.Models.Events'
    out = []
    for f in os.listdir(ev_dir):
        if f.endswith('.cs') and enc_name in read(os.path.join(ev_dir, f)):
            out.append(f[:-3])
    return sorted(out)


def build_encounter(cls, mon_classes, act_enc, act_events, shared_events):
    eid = slug(cls.name)
    b = cls.body
    d = {'id': eid, 'class': cls.name, 'file': cls.file,
         'name': strip_bbcode(loc('en', 'encounters', eid + '.title') or ''),
         'name_zh': strip_bbcode(loc('zh', 'encounters', eid + '.title') or '')}
    m = re.search(r'RoomType\s*=>\s*RoomType\.(\w+)', b)
    d['room_type'] = m.group(1) if m else None
    d['is_weak'] = bool(re.search(r'IsWeak\s*=>\s*true', b))
    d['gives_rewards'] = not bool(re.search(r'ShouldGiveRewards\s*=>\s*false', b))
    acts = act_enc.get(cls.name, [])
    events = []
    if not acts and 'Event' in cls.name:
        events = find_event_for_encounter(cls.name)
        for ev in events:
            acts = acts + act_events.get(ev, [])
        d['event'] = events
        if any(ev in shared_events for ev in events):
            d['event_shared'] = True
    d['in_act_pool'] = bool(act_enc.get(cls.name))
    d['act_names'] = sorted(set(acts))
    nums = sorted({ACT_NUMBER[a] for a in acts if a in ACT_NUMBER})
    d['act'] = nums[0] if len(nums) == 1 else (nums or None)
    sm = re.search(r'Slots\s*=>[^;]*?\{([^}]*)\}', b)
    if sm:
        d['slots'] = re.findall(r'"([^"]*)"', sm.group(1))
    else:
        sm = re.search(r'Slots\s*=>[^;]*?\("([^"]+)"\)', b)
        d['slots'] = [sm.group(1)] if sm else []
    tags = re.findall(r'EncounterTag\.(\w+)', b)
    if tags:
        d['tags'] = sorted(set(tags))
    # 所有可能出现的怪
    poss = re.findall(r'Monster<(\w+)>', b)
    for cname, field in re.findall(r'\b([A-Z]\w+)\.(\w+Spawns)\b', b):
        if cname in mon_classes:
            fs = mon_classes[cname].raw
            fi = fs.find(field)
            fj = fs.find('};', fi)
            poss += re.findall(r'Monster<(\w+)>', fs[fi:fj])
    d['possible_monsters'] = sorted({slug(x) for x in poss})
    # GenerateMonsters
    gm = None
    mm = re.search(r'GenerateMonsters\(\)\s*\{', b)
    if mm:
        ob = b.find('{', mm.end() - 1)
        gm = b[ob + 1:match_bracket(b, ob, '{', '}')]
    d['random_composition'] = bool(gm and 'Rng' in gm)
    monsters = []
    if gm:
        varmon = {}
        for vm in re.finditer(r'(\w+)\s+(\w+)\s*=\s*\(\w+\)ModelDb\.Monster<(\w+)>\(\)\.ToMutable\(\)', gm):
            varmon[vm.group(2)] = {'monster': slug(vm.group(3)), 'cls': vm.group(3), 'config': {}}
        for cm in re.finditer(r'\b(\w+)\.(\w+)\s*=\s*([^;]+);', gm):
            var, prop, val = cm.group(1), cm.group(2), cm.group(3).strip()
            if var in varmon:
                vv = val
                im = re.match(r'^\((\w+)\.(\w+)\s*=\s*(.+)\)$', val)
                if im:
                    vv = im.group(3)
                    if im.group(1) in varmon:
                        varmon[im.group(1)]['config'][im.group(2)] = parse_cfg_val(vv)
                varmon[var]['config'][prop] = parse_cfg_val(vv)
        # num = (x.StarterMoveIdx = base.Rng.NextInt(3))
        for cm in re.finditer(r'\(\s*(\w+)\.(\w+)\s*=\s*([^)]+\))\s*\)', gm):
            if cm.group(1) in varmon:
                varmon[cm.group(1)]['config'][cm.group(2)] = parse_cfg_val(cm.group(3))
        slots = d.get('slots', [])
        for tm in re.finditer(r'\(\s*(ModelDb\.Monster<(\w+)>\(\)\.ToMutable\(\)|\w+(?:\.ToMutable\(\))?)\s*,\s*'
                              r'(null|"[^"]*"|Slots\[(\d+)\]|_slotNames\[[^\]]+\]|\w+)\s*\)', gm):
            expr, gen, slot_e = tm.group(1), tm.group(2), tm.group(3)
            if slot_e.startswith('"'):
                slot = slot_e.strip('"')
            elif tm.group(4):
                slot = slots[int(tm.group(4))] if int(tm.group(4)) < len(slots) else slot_e
            elif slot_e == 'null':
                slot = None
            else:
                slot = slot_e
            if gen:
                monsters.append({'monster': slug(gen), 'slot': slot})
            else:
                v = expr.replace('.ToMutable()', '')
                if v in varmon:
                    e = {'monster': varmon[v]['monster'], 'slot': slot}
                    if varmon[v]['config']:
                        e['config'] = varmon[v]['config']
                    monsters.append(e)
                elif expr.endswith('.ToMutable()') or re.match(r'^monsterModel\d*$', v):
                    # 随机挑出来的怪（base.Rng.NextItem(...)），具体是谁写在手工补丁的 one_of 里
                    monsters.append({'monster': None, 'slot': slot, 'random_pick': v})
    d['monsters'] = monsters
    return d


def parse_cfg_val(v):
    v = v.strip()
    if v in ('true', 'false'):
        return v == 'true'
    if re.fullmatch(r'-?\d+', v):
        return int(v)
    m = re.fullmatch(r'\(\s*num\s*\+\s*(\d+)\s*\)\s*%\s*3', v)
    if m:
        return f'random_offset+{m.group(1)}'
    if 'Rng' in v:
        return 'random:' + norm_ws(v)
    return norm_ws(v)


def resolve_initial(mon, entry, mon_merged):
    """按站位/配置求这个遭遇里该怪第一回合的状态。"""
    opts = mon.get('initial_options')
    cfg = entry.get('config', {})
    slot = entry.get('slot')
    state = mon.get('initial')
    if opts:
        chosen = None
        for o in opts:
            ok = True
            for c in o['when']:
                if '%' in c:
                    sv = None
                    for k, v in cfg.items():
                        if k.lower().startswith('startermove') and isinstance(v, int):
                            sv = v
                    lab = c.split('==')[-1].strip()
                    if sv is None:
                        return 'random'
                    if lab in ('_', 'default'):
                        continue
                    if not lab.isdigit() or sv % 3 != int(lab):
                        ok = False
                        break
                    continue
                r = eval_bool(c, mon_merged, cfg, slot)
                if r is False:
                    ok = False
                    break
            if ok:
                chosen = o['state']
                break
        state = chosen or state
    # 初始状态若是条件分支（按站位决定），再往下解一层
    br = mon.get('branches', {}).get(state)
    seen = set()
    while br and br['kind'] == 'conditional' and state not in seen:
        seen.add(state)
        nxt = None
        for c in br['conditions']:
            r = eval_bool(c['when'], mon_merged, cfg, slot)
            if r:
                nxt = c['move']
                break
            if r is None:
                return state
        if nxt is None:
            return state
        state = nxt
        br = mon.get('branches', {}).get(state)
    return state


# --------------------------------------------------------------------------- 词条表（能力 / 状态牌）

EXTRA_POWERS = ['TaintedPower', 'DisintegrationPower', 'MindRotPower', 'SlothPower', 'WasteAwayPower']


def power_glossary(names):
    out = {}
    names = {p for p in set(names) | set(EXTRA_POWERS) if os.path.exists(f'{POW_DIR}/{p}.cs')}
    for p in sorted(names):
        k = slug(p)
        e = {'name': strip_bbcode(loc('en', 'powers', k + '.title') or p),
             'name_zh': strip_bbcode(loc('zh', 'powers', k + '.title') or ''),
             'desc': strip_bbcode(loc('en', 'powers', k + '.smartDescription') or loc('en', 'powers', k + '.description') or ''),
             'desc_zh': strip_bbcode(loc('zh', 'powers', k + '.smartDescription') or loc('zh', 'powers', k + '.description') or '')}
        path = f'{POW_DIR}/{p}.cs'
        if os.path.exists(path):
            s = read(path)
            m = re.search(r'PowerType\s+Type\s*=>\s*PowerType\.(\w+)', s)
            if m:
                e['type'] = m.group(1)
            m = re.search(r'PowerStackType\s+StackType\s*=>\s*PowerStackType\.(\w+)', s)
            if m:
                e['stack'] = m.group(1)
        out[p] = e
    return out


def card_glossary(names):
    out = {}
    for c in sorted(names):
        k = slug(c)
        e = {'name': strip_bbcode(loc('en', 'cards', k + '.title') or c),
             'name_zh': strip_bbcode(loc('zh', 'cards', k + '.title') or ''),
             'desc_zh': strip_bbcode(loc('zh', 'cards', k + '.description') or '')}
        path = f'{CARD_DIR}/{c}.cs'
        if os.path.exists(path):
            s = read(path)
            m = re.search(r':\s*base\((-?\d+),\s*CardType\.(\w+)', s)
            if m:
                e['cost'] = int(m.group(1))
                e['type'] = m.group(2)
            kw = sorted(set(re.findall(r'CardKeyword\.(\w+)', s)))
            if kw:
                e['keywords'] = kw
            m = re.search(r'new DamageVar\((\d+)m', s)
            if m:
                e['damage_end_of_turn_in_hand'] = int(m.group(1))
            m = re.search(r'new HpLossVar\((\d+)m', s)
            if m:
                e['hp_loss_end_of_turn_in_hand'] = int(m.group(1))
        out[c] = e
    return out


# --------------------------------------------------------------------------- 合并手工补丁

def deep_merge(dst, src):
    for k, v in src.items():
        if k.startswith('//'):
            continue
        if isinstance(v, dict) and isinstance(dst.get(k), dict) and not v.get('__replace__'):
            deep_merge(dst[k], v)
        else:
            if isinstance(v, dict) and v.get('__replace__'):
                v = {kk: vv for kk, vv in v.items() if kk != '__replace__'}
            dst[k] = copy.deepcopy(v)
    return dst


def collect_names(obj, powers, cards):
    if isinstance(obj, dict):
        if obj.get('kind') in ('apply_power', 'remove_power') and isinstance(obj.get('power'), str):
            powers.add(obj['power'])
        if 'power' in obj and isinstance(obj['power'], str) and obj['power'].endswith('Power'):
            powers.add(obj['power'])
        if obj.get('kind') == 'add_card' and isinstance(obj.get('card'), str) and re.fullmatch(r'[A-Z]\w+', obj['card']):
            cards.add(obj['card'])
        for v in obj.values():
            collect_names(v, powers, cards)
    elif isinstance(obj, list):
        for v in obj:
            collect_names(v, powers, cards)


# --------------------------------------------------------------------------- 主流程

def main():
    global OUT_MON, OUT_ENC
    check_only = '--check' in sys.argv
    if '--out' in sys.argv:  # 调试用：输出到别的目录
        od = sys.argv[sys.argv.index('--out') + 1]
        OUT_MON, OUT_ENC = f'{od}/monsters.json', f'{od}/encounters_src.json'
    load_asc_levels()
    load_loc()
    mon_classes = load_classes(MON_DIR)
    enc_classes = load_classes(ENC_DIR)
    overrides = load_json(OVERRIDE)
    mon_over = overrides.get('monsters', {})
    enc_over = overrides.get('encounters', {})

    monsters, merged_of, skipped = {}, {}, []
    for name, cls in mon_classes.items():
        if cls.abstract:
            skipped.append({'class': name, 'reason': '抽象基类，不会单独出现（逻辑被子类继承）'})
            continue
        mg = Merged(cls, mon_classes)
        merged_of[slug(name)] = mg
        try:
            monsters[slug(name)] = build_monster(cls, mg, mon_classes)
        except Exception as ex:  # 解析失败的怪靠手工补
            monsters[slug(name)] = {'id': slug(name), 'class': name, 'file': cls.file, 'parse_error': repr(ex)}

    act_enc, act_events, shared = parse_acts()
    encounters = {}
    for name, cls in enc_classes.items():
        if cls.abstract:
            skipped.append({'class': name, 'reason': '抽象遭遇基类'})
            continue
        encounters[slug(name)] = build_encounter(cls, mon_classes, act_enc, act_events, shared)

    # 手工补丁
    for mid, ov in mon_over.items():
        if mid.startswith('//'):
            continue
        if mid not in monsters:
            monsters[mid] = {'id': mid}
        deep_merge(monsters[mid], ov)
        monsters[mid]['manual'] = sorted(k for k in ov if not k.startswith('//'))
    for eid, ov in enc_over.items():
        if eid.startswith('//'):
            continue
        if eid not in encounters:
            encounters[eid] = {'id': eid}
        deep_merge(encounters[eid], ov)
        encounters[eid]['manual'] = sorted(k for k in ov if not k.startswith('//'))

    # 遭遇里每只怪的开局招式
    for eid, e in encounters.items():
        for ent in e.get('monsters', []):
            mid = ent.get('monster')
            if mid in monsters and mid in merged_of and 'initial_move' not in ent:
                try:
                    ent['initial_move'] = resolve_initial(monsters[mid], ent, merged_of[mid])
                except Exception:
                    pass

    # 召唤关系：招式里的 summon 效果 + 开局能力（死亡时召唤，如 意外/寄生物/库存）里的 CreatureCmd.Add
    for mid, m in monsters.items():
        sp = set()
        for mv in m.get('moves', {}).values():
            for ef in mv.get('effects', []):
                if ef.get('kind') == 'summon':
                    if ef.get('monster'):
                        sp.add(ef['monster'])
                    sp.update(ef.get('one_of', []))
        for p in m.get('start_powers', []):
            pn = p.get('power')
            path = f'{POW_DIR}/{pn}.cs'
            if isinstance(pn, str) and os.path.exists(path):
                ps = read(path)
                if 'CreatureCmd.Add' in ps:
                    for x in re.findall(r'(?:Monster|CreatureCmd\.Add)<(\w+)>', ps):
                        sp.add(slug(x))
        sp.update(m.get('spawns', []) if isinstance(m.get('spawns'), list) else [])
        if sp:
            m['spawns'] = sorted(sp)
    # 反查：怪物出现在哪些遭遇 / 哪一幕；分类
    spawned_by = {}
    for mid, m in monsters.items():
        for mv in list(m.get('moves', {}).values()) + [{'effects': m.get('start_effects', [])}]:
            for ef in mv.get('effects', []):
                if ef.get('kind') == 'summon' and ef.get('monster'):
                    spawned_by.setdefault(ef['monster'], set()).add(mid)
        for x in m.get('spawns', []):
            spawned_by.setdefault(x, set()).add(mid)
    for mid, m in monsters.items():
        in_enc, in_poss, acts = [], [], set()
        for eid, e in encounters.items():
            listed = {x.get('monster') for x in e.get('monsters', [])}
            for x in e.get('monsters', []):
                for o in x.get('one_of', []) or []:
                    listed.add(o)
                for g in x.get('one_of_groups', []) or []:
                    listed.update(g)
            if mid in listed:
                in_enc.append(eid)
            if mid in e.get('possible_monsters', []):
                in_poss.append(eid)
                a = e.get('act')
                if isinstance(a, int):
                    acts.add(a)
                elif isinstance(a, list):
                    acts.update(a)
        m['encounters'] = sorted(set(in_enc) | set(in_poss))
        m['acts'] = sorted(acts)
        if mid in spawned_by:
            m['spawned_by'] = sorted(spawned_by[mid])
        if 'category' not in m:
            cls = m.get('class')
            if cls in TEST_MONSTERS:
                m['category'] = 'test'
            elif cls in PET_MONSTERS:
                m['category'] = 'pet'
            elif any(not encounters[e].get('event') for e in in_enc if e in encounters):
                m['category'] = 'enemy'
            elif in_poss and any(not encounters[e].get('event') for e in in_poss):
                m['category'] = 'summon'
            elif in_enc or in_poss:
                m['category'] = 'event'
            else:
                m['category'] = 'unused'

    powers, cards = set(), set()
    collect_names(monsters, powers, cards)
    meta = {
        'source': f'decompiled {GAME_VERSION} (MegaCrit.Sts2.Core.Models.Monsters / Encounters)',
        'generated_by': 'agent/tools/extract_monsters.py',
        'ascension': {'levels': ASC_LEVEL, 'a10_includes': [k for k, v in ASC_LEVEL.items() if 0 < v <= 10],
                      'monster_relevant': {'ToughEnemies': ASC_LEVEL.get('ToughEnemies'),
                                           'DeadlyEnemies': ASC_LEVEL.get('DeadlyEnemies')}},
        'counts': {'monsters': len(monsters), 'encounters': len(encounters)},
        'skipped_classes': skipped,
        'powers': power_glossary(powers),
        'cards': card_glossary(cards),
        'doc': 'kb/README_monsters.md',
    }
    out_m = {'_meta': meta}
    for k in sorted(monsters):
        out_m[k] = monsters[k]
    out_e = {'_meta': {'source': meta['source'], 'generated_by': meta['generated_by'],
                       'count': len(encounters), 'act_number': ACT_NUMBER, 'doc': meta['doc']}}
    for k in sorted(encounters):
        out_e[k] = encounters[k]

    errs = [k for k, v in monsters.items() if 'parse_error' in v]
    print(f'monsters={len(monsters)} encounters={len(encounters)} skipped={len(skipped)} parse_errors={errs}')
    if check_only:
        return
    with open(OUT_MON, 'w', encoding='utf-8') as f:
        json.dump(out_m, f, ensure_ascii=False, indent=1)
    with open(OUT_ENC, 'w', encoding='utf-8') as f:
        json.dump(out_e, f, ensure_ascii=False, indent=1)
    print('wrote', OUT_MON, OUT_ENC)


if __name__ == '__main__':
    main()
