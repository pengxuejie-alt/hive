import streamlit as st
import pandas as pd
from supabase import create_client
import json, requests, time
from datetime import datetime, timezone
from google import genai
from polygon import RESTClient

# --- 初始化 ---
st.set_page_config(page_title="Hive 蜂巢控制台", layout="wide", page_icon="🐝")

try:
    supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
    gen_client = genai.Client(api_key=st.secrets["GEMINI_KEY"])
    poly_client = RESTClient(api_key=st.secrets["POLYGON_KEY"])
except Exception as e:
    st.error(f"启动失败: {e}")
    st.stop()

def trigger_action():
    try:
        token, repo = st.secrets["GITHUB_TOKEN"].strip(), st.secrets["GITHUB_REPO"].strip()
        url = f"https://api.github.com/repos/{repo}/actions/workflows/hive_cycle.yml/dispatches"
        res = requests.post(url, headers={"Authorization": f"token {token}"}, json={"ref": "main"})
        return res.status_code == 204
    except: return False

@st.cache_data(ttl=60)
def get_live_valuation(positions):
    mv = 0.0
    details = []
    if not positions: return 0.0, []
    for k, v in positions.items():
        try:
            p_obj = poly_client.get_last_trade(k)
            price = getattr(p_obj, 'price', getattr(p_obj, 'p', 0))
            if price == 0:
                sn = poly_client.get_snapshot_ticker("options" if "O:" in k else "stocks", k)
                price = getattr(sn.last_trade, 'p', getattr(sn.prev_day, 'c', 0))
            val = float(v) * float(price) * (100 if "O:" in k else 1)
            mv += val
            details.append({"代码": k, "仓位": v, "现价": f"${price:.2f}", "市值": f"${val:,.2f}"})
        except: details.append({"代码": k, "仓位": v, "市值": "计算中"})
    return mv, details

# --- 侧边栏 ---
with st.sidebar:
    st.title("🐝 Hive 蜂巢")
    if "is_flying" not in st.session_state: st.session_state.is_flying = False
    if st.button("🚀 放飞所有工蜂", disabled=st.session_state.is_flying, use_container_width=True):
        if trigger_action():
            st.session_state.is_flying = True
            bar = st.progress(0)
            st.caption("📡 正在调用 GitHub Actions 进行分时维度扫描...")
            for i in range(100):
                time.sleep(0.35); bar.progress(i + 1)
            st.session_state.is_flying = False
            st.cache_data.clear(); st.rerun()

# --- 标签页 ---
t1, t2, t3 = st.tabs(["🏆 工蜂列表", "👑 蜂后孵化", "⚙️ 系统管理"])

with t1:
    res = supabase.table("drones").select("*").order("created_at", desc=True).execute()
    for d in (res.data or []):
        with st.expander(f"🐝 {d['name']} | 资产: ${d.get('total_assets', 100000.0):,.2f}"):
            mv, pos_df = get_live_valuation(d.get('positions', {}))
            st.metric("现金", f"${d['balance']:,.2f}", delta=f"持仓: ${mv:,.2f}")
            if pos_df: st.table(pd.DataFrame(pos_df))
            for log in (d.get('logs', []) or [])[:5]:
                if "🟢" in str(log): st.success(log)
                elif "🔴" in str(log): st.error(log)
                else: st.info(log)

with t2:
    instr = st.text_area("孵化指令:", placeholder="例如：孵化3只擅长远期期权配置的工蜂...")
    if st.button("开始孵化", type="primary"):
        # 💡 初始本金提升至 100,000
        p = f"设计工蜂。返回纯JSON列表：[{{'name':'','focus':'','portfolio':[''],'logic':'','persona':'','balance':100000}}]。指令：{instr}"
        r = gen_client.models.generate_content(model="gemini-3-flash-preview", contents=p, config={'response_mime_type': 'application/json'})
        for item in json.loads(r.text):
            item.update({"created_at": datetime.now(timezone.utc).isoformat(), "patrol_count": 0, "logs": [], "total_assets": 100000.0, "positions": {}})
            supabase.table("drones").insert(item).execute()
        st.success("孵化完成！"); st.rerun()

with t3:
    if st.button("🔥 全量清空蜂巢", type="primary"):
        supabase.table("drones").delete().neq("name", "RESERVED").execute()
        st.cache_data.clear(); st.rerun()