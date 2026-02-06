import streamlit as st
import json, time, os, random, re, pytz
import pandas as pd
from datetime import datetime, timedelta
from supabase import create_client
from google import genai 
from polygon import RESTClient

# ==========================================
# 1. 样式初始化 (前端渲染层)
# ==========================================
VERSION = "v16.7 (Clean Audit & Logic Isolation)"
st.set_page_config(page_title="虎之眼-纯净审计", layout="wide")

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

# --- 2. 核心取价逻辑 (纯净版) ---
def get_val(obj, *keys):
    if not obj: return 0.0
    for k in keys:
        v = getattr(obj, k, None)
        if v is not None: return float(v)
    return 0.0

def get_precise_price(poly, ticker):
    try:
        is_opt = len(ticker) > 10 or ticker.startswith("O:")
        if is_opt:
            snap = poly.get_snapshot_ticker("options", ticker)
            lq = getattr(snap, 'last_quote', None)
            bp, ap = get_val(lq, 'p'), get_val(lq, 'P')
            if bp > 0 and ap > 0: return (bp + ap) / 2
            prev = poly.get_previous_close_agg(ticker)
            return get_val(prev[0] if prev else None, 'close')
        else:
            snap = poly.get_snapshot_ticker("stocks", ticker)
            lt = getattr(snap, 'last_trade', None)
            tp = get_val(lt, 'p')
            if tp > 0: return tp
            prev = poly.get_previous_close_agg(ticker)
            return get_val(prev[0] if prev else None, 'close')
    except: return 0.0

# ==========================================
# 3. 决策研判 (数据与样式完全隔离)
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
            # 🚨 估值防火墙：期权价不可能超过标的价
            if px > curr_p * 0.5: px = 0.01 
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

        # 🚨 核心：只存纯文本数据，绝对不带 HTML 标签
        log_entry = f"🕒 {tag}{now_tag} || 📊 {tk}:${curr_p:.2f} | NAV:${nav:,.2f} | 现金:${cash:,.2f} | 持仓:${mv_total:,.2f} || 🧠 思考: {res.get('thought', '审计完毕')} || ⚡ 行动: {(' | '.join(exec_logs) if exec_logs else '持仓观望')}"
        
        clients['supabase'].table("drones").update({
            "balance": nb, "positions": np, 
            "logs": ([log_entry] + (d.get('logs') or []))[:100]
        }).eq("id", d_id).execute()
        return True
    except: return False

# ==========================================
# 4. 界面渲染 (前端动态注入样式)
# ==========================================
st.sidebar.title("🤖 托管中心")
auto_mode = st.sidebar.toggle("开启自动巡逻", value=False)
st.title("🐝 Hive 智能金融审计")
d_res = clients['supabase'].table("drones").select("*").order("created_at", desc=True).execute().data

for d in d_res:
    with st.container(border=True):
        h_l, h_r = st.columns([5, 1])
        h_l.subheader(f"🐝 {d['name']} | 虎之眼监控")
        if h_r.button("🚀 放飞", key=f"f_{d['id']}", type="primary"):
            if execute_flight(d['id'], clients): st.cache_data.clear(); st.rerun()

        # 资产网格
        cash, pos = float(d['balance']), d.get('positions') or {}
        mv_total, pos_table = 0.0, []
        for s, q in pos.items():
            px = get_precise_price(clients['poly'], s)
            mv = px * q * 100
            mv_total += mv
            pos_table.append({"代码": s, "数量": q, "估值": f"${mv:,.2f}"})

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("现金", f"${cash:,.2f}")
        m2.metric("持仓市值", f"${mv_total:,.2f}")
        m3.metric("NAV", f"${cash+mv_total:,.2f}", delta=f"{((cash+mv_total)/100000-1)*100:.2f}%")
        m4.metric("审计条数", len(d.get('logs') or []))

        st.divider()
        st.write("🧠 **审计记忆**")
        for log in (d.get('logs') or [])[:15]:
            with st.chat_message("assistant", avatar="🐝"):
                parts = log.split(" || ")
                if len(parts) >= 3:
                    # 🚨 前端渲染时再注入样式，数据库里的数据是干净的
                    st.markdown(f'<span class="time-tag">{parts[0]}</span>', unsafe_allow_html=True)
                    st.markdown(f'<div class="data-block">{parts[1]}</div>', unsafe_allow_html=True)
                    st.markdown(f'<div class="thought-block">{parts[2].replace("🧠 思考:", "").strip()}</div>', unsafe_allow_html=True)
                    if len(parts) > 3:
                        st.markdown(f'<div class="action-block">{parts[3]}</div>', unsafe_allow_html=True)
                else:
                    st.info(log)

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