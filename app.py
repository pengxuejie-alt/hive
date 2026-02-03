import streamlit as st
import pandas as pd
from supabase import create_client
import google.generativeai as genai
import json
import requests
from datetime import datetime, timezone, timedelta
import pytz
from polygon import RESTClient

# --- 核心配置 ---
AI_MODEL_NAME = "gemini-3-flash-preview"
st.set_page_config(page_title="Hive | 虎之眼演化实验室", layout="wide", page_icon="🐝")

try:
    supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
    genai.configure(api_key=st.secrets["GEMINI_KEY"])
    queen_ai = genai.GenerativeModel(AI_MODEL_NAME)
    poly_client = RESTClient(api_key=st.secrets["POLYGON_KEY"])
except Exception as e:
    st.error(f"连接失败: {e}"); st.stop()

# --- 远程触发逻辑 ---
def trigger_worker():
    try:
        token = st.secrets["GITHUB_TOKEN"].strip()
        repo = st.secrets["GITHUB_REPO"].strip()
        headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
        url = f"https://api.github.com/repos/{repo}/actions/workflows/hive_cycle.yml/dispatches"
        res = requests.post(url, headers=headers, json={"ref": "main"})
        return res.status_code == 204
    except: return False

# --- 资产实时估值逻辑 ---
def get_live_asset_value(positions):
    total_mkt_val = 0.0
    details = []
    if not positions: return 0.0, []
    
    for symbol, qty in positions.items():
        try:
            # 识别期权 (格式如 O:FCX260116C00050000)
            if symbol.startswith("O:"):
                px = poly_client.get_last_trade(symbol).price
                mv = float(qty) * float(px) * 100 # 期权张数 * 价格 * 100
            else:
                px = poly_client.get_snapshot_ticker("stocks", symbol).last_trade.p
                mv = float(qty) * float(px)
            
            total_mkt_val += mv
            details.append({"标的": symbol, "数量": qty, "现价": f"${px:.2f}", "市值": f"${mv:.2f}"})
        except:
            details.append({"标的": symbol, "数量": qty, "现价": "代码无效", "市值": "0.0"})
    return total_mkt_val, details

def get_market_active_hours(created_at_str):
    et_tz = pytz.timezone('US/Eastern')
    if not created_at_str: return 0.1
    start_dt = datetime.fromisoformat(created_at_str.replace('Z', '+00:00')).astimezone(et_tz)
    now_et = datetime.now(et_tz)
    active_hours = 0.0
    curr = start_dt
    while curr < now_et:
        if curr.weekday() < 5:
            ot, ct = curr.replace(hour=9, minute=30, second=0), curr.replace(hour=16, minute=0, second=0)
            if ot <= curr <= ct: active_hours += 0.5
        curr += timedelta(minutes=30)
    return max(active_hours, 0.1)

# --- 界面 ---
st.title("🐝 Hive 蜂巢：虎之眼演化实验室")

with st.sidebar:
    et_now = datetime.now(pytz.timezone('US/Eastern'))
    st.header(f"🕒 ET: {et_now.strftime('%H:%M:%S')}")
    if st.button("🚀 立即放飞所有蜜蜂"):
        if trigger_worker(): st.success("已起飞！")
        else: st.error("放飞失败")

tabs = st.tabs(["👑 蜂后赋能", "🏆 演化排行榜", "🧬 杂交实验室", "⚙️ 系统维护"])

# --- Tab 0: 孵化 ---
with tabs[0]:
    instruction = st.text_area("蜂后指令 (注入专业基因):")
    if st.button("执行孵化", type="primary"):
        with st.spinner("蜂后编码中..."):
            prompt = f"设计兵蜂。分配专业期权策略逻辑。返回JSON列表：[{{'name':'代号','focus':'option','portfolio':['代码'],'logic':'逻辑基因','persona':'性格','balance':10000,'initial_balance':10000,'memory':'等待开盘'}}]。指令：{instruction}"
            res = queen_ai.generate_content(prompt)
            for d in json.loads(res.text.strip().replace("```json", "").replace("```", "").strip()):
                d['peak_balance'] = d.get('balance', 10000.0)
                supabase.table("drones").insert(d).execute()
            st.rerun()

# --- Tab 1: 排行榜 (含单体修复) ---
with tabs[1]:
    res = supabase.table("drones").select("*").execute()
    if res.data:
        all_d = []
        for d in res.data:
            age = get_market_active_hours(d.get('created_at'))
            cash = float(d.get('balance') or 0)
            mkt_val, pos_details = get_live_asset_value(d.get('positions', {}))
            total_assets = cash + mkt_val
            initial = float(d.get('initial_balance') or 10000)
            roi = ((total_assets - initial) / initial * 100)
            peak = max(float(d.get('peak_balance') or 0), total_assets)
            mdd = max(0.0, (peak - total_assets) / peak * 100) if peak > 0 else 0
            
            d.update({'age_active': age, 'roi': roi, 'total_assets': total_assets, 
                      'mkt_val': mkt_val, 'pos_details': pos_details, 'mdd': mdd, 'fitness': (roi/age) / (mdd + 1)})
            all_d.append(d)

        for d in sorted(all_d, key=lambda x: x['fitness'], reverse=True):
            with st.expander(f"🐝 {d['name']} | 资产: ${d['total_assets']:,.2f} | ROI: {d['roi']:.2f}%"):
                c1, c2, c3 = st.columns(3)
                c1.metric("现金", f"${d['balance']:,.0f}")
                c2.metric("持仓市值", f"${d['mkt_val']:,.2f}")
                c3.metric("最大回撤", f"{d['mdd']:.2f}%")
                
                if d['pos_details']: st.table(pd.DataFrame(d['pos_details']))
                st.info(f"**🧠 经验记录:** {d.get('memory')}")
                
                # 手术区
                sc1, sc2, sc3 = st.columns(3)
                if sc1.button("🩹 单独重置账本", key=f"fix_{d['id']}"):
                    supabase.table("drones").update({"balance": 10000.0, "positions": {}, "peak_balance": 10000.0}).eq("id", d["id"]).execute()
                    st.success(f"{d['name']} 账本已重置，记忆已保留！"); st.rerun()
                if sc2.button("🗑️ 淘汰", key=f"del_{d['id']}"):
                    supabase.table("drones").delete().eq("id", d["id"]).execute(); st.rerun()
                if sc3.button("📜 日志", key=f"log_{d['id']}"):
                    st.json(d.get('logs', []))

# --- Tab 3: 系统维护 ---
with tabs[3]:
    if st.button("🩹 全体账本无损重置"):
        supabase.table("drones").update({"balance": 10000.0, "positions": {}, "peak_balance": 10000.0}).neq("id", -1).execute()
        st.success("全体修正完成！"); st.rerun()