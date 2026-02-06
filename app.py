import streamlit as st
import json, time, os, random, re, pytz
import pandas as pd
from datetime import datetime, timedelta
from supabase import create_client
from google import genai 
from polygon import RESTClient

# ==========================================
# 1. 初始化与专业样式
# ==========================================
VERSION = "v16.8 (Queen & System Management)"
st.set_page_config(page_title="Hive 智能审计管理中心", layout="wide")

st.markdown("""
    <style>
    .time-tag { color: #888; font-size: 0.8rem; font-family: monospace; }
    .data-block { color: #003366; font-weight: bold; font-family: monospace; font-size: 0.95rem; margin: 5px 0; border-bottom: 2px solid #1a73e8; }
    .thought-block { font-size: 0.95rem; color: #222; background: #f0f2f6; padding: 15px; border-radius: 8px; border-left: 5px solid #d93025; margin: 10px 0; line-height: 1.6; }
    .action-block { color: #d93025; font-weight: bold; font-size: 0.9rem; background: #fff5f5; padding: 5px; border-radius: 4px; border: 1px solid #ffcdd2; }
    </style>
""", unsafe_allow_html=True)

@st.cache_resource
def init_hive_engine():
    try:
        return {
            "supabase": create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"]),
            "gen_client": genai.Client(api_key=st.secrets["GEMINI_KEY"]),
            "poly": RESTClient(api_key=st.secrets["POLYGON_KEY"])
        }, None
    except Exception as e: return None, str(e)

cl_pkg, err = init_hive_engine()
if err: st.error(err); st.stop()
clients = cl_pkg

# --- 取价逻辑 (锁定 v16.7 稳定版) ---
def get_precise_price(poly, ticker):
    try:
        is_opt = len(ticker) > 10 or ticker.startswith("O:")
        if is_opt:
            snap = poly.get_snapshot_ticker("options", ticker)
            lq = getattr(snap, 'last_quote', None)
            bp, ap = getattr(lq, 'p', 0), getattr(lq, 'P', 0)
            if bp > 0 and ap > 0: return (float(bp) + float(ap)) / 2
            prev = poly.get_previous_close_agg(ticker)
            return float(prev[0].close) if prev else 0.0
        else:
            snap = poly.get_snapshot_ticker("stocks", ticker)
            lt = getattr(snap, 'last_trade', None)
            tp = getattr(lt, 'p', 0)
            if tp > 0: return float(tp)
            prev = poly.get_previous_close_agg(ticker)
            return float(prev[0].close) if prev else 0.0
    except: return 0.0

# ==========================================
# 2. 系统管理核心：孵化与销毁
# ==========================================
def hatch_drone(clients, name, dna):
    new_drone = {
        "name": name,
        "style": dna,
        "balance": 100000.0,
        "positions": {},
        "logs": [f"🕒 初始 | 🐣 {name} 孵化完成 || 📊 初始资产: $100,000 || 🧠 思考: 准备启动策略 || ⚡ 行动: 等待首航"]
    }
    clients['supabase'].table("drones").insert(new_drone).execute()

def wipe_all_drones(clients):
    clients['supabase'].table("drones").delete().neq("name", "SYSTEM_RESERVED").execute()

# ==========================================
# 3. 决策研判引擎
# ==========================================
def execute_flight(d_id, clients, is_auto=False):
    try:
        d = clients['supabase'].table("drones").select("*").eq("id", d_id).single().execute().data
        est = pytz.timezone('US/Eastern')
        now_tag = datetime.now(est).strftime('%m-%d %H:%M:%S')
        tk = "GLD"
        curr_p = get_precise_price(clients['poly'], tk)
        
        cash, pos = float(d['balance']), d.get('positions') or {}
        mv_total = 0.0
        for s, q in pos.items():
            px = get_precise_price(clients['poly'], s)
            mv_total += px * q * 100
        
        nav = cash + mv_total
        tag = "[自动] " if is_auto else ""
        
        prompt = f"你是{d['name']}。DNA:{d.get('style')}。NAV:${nav:,.2f}, GLD:${curr_p:.2f}, 持仓:{json.dumps(pos)}。要求中文分析并返回 JSON。"
        r = clients['gen_client'].models.generate_content(model="gemini-2.0-flash", contents=prompt, config={'response_mime_type': 'application/json'})
        res = json.loads(r.text)
        
        nb, np, exec_logs = cash, pos.copy(), []
        for t in res.get('trades', []):
            sym = (t.get('ticker') or t.get('symbol', "")).upper()
            qty, act = int(t.get('qty', 0)), t.get('action', "").upper()
            px = get_precise_price(clients['poly'], sym)
            cost = px * qty * 100
            if act == 'BUY' and nb >= cost:
                nb -= cost; np[sym] = np.get(sym, 0) + qty
                exec_logs.append(f"买入 {qty}手 {sym} @${px:.2f}")
            elif act == 'SELL' and np.get(sym, 0) >= qty:
                nb += cost; np[sym] -= qty
                if np[sym] <= 0: del np[sym]
                exec_logs.append(f"卖出 {qty}手 {sym} @${px:.2f}")

        log_entry = f"🕒 {tag}{now_tag} || 📊 {tk}:${curr_p:.2f} | NAV:${nav:,.2f} | 现金:${cash:,.2f} | 持仓:${mv_total:,.2f} || 🧠 思考: {res.get('thought', '审计完毕')} || ⚡ 行动: {(' | '.join(exec_logs) if exec_logs else '持仓观望')}"
        
        clients['supabase'].table("drones").update({
            "balance": nb, "positions": np, 
            "logs": ([log_entry] + (d.get('logs') or []))[:100]
        }).eq("id", d_id).execute()
        return True
    except: return False

# ==========================================
# 4. 界面渲染与管理面板
# ==========================================
st.sidebar.title("👑 蜂后控制台")

# 4.1 孵化器
with st.sidebar.expander("🐣 孵化新工蜂", expanded=False):
    new_name = st.text_input("工蜂代号", value=f"AI-{random.randint(100,999)}")
    new_dna = st.text_area("DNA 基因序列", value="激进型 | 末日博弈 | 冷静分析")
    if st.button("开始孵化", use_container_width=True):
        hatch_drone(clients, new_name, new_dna)
        st.success(f"{new_name} 已进入蜂群")
        time.sleep(1); st.rerun()

# 4.2 自动托管
st.sidebar.divider()
auto_mode = st.sidebar.toggle("开启 5 分钟自动托管", value=False)

# 4.3 系统清空
st.sidebar.divider()
with st.sidebar.expander("⚠️ 系统高级管理", expanded=False):
    st.warning("此操作将永久删除所有交易数据。")
    if st.button("🔥 销毁所有蜜蜂", use_container_width=True):
        wipe_all_drones(clients)
        st.cache_data.clear(); st.rerun()

st.title("🐝 Hive 智能金融审计中心")
d_res = clients['supabase'].table("drones").select("*").order("created_at", desc=True).execute().data

for d in d_res:
    with st.container(border=True):
        h_l, h_r = st.columns([5, 1])
        h_l.subheader(f"🐝 {d['name']} | 管理监控")
        if h_r.button("🚀 放飞", key=f"f_{d['id']}", type="primary"):
            if execute_flight(d['id'], clients): st.cache_data.clear(); st.rerun()

        # 数据卡片
        cash, pos = float(d['balance']), d.get('positions') or {}
        mv_total = 0.0
        for s, q in pos.items():
            px = get_precise_price(clients['poly'], s)
            mv_total += px * q * 100
        
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("现金", f"${cash:,.2f}")
        m2.metric("持仓市值", f"${mv_total:,.2f}")
        m3.metric("NAV", f"${cash+mv_total:,.2f}", delta=f"{((cash+mv_total)/100000-1)*100:.2f}%")
        m4.metric("审计条数", len(d.get('logs') or []))

        st.divider()
        st.write("🧠 **审计记忆**")
        for log in (d.get('logs') or [])[:10]:
            with st.chat_message("assistant", avatar="🐝"):
                parts = log.split(" || ")
                if len(parts) >= 3:
                    st.markdown(f'<span class="time-tag">{parts[0]}</span>', unsafe_allow_html=True)
                    st.markdown(f'<div class="data-block">{parts[1]}</div>', unsafe_allow_html=True)
                    st.markdown(f'<div class="thought-block">{parts[2].replace("🧠 思考:", "").strip()}</div>', unsafe_allow_html=True)
                    if len(parts) > 3: st.markdown(f'<div class="action-block">{parts[3]}</div>', unsafe_allow_html=True)

# 托管逻辑
if auto_mode and d_res:
    if "last_auto_run" not in st.session_state: st.session_state.last_auto_run = 0
    now = time.time()
    if (now - st.session_state.last_auto_run) > 300:
        execute_flight(d_res[0]['id'], clients, is_auto=True)
        st.session_state.last_auto_run = now
        st.cache_data.clear(); st.rerun()
    else:
        st.sidebar.metric("下次自动研判", f"{int(300 - (now - st.session_state.last_auto_run))} 秒")
        time.sleep(2); st.rerun()