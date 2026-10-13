# 乖乖值計算器：每個交易日收盤後，抓上市、上櫃收盤價，存成網頁要用的資料檔
import json, os, re, time, datetime as dt, urllib.request

KEEP = 100                      # 保留最近 100 個交易日
D = 'data'
UA = {'User-Agent': 'Mozilla/5.0'}
TW = dt.timezone(dt.timedelta(hours=8))

def get(url):
    err = None
    for t in range(4):
        time.sleep(3 if t == 0 else 15)
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as r:
                return json.loads(r.read().decode('utf-8'))
        except Exception as e:
            err = e
            print('  retry', t + 1, url[:90], e)
    raise err

def num(x):
    try:
        return float(str(x).replace(',', '').strip())
    except Exception:
        return None

def okcode(c):
    return re.fullmatch(r'[1-9]\d{3}|00\d{2,4}[A-Z]?', c) is not None

def table(j, need):
    for t in j.get('tables') or []:
        f = [str(x).strip() for x in (t.get('fields') or [])]
        if all(any(n == x for x in f) for n in need):
            return f, t.get('data') or []
    return None, None

def twse(day):
    j = get(f'https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={day}&type=ALLBUT0999&response=json')
    if str(j.get('stat', '')).upper() != 'OK' or str(j.get('date', day)) != day:
        return None
    f, data = table(j, ['證券代號', '證券名稱', '收盤價'])
    if not f:
        return None
    ic, inm, ip = f.index('證券代號'), f.index('證券名稱'), f.index('收盤價')
    ix = next((i for i, x in enumerate(f) if x.startswith('漲跌(+/-)')), None)
    out = {}
    for r in data:
        c, p = str(r[ic]).strip(), num(r[ip])
        if okcode(c) and p:
            out[c] = (str(r[inm]).strip(), p, ix is not None and 'X' in str(r[ix]))
    return out or None

def tpex(day):
    d2 = f'{day[:4]}%2F{day[4:6]}%2F{day[6:]}'
    j = get(f'https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes?date={d2}&response=json')
    jd = re.sub(r'\D', '', str(j.get('date', '')))
    if jd and jd != day:
        return None
    f, data = table(j, ['代號', '名稱', '收盤'])
    if not f:
        return None
    ic, inm, ip = f.index('代號'), f.index('名稱'), f.index('收盤')
    out = {}
    for r in data:
        c, p = str(r[ic]).strip(), num(r[ip])
        if okcode(c) and p:
            out[c] = (str(r[inm]).strip(), p, False)
    return out or None

def tpex_ex(a, b):
    """櫃買除權息結果：回傳 {code: [[日期, 參考價/前收盤], ...]}"""
    q = lambda d: f'{d[:4]}%2F{d[4:6]}%2F{d[6:]}'
    j = get(f'https://www.tpex.org.tw/www/zh-tw/bulletin/exDailyQ?startDate={q(a)}&endDate={q(b)}&response=json')
    out = {}
    for t in j.get('tables') or []:
        for r in t.get('data') or []:
            g = re.findall(r'\d+', str(r[0]))
            p, rr = num(r[3]), num(r[4])
            if len(g) < 3 or not p or not rr:
                continue
            y = int(g[0]) + (1911 if int(g[0]) < 1911 else 0)
            out.setdefault(str(r[1]).strip(), []).append([y * 10000 + int(g[1]) * 100 + int(g[2]), round(rr / p, 6)])
    return out

def twt48u(store):
    """證交所除權息預告表：記下每檔的配息配股（之後除權息當天用來算還原比例）"""
    try:
        j = get('https://www.twse.com.tw/rwd/zh/exRight/TWT48U?response=json')
    except Exception as e:
        print('TWT48U fail', e)
        return
    fl = [str(x) for x in (j.get('fields') or [])]
    idx = lambda name: next((i for i, x in enumerate(fl) if name in x), -1)
    iC, iS, iR, iP = idx('現金股利'), idx('無償配股率'), idx('現金增資配股率'), idx('現金增資認購價')
    for r in j.get('data') or []:
        code = str(r[1]).strip()
        g = re.findall(r'\d+', str(r[0]))
        if not re.fullmatch(r'[1-9]\d{3}|00\d{2,4}[A-Z]?', code) or len(g) < 3:
            continue
        k = (int(g[0]) + 1911) * 10000 + int(g[1]) * 100 + int(g[2])
        v = lambda i: (num(r[i]) or 0) if i >= 0 else 0
        lst = [e for e in store.get(code, []) if e[0] != k] + [[k, v(iC), v(iS), v(iR), v(iP)]]
        store[code] = sorted(lst)[-6:]

def holidays(store):
    """證交所公告的休市日（網頁判斷今天是否開市用）：抓今年和明年，「開始交易日／最後交易日」是有交易的日子，不算休市"""
    y = dt.datetime.now(TW).year
    closed = set(store.get('closed', []))
    for yy in (y, y + 1):
        try:
            j = get(f'https://www.twse.com.tw/rwd/zh/holidaySchedule/holidaySchedule?date={yy}0101&response=json')
        except Exception as e:
            print('休市日 fail', yy, e); continue
        for r in j.get('data') or []:
            g = re.findall(r'\d+', str(r[0])); name = str(r[1])
            if len(g) < 3 or '開始交易' in name or '最後交易' in name:
                continue
            yv = int(g[0]); yv += 1911 if yv < 1911 else 0
            closed.add(yv * 10000 + int(g[1]) * 100 + int(g[2]))
    store['closed'] = sorted(closed)

def taiex(store):
    """加權指數每日收盤（網頁顯示大盤乖乖用）：第一次抓最近 6 個月，之後每次抓本月和上個月，保留最近 KEEP 天"""
    today = dt.datetime.now(TW).date()
    have = dict(zip(store.get('d', []), store.get('c', [])))
    for k in range(5 if not have else 1, -1, -1):
        y, m = today.year, today.month - k
        while m <= 0:
            m += 12; y -= 1
        try:
            j = get(f'https://www.twse.com.tw/rwd/zh/TAIEX/MI_5MINS_HIST?date={y}{m:02d}01&response=json')
        except Exception as e:
            print('TAIEX fail', e); continue
        fl = [str(x) for x in (j.get('fields') or [])]
        ic = next((i for i, x in enumerate(fl) if '收盤' in x), 4)
        for r in j.get('data') or []:
            g = re.findall(r'\d+', str(r[0])); v = num(r[ic])
            if len(g) >= 3 and v:
                have[(int(g[0]) + 1911) * 10000 + int(g[1]) * 100 + int(g[2])] = v
    d = sorted(have)[-KEEP:]
    store['d'] = d; store['c'] = [have[k] for k in d]

def load(name, default):
    p = os.path.join(D, name)
    return json.load(open(p, encoding='utf-8')) if os.path.exists(p) else default

def save(name, obj):
    with open(os.path.join(D, name), 'w', encoding='utf-8') as fo:
        json.dump(obj, fo, ensure_ascii=False, separators=(',', ':'))

def add_day(px, k, rows, market):
    if k not in px['d']:
        px['d'].append(k)
        for c in px['c']:
            px['c'][c].append(None)
    i = px['d'].index(k)
    for c, (name, p, x) in rows.items():
        if c not in px['c']:
            px['c'][c] = [None] * len(px['d'])
        px['c'][c][i] = p
        px['n'][c] = name
        px['m'][c] = market

def prev_close(px, c, k):
    i = px['d'].index(k)
    for j in range(i - 1, -1, -1):
        if px['c'][c][j] is not None:
            return px['c'][c][j]
    return None

def main():
    os.makedirs(D, exist_ok=True)
    px = load('px.json', {'d': [], 'n': {}, 'm': {}, 'c': {}})
    ex = load('ex.json', {})
    t48 = load('tw48.json', {})
    twt48u(t48)
    today = dt.datetime.now(TW).date()
    boot = not px['d']
    if boot:
        start = today - dt.timedelta(days=150)
    else:
        last = str(px['d'][-1])
        start = dt.date(int(last[:4]), int(last[4:6]), int(last[6:])) + dt.timedelta(days=1)
    day = start
    added = []
    while day <= today:
        if day.weekday() < 5:
            k = day.strftime('%Y%m%d')
            if not (day == today and dt.datetime.now(TW).hour < 14):
                a, b = twse(k), tpex(k)
                print(k, 'TWSE', len(a or {}), 'TPEX', len(b or {}))
                if a and b:
                    kk = int(k)
                    add_day(px, kk, a, '上市')
                    add_day(px, kk, b, '上櫃')
                    added.append(kk)
                    # 上市：除權息當天用預告表的配息配股自己算還原比例
                    for c, (nm, p, x) in a.items():
                        if not x:
                            continue
                        e = next((e for e in t48.get(c, []) if e[0] == kk), None)
                        P = prev_close(px, c, kk)
                        r = None
                        if e and P:
                            r = round((P - e[1] + e[3] * e[4]) / (1 + e[2] + e[3]) / P, 6)
                        lst = [z for z in ex.get(c, []) if z[0] != kk] + [[kk, r]]
                        ex[c] = sorted(lst, key=lambda z: z[0])
        day += dt.timedelta(days=1)
    if not added:
        print('沒有新的交易日資料')
    # 上櫃：查櫃買中心的除權息結果
    if px['d']:
        try:
            a0 = str(px['d'][0] if boot else (added[0] if added else px['d'][-1]))
            for c, lst in tpex_ex(a0, today.strftime('%Y%m%d')).items():
                old = {z[0]: z for z in ex.get(c, [])}
                for z in lst:
                    old[z[0]] = z
                ex[c] = sorted(old.values(), key=lambda z: z[0])
        except Exception as e:
            print('exDailyQ fail', e)
    # 開機時：上市在 2026/10/1 以前用官方結果表事先整理好的比例
    if boot and os.path.exists(os.path.join(D, 'ex_tw.txt')):
        for m in re.finditer(r';([0-9A-Z]+):(\d{8}):([\d.]+)', open(os.path.join(D, 'ex_tw.txt'), encoding='utf-8').read()):
            c, k, r = m.group(1), int(m.group(2)), float(m.group(3))
            if k not in [z[0] for z in ex.get(c, []) if z[1] is not None]:
                ex[c] = sorted([z for z in ex.get(c, []) if z[0] != k] + [[k, r]], key=lambda z: z[0])
    # 只留最近 KEEP 個交易日
    if len(px['d']) > KEEP:
        cut = len(px['d']) - KEEP
        px['d'] = px['d'][cut:]
        for c in list(px['c']):
            px['c'][c] = px['c'][c][cut:]
    first = px['d'][0] if px['d'] else 0
    for c in list(px['c']):
        if all(v is None for v in px['c'][c]):
            del px['c'][c]; px['n'].pop(c, None); px['m'].pop(c, None)
    for c in list(ex):
        ex[c] = [z for z in ex[c] if z[0] > first]
        if not ex[c]:
            del ex[c]
    save('px.json', px); save('ex.json', ex); save('tw48.json', t48)
    idx = load('idx.json', {'d': [], 'c': []}); taiex(idx); save('idx.json', idx)
    hol = load('holidays.json', {'closed': []}); holidays(hol); save('holidays.json', hol)
    print('完成：', len(px['d']), '個交易日，', len(px['c']), '檔，最後一天', px['d'][-1] if px['d'] else '-')

if __name__ == '__main__':
    main()
