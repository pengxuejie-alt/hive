import os
import json
import google.generativeai as genai
from polygon import RESTClient
from supabase import create_client
from datetime import datetime, timezone

# --- 配置 ---
AI_MODEL_NAME = "gemini-3-flash-preview"
client_poly = RESTClient(api_key=os.environ.get("POLYGON_KEY"))
supabase = create_client(os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY"))
genai.configure(api_key=os.environ.get("GEMINI_KEY"))
model = genai.GenerativeModel(AI_MODEL_NAME)

def calculate_roi_hr(d):
    """计算每小时收益率以对齐生命周期"""
    start_time = datetime.fromisoformat(d['created_at'].replace('Z', '+00:00'))
    hours_alive = (datetime.now(timezone.utc) - start_time).total_seconds() / 3600
    if hours_alive < 0.1: return 0, hours_alive
    
    net_profit = d['balance'] - d['initial_balance']
    roi_total = (net_profit / d['initial_balance']) if d['initial_balance'] > 0 else 0
    return (roi_total / hours_alive), hours_alive

def natural_selection():
    """物竞天择：自动淘汰末位表现者"""
    print("--- 启动物竞天择程序 ---")
    res = supabase.table("drones").select("*").eq("type", "soldier").execute()
    soldiers = res.data
    
    if len(soldiers) < 5: 
        print("兵蜂数量不足，暂不启动淘汰。")
        return

    # 1. 筛选出已过“新手保护期”（存活超过12小时）的蜂
    candidates = []
    for s in soldiers:
        roi_hr, age = calculate_roi_hr(s)
        if age > 12: # 12小时观察期
            s['roi_hr'] = roi_hr
            candidates.append(s)
    
    if not candidates: return

    # 2. 按 ROI/hr 排序，找出末位 30%
    candidates.sort(key=lambda x: x['roi_hr'])
    kill_count = max(1, int(len(candidates) * 0.3))
    losers = candidates[:kill_count]

    for l in losers:
        if l['roi_hr'] < 0: # 只有亏损的才会被自动淘汰
            print(f"💀 淘汰劣等蜂: {l['name']} (ROI/hr: {l['roi_hr']:.4%})")
            supabase.table("drones").delete().eq("id", l['id']).execute()

def patrol():
    """常规巡检与交易决策"""
    drones = supabase.table("drones").select("*").execute().data
    for d in drones:
        try:
            # (此处保留之前的 fetch_data 和 Gemini 决策逻辑...)
            # 简化版逻辑演示：
            print(f"🐝 {d['name']} 正在执行任务...")
            # ... 决策与数据库更新 ...
        except Exception as e:
            print(f"Error in {d['name']}: {e}")

if __name__ == "__main__":
    # 执行顺序：先干活，再根据战果优胜劣汰
    patrol()
    natural_selection()