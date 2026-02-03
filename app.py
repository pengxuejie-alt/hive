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
st.set_page_config(page_title="Hive | 蜂巢演化实验室", layout="wide", page_icon="🐝")

try:
    supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
    genai.configure(api_key=st.secrets["GEMINI_KEY"])
    queen_ai = genai.GenerativeModel(AI_MODEL_NAME)
    # 前端也需要 Polygon 权限来计算实时市值
    poly_client = RESTClient(api_key=st.secrets["POLYGON_KEY"])
except Exception as e:
    st.error(f"连接失败: {e}"); st.stop()

# --- 远程放飞逻辑 (经典 Token 认证) ---
def trigger_worker():
    try:
        token = st.secrets["GITHUB_TOKEN"].strip()
        repo = st.secrets["GITHUB_REPO"].strip()
        headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
        url = f"https://api.github.com/repos/{repo}/actions/workflows/hive_cycle.yml/dispatches"
        res = requests.post(url, headers=headers, json={"ref": "main"})
        return res.status_code == 204
    except: return False

# --- 资产估值逻辑 ---
def get_live_asset_value(positions, current_cash):
    """计算持仓总市值"""
    total_market_value = 0.0
    details = []
    if not positions:
        return 0.0, []
        
    for symbol, qty in positions.items():
        try:
            # 判断是股票还是期权
            if "O:" in symbol or len(symbol) > 10: # 简单的期权识别
                px = poly_client.get_last_trade(symbol).price
            else:
                px = poly_client.get_snapshot_ticker("stocks", symbol).last_trade.p
            
            mv = float(qty) * float(px)
            total_market_value += mv
            details.append({"标的": symbol, "数量": qty, "现价": f"${px:.2f}", "市值": f"${mv:.2f}"})
        except:
            details.append({"标的": symbol, "数量": qty, "现价": "数据获取中", "市值": "0.0"})
            
    return total_market_value, details

def get_et_time(): return datetime.now(pytz.timezone('US/Eastern'))

def check_market_status():
    et_now = get_et_time()
    if et_now.weekday() >= 5: return "休市 (周末)", "🔴"
    open_t, close_t = et_now.replace(hour=9, minute=30, second=0), et_now.replace(hour=16, minute=0, second=0)
    if et_now < open_t: return "盘前", "🟡"
    elif et_now > close_t: return "盘后", "🟠"
    else: return "盘中", "🟢"

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

# --- UI 展示 ---
st.title("🐝 Hive 蜂巢：资产实战看板")

with st.sidebar:
    st.header("🕒 市场状态")
    m_status, m_icon = check_market_status()
    st.subheader(f"{m_icon} {m_status}")
    st.write(f"ET: {get_et_time().strftime('%H:%M:%S')}")
    st.divider()
    if st.button("🚀 手动放飞所有蜜蜂"):
        if trigger_worker(): st.success("已起飞！")
        else: st.error("起飞失败，检查 Secrets。")

tabs = st.tabs(["👑 蜂后赋能", "🏆 演化排行榜", "🧬 杂交实验室", "⚙️ 系统维护"])

# ... t1 孵化逻辑保持不变 ...

with tabs[1]:
    res = supabase.table("drones").select("*").execute()
    if res.data:
        all_d = []
        for d in res.data:
            age = get_market_active_hours(d.get('created_at'))
            cash = float(d.get('balance') or 0.0)
            # 关键：计算实时资产
            mkt_val, pos_details = get_live_asset_value(d.get('positions', {}), cash)
            total_assets = cash + mkt_val
            
            initial = float(d.get('initial_balance') or 10000.0)
            roi = ((total_assets - initial) / initial * 100)
            roi_hr = roi / age
            
            # 更新峰值资产以便计算回撤
            peak = max(float(d.get('peak_balance') or 0), total_assets)
            mdd = max(0.0, (peak - total_assets) / peak * 100) if peak > 0 else 0
            
            d.update({
                'age_active': age, 'roi': roi, 'roi_hr': roi_hr, 
                'total_assets': total_assets, 'mkt_val': mkt_val,
                'pos_details': pos_details, 'mdd': mdd, 'fitness': roi_hr / (mdd + 1)
            })
            all_d.append(d)

        def draw_drone_card(d, icon):
            with st.expander(f"{icon} {d['name']} | 总资产: ${d['total_assets']:,.2f} | 收益: {d['roi']:.2f}%"):
                col_a, col_b, col_c = st.columns(3)
                col_a.metric("现金可用", f"${d['balance']:,.0f}")
                col_b.metric("持仓市值", f"${d['mkt_val']:,.2f}")
                col_c.metric("最大回撤", f"{d['mdd']:.2f}%")
                
                if d['pos_details']:
                    st.write("**📦 当前持仓明细:**")
                    st.table(pd.DataFrame(d['pos_details']))
                else:
                    st.write("目前处于空仓观望状态。")
                
                st.info(f"**🧠 思考复盘:** {d.get('memory')}")
                if d.get('logs'): st.json(d['logs'])
                
                if st.button(f"🗑️ 淘汰 {d['name']}", key=d['id']):
                    supabase.table("drones").delete().eq("id", d["id"]).execute(); st.rerun()

        mature = sorted([d for d in all_d if d['age_active'] >= 4], key=lambda x: x['fitness'], reverse=True)
        nursery = sorted([d for d in all_d if d['age_active'] < 4], key=lambda x: x['age_active'], reverse=True)

        st.subheader("🏁 正式赛场")
        for idx, d in enumerate(mature): draw_drone_card(d, "🥇" if idx==0 else "🥈" if idx==1 else "🥉" if idx==2 else "🐝")
        st.divider(); st.subheader("🍼 观察室")
        for d in nursery: draw_drone_card(d, "🐣"); st.progress(min(d['age_active']/4.0, 1.0))