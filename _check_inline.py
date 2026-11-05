import re, hashlib, os
sys_path = r"c:/MarcoAI/AICode/MarcoAPI"
html_path = os.path.join(sys_path, "UI", "StrategyDashboardOffline.html")
vendor = os.path.join(sys_path, "UI", "vendor")

html = open(html_path, encoding="utf-8").read()

def extract(name):
    # 内联块：/* inlined vendor lib: NAME */\n ... \n</script>
    m = re.search(r"/\* inlined vendor lib: " + re.escape(name) + r" \*/\n(.*?)\n</script>", html, re.S)
    if not m:
        return None
    return m.group(1).replace("<\\/script>", "</script>")

for f in ["chart.umd.js", "lightweight-charts.standalone.production.js"]:
    orig = open(os.path.join(vendor, f), encoding="utf-8").read()
    inline = extract(f)
    if inline is None:
        print(f"{f}: 未在 HTML 中找到内联块!")
        continue
    print(f"{f}: 原始字节={len(orig)} 内联还原字节={len(inline)} 一致={orig == inline}")
    if orig != inline:
        # 找第一个差异
        for i in range(min(len(orig), len(inline))):
            if orig[i] != inline[i]:
                print(f"   首个差异 @ {i}: orig={orig[i-30:i+30]!r} inline={inline[i-30:i+30]!r}")
                break
