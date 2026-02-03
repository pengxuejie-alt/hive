import streamlit as st
import pandas as pd
from supabase import create_client
import json, requests, time
from datetime import datetime, timezone
from google import genai
from polygon import RESTClient

# --- 1. 基础配置 ---
st.set_page_config(page_title="Hive 蜂巢控制台", layout="wide", page_icon="🐝")

try:
    supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
    gen_client = genai.Client(api_key=st.secrets["GEMINI_KEY"])
    poly_client = RESTClient(api_key=st.secrets["POLYGON_KEY"])
except Exception as e:
    st.error(f"启动失败: {e}")
    st.stop()

# --- 2. 功能函数 ---
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
            p = poly_client.get_last_trade(k).price if k.startswith("O:") else poly_client.get_snapshot_ticker("stocks", k).last_trade.p
            val = float(v) * float(p) * (100 if k.startswith("O:") else 1)
            mv += val
            details.append({"代码": k, "仓位": v, "现价": f"${p:.2f}", "市值": f"${val:,.2f}"})
        except: details.append({"代码": k, "仓位": v, "市值": "获取中"})
    return mv, details

# --- 3. 侧边栏 ---
with st.sidebar:
    st.title("🐝 Hive 蜂巢")
    if "is_flying" not in st.session_state: st.session_state.is_flying = False

    if st.button("🚀 放飞所有工蜂", disabled=st.session_state.is_flying, use_container_width=True):
        if trigger_action():
            st.session_state.is_flying = True
            bar = st.progress(0)
            status = st.empty()
            msg = ["📦 环境准备中...", "📡 扫描盘中行情...", "🧠 正在演化决策...", "💾 同步资产账本...", "✅ 巡检完成！"]
            for i in range(100):
                time.sleep(0.35) 
                bar.progress(i + 1)
                status.caption(msg[i // 25] if i // 25 < 5 else msg[-1])
            st.session_state.is_flying = False
            st.cache_data.clear()
            st.rerun()

# --- 4. 标签页 ---
t1, t2, t3 = st.tabs(["🏆 工蜂列表", "👑 蜂后孵化", "⚙️ 系统管理"])

with t1:
    # 修复核心：调整 order 的位置和调用方式
    try:
        query = supabase.table("drones").select("*")
        # 确保 created_at 存在，如果报错则不排序
        res = query.order("created_at", desc=True).execute()
        data = res.data
    except:
        res = supabase.table("drones").select("*").execute()
        data = res.data

    if data:
        for d in data:
            db_assets = d.get('total_assets', 10000.0)
            with st.expander(f"🐝 {d['name']} | 总资产: ${db_assets:,.2f} | 巡检: {d.get('patrol_count', 0)}"):
                live_mv, pos_list = get_live_valuation(d.get('positions', {}))
                st.metric("现金", f"${d['balance']:,.2f}", delta=f"实时市值: ${live_mv:,.2f}")
                if pos_list: st.table(pd.DataFrame(pos_list))
                for log in (d.get('logs', []) or [])[:5]:
                    if "🟢" in str(log): st.success(log)
                    elif "🔴" in str(log): st.error(log)
                    else: st.info(log)

with t2:
    instr = st.text_area("孵化指令:")
    if st.button("执行孵化"):
        p = f"设计工蜂。返回纯JSON列表：[{{'name':'','focus':'','portfolio':[''],'logic':'','persona':'','balance':10000}}]。指令：{instr}"
        r = gen_client.models.generate_content(model="gemini-2.0-flash-exp", contents=p, config={'response_mime_type': 'application/json'})
        for item in json.loads(r.text):
            item.update({"created_at": datetime.now(timezone.utc).isoformat(), "patrol_count": 0, "logs": [], "total_assets": 10000.0})
            supabase.table("drones").insert(item).execute()
        st.rerun()

with t3:
    if st.button("🔥 全量清空蜂巢", type="primary"):
        # 修复：neq 条件必须匹配字段类型
        supabase.table("drones").delete().neq("name", "RESERVED_VOID_NAME").execute()
        st.cache_data.clear()
        st.rerun()