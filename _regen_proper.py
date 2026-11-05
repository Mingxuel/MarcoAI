import sys, time
sys.path.insert(0, r"c:/MarcoAI/AICode/MarcoAPI")
import StrategyUI as S

t0 = time.time()
out = S.GENERATE_STRATEGY_UI_OFFLINE(open_browser=False)
print("OUTPUT:", out, " took", round(time.time() - t0, 1), "s")

# 校验：图表库是否真的被内联进 HTML
html = open(out, encoding="utf-8").read()
for key in ["chart.umd.js", "lightweight-charts.standalone.production.js"]:
    print(f"内联 {key}:", "有" if ("inlined vendor lib: " + key) in html else "缺失!!!")
