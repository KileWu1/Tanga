# 乖乖值計算器：用 data/hist 的全部歷史收盤價，重算每檔股性，寫成 data/stats.txt
# 算法與 2026/10/1 版完全相同（已逐檔比對 1,788 檔、8 個欄位全部一致）
import json, os, sys, glob
import numpy as np
import pandas as pd

H = os.path.join('data', 'hist')

def load_hist(until=None):
    days, cols = [], {}
    for f in sorted(glob.glob(os.path.join(H, '[0-9]' * 6 + '.json'))):
        j = json.load(open(f, encoding='utf-8'))
        for i, k in enumerate(j['d']):
            if until and k > until:
                continue
            days.append(k)
            for c, arr in j['c'].items():
                v = arr[i]
                if v is not None:
                    cols.setdefault(c, []).append((k, v))
    ex = json.load(open(os.path.join(H, 'ex.json'), encoding='utf-8')) if os.path.exists(os.path.join(H, 'ex.json')) else {}
    return sorted(set(days)), cols, ex

def kk(a, b):
    v = (a / b - 1) * 100
    return np.trunc(v * 10 + np.where(v >= 0, 1e-9, -1e-9)) / 10

def roll(x, n):
    return pd.Series(x).rolling(n).mean().values

def one(rows, events):
    ks = [k for k, _ in rows]; close = np.array([v for _, v in rows], float)
    fx = np.ones(len(ks)); pos = {k: i for i, k in enumerate(ks)}
    for k, r in events:                        # 除權息當天的比例；當天以前的價格乘上之後所有比例
        if r is not None and k in pos:
            fx[pos[k]] = r
    cum = np.cumprod(fx[::-1])[::-1]
    ac = close * np.append(cum[1:], 1.0)
    ma5, ma10, ma20 = roll(ac, 5), roll(ac, 10), roll(ac, 20)
    with np.errstate(invalid='ignore', divide='ignore'):
        s, m = kk(ma5, ma10), kk(ma10, ma20)
        ret = pd.Series(ac).pct_change().abs().values
    for j in np.where(ret > 0.11)[0]:          # 跳空超過 11%（未還原的減資、分割等）：前1天到後20天不算
        s[max(0, j - 1):j + 21] = np.nan; m[max(0, j - 1):j + 21] = np.nan
    days = int(np.sum(~np.isnan(s)))
    if days == 0:
        return None
    S = np.nanquantile(s, .97)
    S2 = np.nanquantile(m, .97) if np.any(~np.isnan(m)) else np.nan
    R, a = [], None
    for i, v in enumerate(s):
        if not np.isnan(v) and v > 0:
            if a is None: a = i
        elif a is not None:
            R.append((a, i - 1)); a = None
    if a is not None: R.append((a, len(s) - 1))
    pk = [i + int(np.nanargmax(s[i:j + 1])) for i, j in R]
    pk = [p for p in pk if s[p] >= 0.5 * S and p + 10 < len(s)]
    vals = [s[p] for p in pk]
    dd = [np.nanmin(ac[p + 1:p + 11]) / ac[p] - 1 for p in pk]
    b = [float(np.any(ac[p + 1:p + 11] <= ma10[p + 1:p + 11])) for p in pk]
    return dict(S=S, S2=S2, n=len(vals), M=np.median(vals) if vals else np.nan, P75=np.percentile(vals, 75) if vals else np.nan,
                dd=np.median(dd) if dd else np.nan, b10=np.mean(b) * 100 if b else np.nan, days=days)

def fmt(code, r):
    f = lambda x, k: '' if x is None or np.isnan(x) else str(int(round(x * k)))
    return f'{code}:' + ','.join([f(r['S'], 10), f(r['S2'], 10), str(r['n']), f(r['M'], 10), f(r['P75'], 10),
                                  f(r['dd'], 1000), f(r['b10'], 1), str(r['days'])])

def build(until=None):
    days, cols, ex = load_hist(until)
    last = days[-1]
    out = []
    for c in sorted(cols):
        rows = cols[c]
        if rows[-1][0] != last:              # 只算最後一天還有交易的
            continue
        r = one(rows, ex.get(c, []))
        if r and r['days'] >= 500 and r['n'] >= 8:
            out.append(fmt(c, r))
    return days, out

if __name__ == '__main__':
    until = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[1] == '--check' else None
    days, out = build(until)
    print('資料期間', days[0], '~', days[-1], '共', len(days), '天；有股性參考', len(out), '檔')
    if until:                                 # 驗證：跟 2026/10/1 版比對
        old = {x.split(':')[0]: x for x in open('data/stats_20261001.txt', encoding='utf-8').read().strip(';').split(';')}
        new = {x.split(':')[0]: x for x in out}
        both = set(old) & set(new)
        same = sum(old[c] == new[c] for c in both)
        print('比對：舊版', len(old), '檔，新版', len(new), '檔，共同', len(both), '檔，完全一致', same, '檔')
        for c in [c for c in both if old[c] != new[c]][:20]:
            print('  不同', old[c], '|', new[c])
    else:
        if days[0] > 20210201 or len(days) < 1000:
            print('歷史資料還不夠（補抓還沒完成），先不更新股性'); sys.exit(0)
        with open('data/stats.txt', 'w', encoding='utf-8') as fo:
            fo.write(';' + ';'.join(out) + ';')
        json.dump({'from': days[0], 'to': days[-1], 'count': len(out)}, open('data/stats_meta.json', 'w'))
        print('已更新 data/stats.txt')
