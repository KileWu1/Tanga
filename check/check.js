// 網頁全市場檢查：用網頁本身的程式把每一檔跑一遍，有錯誤就讓這次執行失敗（GitHub 會寄信通知）
const {JSDOM, VirtualConsole} = require('jsdom');
const fs = require('fs');
const read = p => { try { return fs.readFileSync(p, 'utf8'); } catch (e) { return null; } };
const files = {};
['data/px.json', 'data/stats.txt', 'data/ex.json', 'data/hist/ex.json', 'data/hist/ex_recent.json', 'data/hist/cap.json', 'data/stats_meta.json', 'data/idx.json'].forEach(p => files[p] = read(p));
const hard = [], warn = [];
(async () => {
  const vc = new VirtualConsole();
  vc.on('jsdomError', e => hard.push('網頁程式錯誤：' + (e.message || e)));
  const dom = new JSDOM(read('index.html'), {runScripts: 'dangerously', pretendToBeVisual: true, virtualConsole: vc, beforeParse(w){
    w.fetch = async u => { const t = files[u.split('?')[0]]; if (t == null) throw new Error('沒有檔案 ' + u); return {json: async () => JSON.parse(t), text: async () => t}; };
  }});
  const w = dom.window, $ = id => w.document.getElementById(id);
  const px = JSON.parse(files['data/px.json']);
  const codes = Object.keys(px.c).filter(c => px.c[c][px.c[c].length - 1] != null);
  if (files['data/idx.json']) codes.push('TAIEX');
  let ok = 0;
  for (const c of codes){
    $('code').value = c; $('auto').click();
    for (let i = 0; i < 400; i++){ await new Promise(r => setTimeout(r, 5)); if (!$('auto').disabled && !/抓取中/.test($('autoMsg').textContent)) break; }
    const err = $('err').hidden ? null : $('err').textContent, txt = $('summary').textContent, name = (px.n[c] || '') + ' ' + c;
    if (err){ (/交易日數不足 10 天/.test(err) ? warn : hard).push(`${name}：${err}`); continue; }
    if (!txt.trim()) { hard.push(`${name}：畫面是空白的`); continue; }
    if (/NaN|undefined|Infinity/.test(txt + $('tbl').textContent)) { hard.push(`${name}：畫面出現 NaN／undefined`); continue; }
    const cl = +((txt.match(/收盤 ([\d.]+) 元，離5日線/) || [])[1]), p10 = +((txt.match(/第一回落區（強勢回測，預估10日線附近）：明天約 ([\d.]+)/) || [])[1]);
    if (cl && p10 && Math.abs(p10 / cl - 1) > 0.3) warn.push(`${name}：第一回落區 ${p10} 離收盤 ${cl} 超過 30%，可能有沒還原的減資或分割`);
    ok++;
  }
  const last = px.d[px.d.length - 1];
  const now = new Date(Date.now() + 8 * 3600e3), today = now.getUTCFullYear() * 10000 + (now.getUTCMonth() + 1) * 100 + now.getUTCDate();
  if (now.getUTCDay() >= 1 && now.getUTCDay() <= 5 && now.getUTCHours() >= 18 && last !== today) warn.push(`資料最新日期是 ${last}，今天（${today}）的收盤還沒更新（若今天休市可忽略）`);
  const out = [`## 網頁全市場檢查`, `資料最新日期：${last}；檢查 ${codes.length} 檔，正常 ${ok} 檔。`, '',
    `### 錯誤（${hard.length}）`, ...hard.slice(0, 100).map(x => '- ' + x), '', `### 提醒（${warn.length}）`, ...warn.slice(0, 100).map(x => '- ' + x)].join('\n');
  console.log(out);
  if (process.env.GITHUB_STEP_SUMMARY) fs.appendFileSync(process.env.GITHUB_STEP_SUMMARY, out + '\n');
  process.exit(hard.length ? 1 : 0);
})().catch(e => { console.error('檢查程式本身出錯', e); process.exit(1); });
