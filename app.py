import streamlit as st
import json, time, os, random, re, pytz
import pandas as pd
from datetime import datetime, timedelta
from supabase import create_client
from google import genai 
from polygon import RESTClient

# ==========================================
# 1. 初始化与样式
# ==========================================
VERSION = "v14.4 (Parallel Pilot)"
st.set_page_config(page_title="虎之眼智能金融审计", layout="wide")

st.markdown("""
    <style>
    .time-tag { color: #888; font-size: 0.8rem; font-family: monospace; }
    .data-block { color: #003366; font-weight: bold; font-family: monospace; font-size: 0.9rem; margin-top: 5px; border-bottom: 2px solid #1a73e8; padding-bottom: 3px; }
    .thought-block { font-size: 0.9rem; color: #333; background: #f4f6f8; padding: 12px; border-radius: 8px; border-left: 4px solid #ccd; margin: 8px 0; line-height: 1.5; white-space: pre-wrap; }
    .action-block { color: #d93025; font-weight: bold; font-size: 0.9rem; margin-top: 5px; background: #fff5f5; padding: 5px; border-radius: 4px; }
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

def get_val(obj, *keys):
    if not obj: return 0.0
    for k in keys:
        v = getattr(obj, k, None)
        if v is not None: return float(v)
    return 0.0

def get_verified_price(poly, ticker):
    try:
        is_option = ticker.startswith("O:") or len(ticker) > 10
        if not is_option:
            snap = poly.get_snapshot_ticker("stocks", ticker)
            prev = poly.get_previous_close_agg(ticker)
            y_close = get_val(prev[0] if prev else None, 'close')
            lt, lq = getattr(snap, 'last_trade', None), getattr(snap, 'last_quote', None)
            tp = get_val(lt, 'p', 'price')
            bp, ap = get_val(lq, 'p', 'bid'), get_val(lq, 'P', 'ask')
            return tp if tp > 0 else (((bp + ap) / 2) if (bp > 0 and ap > 0) else y_close)
        else:
            end = datetime.now()
            start = end - timedelta(days=5)
            aggs = poly.get_aggs(ticker, 1, "minute", start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
            if aggs:
                for i in range(len(aggs)-1, -1, -1):
                    if aggs[i].volume > 0: return float(aggs[i].close)
            return 0.0
    except: return 0.0

# ==========================================
# 2. 核心决策逻辑
# ==========================================
def execute_flight(d_id, clients, is_auto=False):
    est = pytz.timezone('US/Eastern')
    now_tag = datetime.now(est).strftime('%m-%d %H:%M:%S')
    
    # 🚨 强行获取最新状态
    d = clients['supabase'].table("drones").select("*").eq("id", d_id).single().execute().data
    if not d: return False

    dna = d.get('style', 'Risk:Neutral')
    current_logs = d.get('logs') or []
    tk = "GLD"
    curr_p = get_verified_price(clients['poly'], tk)
    
    cash, pos = float(d['balance']), d.get('positions') or {}
    mv_total = sum([get_verified_price(clients['poly'], s) * q * 100 for s, q in pos.items()])
    nav = cash + mv_total

    tag = "[AUTO] " if is_auto else ""
    prompt = f"你是{d['name']}。NAV ${nav:,.2f}, GLD ${curr_p:.2f}, 持仓:{json.dumps(pos)}。要求按 JSON 返回 thought 和 trades。"
    
    try:
        r = clients['gen_client'].models.generate_content(model="gemini-2.0-flash", contents=prompt, config={'response_mime_type': 'application/json'})
        res = json.loads(r.text)
        
        nb, np = cash, pos.copy()
        exec_logs = []
        for t in res.get('trades', []):
            sym = (t.get('ticker') or t.get('symbol') or "").upper()
            qty, act = int(t.get('qty', 0)), (t.get('action') or "").upper()
            px = get_verified_price(clients['poly'], sym)
            if px <= 0: continue
            cost = px * qty * (100 if "O:" in sym else 1)
            if act == 'BUY' and nb >= cost:
                nb -= cost; np[sym] = np.get(sym, 0) + qty
                exec_logs.append(f"买入{qty}手 {sym} @${px:.2f}")
            elif act == 'SELL' and np.get(sym, 0) >= qty:
                nb += cost; np[sym] -= qty
                if np[sym] <= 0: del np[sym]
                exec_logs.append(f"卖出{qty}手 {sym} @${px:.2f}")

        new_entry = f"🕒 {tag}{now_tag} || 📊 GLD:${curr_p:.2f} | NAV:${nav:,.2f} | 现金:${cash:,.2f} | 持仓:${mv_total:,.2f} || 🧠 思考: {res.get('thought')} || ⚡ 行动: {(' | '.join(exec_logs) if exec_logs else '观望')}"
        
        clients['supabase'].table("drones").update({
            "balance": nb, "positions": np, 
            "patrol_count": d.get('patrol_count', 0)+1,
            "logs": ([new_entry] + current_logs)[:50]
        }).eq("id", d["id"]).execute()
        return True
    except: return False

# ==========================================
# 3. 界面渲染
# ==========================================
st.sidebar.title("🤖 托管中心")
auto_mode = st.sidebar.toggle("开启 5 分钟自动托管", value=False)

st.title("🐝 Hive 智能金融审计中心")
d_res = clients['supabase'].table("drones").select("*").order("created_at", desc=True).execute().data

# --- 先渲染 UI 确保按钮可见 ---
for d in d_res:
    with st.container(border=True):
        h_l, h_r = st.columns([5, 1])
        h_l.subheader(f"🐝 {d['name']} | 虎之眼审计看板")
        # 🚨 手动按钮回归
        if h_r.button(f"🚀 放飞研判", key=f"f_{d['id']}", type="primary", use_container_width=True):
            if execute_flight(d['id'], clients): 
                st.cache_data.clear()
                st.rerun()

        # Metrics 网格
        cash, pos = float(d.get('balance', 0.0)), d.get('positions', {})
        mv_total = sum([get_verified_price(clients['poly'], s) * q * 100 for s, q in pos.items()])
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("现金", f"${cash:,.2f}")
        m2.metric("持仓市值", f"${mv_total:,.2f}")
        m3.metric("NAV (总资产)", f"${cash+mv_total:,.2f}", delta=f"{((cash+mv_total)/100000-1)*100:.2f}%")
        m4.metric("审计深度", f"{len(d.get('logs') or [])}")

        st.divider()
        st.write("🧠 **审计记忆**")
        logs = d.get('logs', [])
        for log in logs[:15]:
            with st.chat_message("assistant", avatar="🐝"):
                parts = log.split(" || ")
                if len(parts) >= 3:
                    st.markdown(f'<span class="time-tag">{parts[0]}</span><div class="data-block">{parts[1]}</div><div class="thought-block">{parts[2].replace("🧠 思考:", "").strip()}</div><div class="action-block">{parts[3]}</div>', unsafe_allow_html=True)

# --- 托管逻辑放在最后处理 ---
if auto_mode and d_res:
    st.sidebar.warning("自动巡逻中... 浏览器需保持开启。")
    target_id = d_res[0]['id']
    # 这里立即执行一次，然后进入等待循环
    execute_flight(target_id, clients, is_auto=True)
    time.sleep(300)
    st.cache_data.clear()
    st.rerun()