html = open('AICode/MarcoAPI/UI/StrategyDashboardOffline.html', encoding='utf-8').read()
checks = {
    'kline-split x3': html.count('class="kline-split"') == 3,
    'kline-5m-col x3': html.count('class="kline-5m-col"') == 3,
    'CSS .kline-split': '.kline-split {' in html,
    'CSS .kline-5m-col': '.kline-5m-col {' in html,
    'daily width:auto': '#kline, #top-kline { width: auto;' in html,
    'detail width:auto': '#detail-kline { width: auto;' in html,
    'subhead inside 5m-col': 'kline-5m-col"><div class="kline-subhead"' in html,
    'no old stacked 5m-after-kline': 'id="kline"></div>\n        <div class="kline-subhead"' not in html,
}
for k, v in checks.items():
    print(('OK ' if v else 'XX '), k)
