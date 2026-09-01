"""
SZ200 入场时机分析 - 每月5~10次入场，找出最佳策略
"""
import os
import pandas as pd
import numpy as np
import sys
from pathlib import Path

# 项目根加入 sys.path，保证直接运行本脚本时也能导入 AICode.* 模块
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from AICode.MarcoAPI.Update.Path import PATH_AIDATA

# ==================== 1. 读取数据 ====================
def load_data():
    file_path = os.path.join(PATH_AIDATA(), "1D_MOTION")
    df = pd.read_csv(
        file_path, sep='|', header=None,
        names=['date', 'open_ratio', 'high_ratio', 'low_ratio', 'close_ratio', 'volume', 'amount']
    )
    df['date'] = pd.to_datetime(df['date'], format='%Y%m%d')
    df['month'] = df['date'].dt.to_period('M')
    return df

# ==================== 2. 构造衍生指标 ====================
def build_features(df):
    df = df.copy()
    df['close_ma5'] = df['close_ratio'].rolling(5, min_periods=1).mean()
    df['close_ma10'] = df['close_ratio'].rolling(10, min_periods=1).mean()
    df['close_ma20'] = df['close_ratio'].rolling(20, min_periods=1).mean()
    df['deviation_5'] = df['close_ratio'] - df['close_ma5']
    df['deviation_10'] = df['close_ratio'] - df['close_ma10']
    df['deviation_20'] = df['close_ratio'] - df['close_ma20']
    # 连跌天数
    df['is_down'] = (df['close_ratio'] < 0).astype(int)
    down_groups = (df['is_down'] == 0).cumsum()
    df['consec_down'] = df['is_down'].groupby(down_groups).cumsum()
    # 连跌幅度
    df['down_streak_ret'] = 0.0
    for i in range(1, 11):
        df[f'prev_{i}d_close'] = df['close_ratio'].shift(i)
    for i in range(len(df)):
        cd = int(df.iloc[i]['consec_down'])
        if cd >= 2:
            s = 0.0
            for j in range(1, cd+1):
                if i - j >= 0:
                    s += df.iloc[i-j]['close_ratio']
            df.iloc[i, df.columns.get_loc('down_streak_ret')] = s
    # 量比
    df['vol_ma5'] = df['volume'].rolling(5, min_periods=1).mean()
    df['vol_ma10'] = df['volume'].rolling(10, min_periods=1).mean()
    df['vol_ratio_5'] = df['volume'] / df['vol_ma5']
    df['vol_ratio_10'] = df['volume'] / df['vol_ma10']
    # 振幅
    df['amplitude'] = df['high_ratio'] - df['low_ratio']
    # 5日动量
    df['mom_5d'] = df['close_ratio'].rolling(5, min_periods=1).sum()
    # 涨跌强度
    df['up_power'] = df['close_ratio'] / df['amplitude'].clip(lower=0.01)
    # 尾盘变化 (close vs open)
    df['close_vs_open'] = df['close_ratio'] - df['open_ratio']
    # 日内最大不利波动
    df['max_adverse'] = df['low_ratio']
    # 相对强弱
    df['rs_5d'] = df['close_ratio'] / df['close_ma5'].clip(lower=0.001)
    return df

# ==================== 3. 定义策略信号 ====================
def calc_signals(df):
    df = df.copy()
    # A. 超跌反弹
    df['sig_over_sold'] = -df['close_ratio']
    # B. 动量追涨
    df['sig_momentum'] = df['close_ratio']
    # C. 连跌抄底
    df['sig_consec_down'] = df['consec_down'] * (df['close_ratio'] < 0).astype(int)
    # D. 缩量低吸
    df['sig_vol_shrink'] = -df['close_ratio'] + (1.0 - df['vol_ratio_5'].clip(0, 3)) * 0.5
    # E. 均线回归
    df['sig_ma_reverse'] = -df['deviation_5']
    # F. 高弹性
    df['sig_high_amp'] = df['amplitude']
    # G. 连跌+缩量 (组合)
    df['sig_combo1'] = -df['close_ratio'] * 0.4 + df['consec_down'] * 0.3 + (1.0 - df['vol_ratio_5'].clip(0, 3)) * 0.3
    # H. 尾盘走强 (低开高走)
    df['sig_close_strength'] = df['close_vs_open'] - df['close_ratio'] * 0.3
    # I. 多因子综合
    df['sig_multi'] = (
        -df['close_ratio'] * 0.25
        + (df['consec_down'] * (df['close_ratio'] < 0).astype(int)) * 0.20
        + (1.0 - df['vol_ratio_5'].clip(0, 3)) * 0.15
        - df['deviation_5'] * 0.15
        + df['close_vs_open'] * 0.15
        + df['amplitude'] * 0.10
    )
    return df

# ==================== 4. 计算未来N日收益 ====================
def calc_forward_returns(df, horizons=[1, 2, 3, 5, 10, 20]):
    df = df.copy()
    for h in horizons:
        # 未来h日的累计收益
        fwd_col = f'fwd_{h}d'
        # 使用滚动和
        roll_sum = df['close_ratio'].shift(-1).rolling(h, min_periods=0).sum()
        df[fwd_col] = roll_sum.shift(1 - h)
        # 未来h天，从第1天开始累计
        vals = df['close_ratio'].values
        fwd_vals = np.full(len(vals), np.nan)
        for i in range(len(vals) - 1):
            end = min(i + 1 + h, len(vals))
            fwd_vals[i] = np.sum(vals[i+1:end])
        df[fwd_col] = fwd_vals
    return df

# ==================== 5. 回测单策略 ====================
def backtest_strategy(df, signal_col, top_n=8, min_samples=5):
    results = {}
    df_valid = df.dropna(subset=[signal_col]).copy()
    
    monthly_records = []
    
    for month, group in df_valid.groupby('month'):
        if len(group) < min_samples:
            continue
        top_days = group.nlargest(top_n, signal_col)
        for _, day in top_days.iterrows():
            record = {
                'date': day['date'],
                'month': month,
                'signal': day[signal_col],
                'close_ratio': day['close_ratio'],
            }
            for h in [1, 2, 3, 5, 10, 20]:
                col = f'fwd_{h}d'
                record[f'fwd_{h}d'] = day[col]
            monthly_records.append(record)
    
    if not monthly_records:
        return {}, pd.DataFrame()
    
    rec_df = pd.DataFrame(monthly_records)
    
    for h in [1, 2, 3, 5, 10, 20]:
        col = f'fwd_{h}d'
        key = f'{h}d'
        ret_series = rec_df[col].dropna()
        arr = ret_series.values
        if len(arr) == 0:
            continue
        wins = arr[arr > 0]
        losses = arr[arr < 0]
        std = np.std(arr, ddof=0) if len(arr) > 1 else 0.0001
        results[key] = {
            'count': len(arr),
            'win_rate': round(len(wins) / len(arr) * 100, 2),
            'avg_return': round(np.mean(arr), 4),
            'median_return': round(np.median(arr), 4),
            'std_return': round(std, 4),
            'avg_win': round(np.mean(wins), 4) if len(wins) > 0 else 0,
            'avg_loss': round(np.mean(losses), 4) if len(losses) > 0 else 0,
            'max_return': round(np.max(arr), 4),
            'max_loss': round(np.min(arr), 4),
            'sharpe': round(np.mean(arr) / std, 4),
            'cum_return': round(np.sum(arr), 4),
            'profit_factor': round(abs(np.sum(wins) / np.sum(losses)), 4) if len(losses) > 0 and np.sum(losses) != 0 else float('inf'),
        }
    
    return results, rec_df

# ==================== 6. 主流程 ====================
def main():
    print("=" * 70)
    print("SZ200 入场时机分析 - 每月5~10次入场")
    print("=" * 70)
    
    df = load_data()
    print(f"\n[数据范围]: {df['date'].min().strftime('%Y-%m-%d')} ~ {df['date'].max().strftime('%Y-%m-%d')}")
    print(f"[总交易天数]: {len(df)}")
    print(f"[覆盖月份]: {df['month'].nunique()} 个月")
    
    df = build_features(df)
    print("\n[OK] 衍生指标构建完成")
    
    df = calc_signals(df)
    print("[OK] 信号策略计算完成")
    
    df = calc_forward_returns(df)
    print("[OK] 未来收益计算完成")
    
    # 策略列表
    strategies = {
        'A.超跌反弹': 'sig_over_sold',
        'B.动量追涨': 'sig_momentum',
        'C.连跌抄底': 'sig_consec_down',
        'D.缩量低吸': 'sig_vol_shrink',
        'E.均线回归': 'sig_ma_reverse',
        'F.高弹性': 'sig_high_amp',
        'G.连跌缩量': 'sig_combo1',
        'H.尾盘走强': 'sig_close_strength',
        'I.多因子综合': 'sig_multi',
    }
    
    all_summaries = []
    
    for top_n in [5, 8, 10]:
        print(f"\n{'=' * 70}")
        print(f"[每月入场 {top_n} 次]")
        print(f"{'=' * 70}")
        
        all_results = []
        for name, sig_col in strategies.items():
            stats, rec_df = backtest_strategy(df, sig_col, top_n=top_n)
            for horizon_key in ['1d', '2d', '3d', '5d', '10d', '20d']:
                if horizon_key in stats:
                    s = stats[horizon_key]
                    all_results.append({
                        '策略': name,
                        '持仓': horizon_key,
                        '入场次数': s['count'],
                        '胜率%': s['win_rate'],
                        '平均收益%': s['avg_return'],
                        '平均盈利%': s['avg_win'],
                        '平均亏损%': s['avg_loss'],
                        '最大收益%': s['max_return'],
                        '最大亏损%': s['max_loss'],
                        '夏普': s['sharpe'],
                        '累计收益%': s['cum_return'],
                        '盈亏比': s['profit_factor'],
                    })
        
        result_df = pd.DataFrame(all_results)
        
        for horizon in ['1d', '2d', '3d', '5d', '10d', '20d']:
            subset = result_df[result_df['持仓'] == horizon].sort_values('累计收益%', ascending=False)
            print(f"\n  [持仓 {horizon} 按累计收益排序]:")
            print(f"  {'策略':<10} {'入场':>5} {'胜率%':>7} {'均收益%':>8} {'均盈利%':>8} {'均亏损%':>8} {'累计收益%':>8} {'夏普':>6}")
            print(f"  {'-'*65}")
            for _, row in subset.iterrows():
                print(f"  {row['策略']:<10} {int(row['入场次数']):>5} {row['胜率%']:>7.1f} {row['平均收益%']:>8.2f} {row['平均盈利%']:>8.2f} {row['平均亏损%']:>8.2f} {row['累计收益%']:>8.2f} {row['夏普']:>6.2f}")
        
        # 保存该top_n下的最佳结果
        for horizon in ['1d', '2d', '3d', '5d', '10d']:
            subset = result_df[result_df['持仓'] == horizon]
            if len(subset) > 0:
                best = subset.loc[subset['累计收益%'].idxmax()]
                all_summaries.append({
                    '每月入场': top_n,
                    '持仓': horizon,
                    '最佳策略': best['策略'],
                    '胜率%': best['胜率%'],
                    '平均收益%': best['平均收益%'],
                    '累计收益%': best['累计收益%'],
                    '夏普': best['夏普'],
                    '盈亏比': best['盈亏比'],
                    '入场次数': int(best['入场次数']),
                })
    
    # ==================== 7. 综合排名 ====================
    print(f"\n{'=' * 70}")
    print("[综合最佳入场策略排名]")
    print(f"{'=' * 70}")
    
    summary_df = pd.DataFrame(all_summaries)
    # 按累计收益降序
    summary_df = summary_df.sort_values('累计收益%', ascending=False)
    
    print(f"\n  {'排名':>3} {'每月入场':>8} {'持仓':>5} {'最佳策略':<10} {'胜率%':>7} {'均收益%':>8} {'累计收益%':>8} {'夏普':>6} {'盈亏比':>6}")
    print(f"  {'-'*68}")
    for rank, (_, row) in enumerate(summary_df.iterrows(), 1):
        print(f"  {rank:>3} {row['每月入场']:>8} {row['持仓']:>5} {row['最佳策略']:<10} {row['胜率%']:>7.1f} {row['平均收益%']:>8.2f} {row['累计收益%']:>8.2f} {row['夏普']:>6.2f} {row['盈亏比']:>6.2f}")
    
    print(f"\n{'=' * 70}")
    print("[结论与建议]")
    print(f"{'=' * 70}")
    
    return df, summary_df

if __name__ == "__main__":
    df, summary = main()
