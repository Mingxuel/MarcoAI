import re
html = open('AICode/MarcoAPI/UI/StrategyDashboardOffline.html', encoding='utf-8').read()
ok = 0
for m in re.finditer('class="kline-5m-col">', html):
    seg = html[m.start():m.start() + 260]
    has_sub = 'kline-subhead' in seg
    has_5m = ('id="kline-5m"' in seg) or ('id="top-kline-5m"' in seg) or ('id="detail-kline-5m"' in seg)
    print('subhead:', has_sub, '5m-container:', has_5m)
    ok += 1 if (has_sub and has_5m) else 0
print('valid 5m-col blocks:', ok, '/ 3')
