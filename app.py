import streamlit as st
import pandas as pd
from supabase import create_client
import google.generativeai as genai
import json, requests, pytz
from datetime import datetime, timezone
from polygon import RESTClient

# --- 1. 基础配置 ---
st.set_page_config(page_title="Hive 蜂巢控制台", layout="wide", page_icon="🐝")

try:
    supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
    genai.configure(api_key=st.secrets["GEMINI_KEY"])
    queen_ai = genai.GenerativeModel("gemini-3-flash-preview")
    # 付费版接口支持
    poly_client = RESTClient(api_key=st.secrets["POLYGON_KEY"])
except Exception as e:
    st.error(f"初始化失败: {e}")
    st.stop()

# --- 2. 深度穿透估值函数 (付费版专用) ---
def get_live_valuation(positions):
    mv = 0.0
    details = []
    if not positions: return 0.0, []
    
    for k, v in positions.items():
        try:
            if k.startswith("O:"):
                # 付费版 Last Trade 极速响应
                p = poly_client.get_last_trade(k).price
                val = float(v) * float(p) * 100
            else:
                # 股票 Snapshot 包含盘前盘后价格
                snap = poly_client.get_snapshot_ticker("stocks", k)
                p = snap.last_trade.p if snap.last_trade and snap.last_trade.p > 0 else snap.prev_day.c
                val = float(v) * float(p)
            mv += val
            details.append({"代码": k, "仓位": v, "现价": f"${p:.2f}", "市值": f"${val:,.2f}"})
        except:
            details.append({"代码": k, "仓位": v, "现价": "获取中", "市值": "0.00"})
    return mv, details

# --- 3. 侧边栏 ---
with st.sidebar:
    st.title("🐝 Hive 蜂巢")
    if st.button("🚀 放飞所有工蜂"):
        repo = st.secrets["GITHUB_REPO"]
        requests.post(f"https://api.github.com/repos/{repo}/actions/workflows/hive_cycle.yml/dispatches",
                      headers={"Authorization": f"token {st.secrets['GITHUB_TOKEN']}"}, json={"ref": "main"})
        st.success("巡检指令已下达")

# --- 4. 强制 Tab 驻留结构 ---
t1, t2, t3 = st.tabs(["🏆 工蜂列表", "👑 蜂后孵化", "⚙️ 系统管理"])

with t1:
    res = supabase.table("drones").select("*").execute()
    if not res.data:
        st.info("蜂巢暂无工蜂，请前往孵化。")
    else:
        for d in res.data:
            # 列表显示：优先读取数据库已存的 total_assets，实现秒开
            db_total = d.get('total_assets', 10000.0)
            created_at = datetime.fromisoformat(d.get('created_at', datetime.now(timezone.utc).isoformat()).replace('Z', '+00:00'))
            age_h = (datetime.now(timezone.utc) - created_at).total_seconds() / 3600
            
            with st.expander(f"🐝 {d['name']} | 总资产: ${db_total:,.2f} | 巡检: {d.get('patrol_count', 0)}次"):
                st.caption(f"性格: {d.get('persona')} | 年龄: {age_h:.1f}h | 监控: {', '.join(d.get('portfolio', []))}")
                
                # 深度穿透：点开后才重算实时价格
                live_mv, pos_details = get_live_valuation(d.get('positions', {}))
                cash = float(d.get('balance', 10000.0))
                
                c1, c2 = st.columns(2)
                c1.metric("实时现金余额", f"${cash:,.2f}")
                c2.metric("实时持仓市值", f"${live_mv:,.2f}")
                
                if pos_details: st.table(pd.DataFrame(pos_details))
                
                st.write("**📜 最新日志:**")
                for log in (d.get('logs', []) or [])[:8]:
                    st.caption(str(log))

with t2:
    st.subheader("🧬 基因编码：孵化新工蜂")
    instruction = st.text_area("输入孵化指令:", height=150, placeholder="例如：孵化2只专门盯住 NVDA 期权波动的激进工蜂")
    if st.button("注入基因并孵化", type="primary"):
        with st.spinner("蜂后编码中..."):
            try:
                prompt = f"设计工蜂。返回纯JSON列表：[{{'name':'代号','focus':'option','portfolio':['代码'],'logic':'逻辑','persona':'性格','balance':10000,'initial_balance':10000,'memory':'等待开盘'}}]。指令：{instruction}"
                res_ai = queen_ai.generate_content(prompt)
                items = json.loads(res_ai.text.strip().replace("```json", "").replace("```", "").strip())
                for item in items:
                    item.update({"created_at": datetime.now(timezone.utc).isoformat(), "patrol_count": 0, "logs": [], "total_assets": 10000.0})
                    supabase.table("drones").insert(item).execute()
                st.success("孵化成功！"); st.rerun()
            except Exception as e: st.error(f"孵化失败: {e}")

with t3:
    st.header("⚙️ 蜂巢管理")
    
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("文明重启")
        st.caption("重置出生时间、巡检次数、账本、日志、记忆。")
        if st.button("🩹 执行文明重启", key="full_reset"):
            supabase.table("drones").update({
                "balance": 10000.0, "positions": {}, "logs": [], "memory": "等待开盘",
                "patrol_count": 0, "total_assets": 10000.0, "created_at": datetime.now(timezone.utc).isoformat()
            }).neq("id", -1).execute(); st.rerun()

    with col2:
        st.subheader("财务审计")
        st.caption("重置账本、日志；保留出生时间、巡检次数、记忆。")
        if st.button("🩹 执行财务审计", key="finance_reset"):
            supabase.table("drones").update({
                "balance": 10000.0, "positions": {}, "logs": [], "total_assets": 10000.0
            }).neq("id", -1).execute(); st.rerun()

    st.divider()
    if st.button("🔥 全量清空蜂巢", type="primary"):
        if st.checkbox("确认彻底删除所有工蜂？"):
            supabase.table("drones").delete().neq("id", -1).execute(); st.rerun()