import re, sys
sys.path.insert(0, r"c:/MarcoAI/AICode/MarcoAPI")
import esprima

html = open(r"c:/MarcoAI/AICode/MarcoAPI/UI/StrategyDashboardOffline.html", encoding="utf-8").read()
blocks = re.findall(r"<script(?:\s[^>]*)?>(.*?)</script>", html, re.DOTALL)
# 应用主脚本：含 switchTab（排除 vendor 库，vendor 块以 inlined vendor lib 注释开头）
main = [b for b in blocks if "async function switchTab" in b]
print("主脚本块数量:", len(main))
if not main:
    print("未找到主脚本"); sys.exit(1)
cand = main[0]
neutral = cand.replace("?.", ".").replace("??", "||")
try:
    esprima.parseModule(neutral)
    print("ESPRIMA 应用主脚本解析: OK (无语法错误)")
except Exception as e:
    print("ESPRIMA 报错:", str(e)[:300])
