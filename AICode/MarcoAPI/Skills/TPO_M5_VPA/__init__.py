"""TPO_M5_VPA 技能：基于 TARGET_5M 高低点折线 + 5M 实际 K 线的威科夫量价趋势分析。

导入示例::
    from AICode.MarcoAPI.Skills.TPO_M5_VPA import vpa
    print(vpa.print_report("20260930"))
"""
from .vpa import (
    build_zigzag, volume_stats, interpret, analyze_stock, print_report,
)

__all__ = ["build_zigzag", "volume_stats", "interpret", "analyze_stock", "print_report"]
