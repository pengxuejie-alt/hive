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
VERSION = "v14.6 (Full Legacy Compatible)"
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

def get_verified_price(poly, ticker):
    try:
        if ticker.startswith("O:") or len(ticker) > 10:
            end = datetime.now()
            aggs = poly.get_aggs(ticker, 1, "minute", (end-timedelta(days=5)).strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
            return float(aggs[-1].close) if aggs else 0.0
        else:
            snap = poly.get_snapshot_ticker("stocks", ticker)
            return float(getattr(snap.last_trade, 'p', 0))
    except: return 0.0

# ==========================================
# 2. 决策逻辑 (带数据自动清洗)
# ==========================================
def execute_flight(d_id, clients, is_auto=False):
    try:
        # 实时拉取最新日志
        d = clients['supabase'].table("drones").select("*").eq("id", d_id).single().execute().data
        est = pytz.timezone('US/Eastern')
        now_tag = datetime.now(est).strftime('%m-%d %H:%M:%S')
        tk = "GLD"
        curr_p = get_verified_price(clients['poly'], tk)
        
        cash, pos = float(d['balance']), d.get('positions') or {}
        mv_total = sum([get_verified_price(clients['poly'], s) * q * 100 for s, q in pos.items()])
        nav = cash + mv_total

        tag = "[AUTO] " if is_auto else ""
        prompt = f"你是{d['name']}。NAV ${nav:,.2f}, GLD ${curr_p:.2f}, 持仓:{json.dumps(pos)}。要求按 JSON 返回 thought 和 trades。"
        
        r = clients['gen_client'].models.generate_content(model="gemini-2.0-flash", contents=prompt, config={'response_mime_type': 'application/json'})
        res = json.loads(r.text)
        
        nb, np = cash, pos.copy()
        exec_logs = []
        for t in res.get('trades', []):
            sym = (t.get('ticker') or t.get('symbol', "")).upper()
            qty, act = int(t.get('qty', 0)), t.get('action', "").upper()
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

        # 统一使用 || 分隔符，数据内部使用单一 |
        new_entry = f"🕒 {tag}{now_tag} || 📊 GLD:${curr_p:.2f} | NAV:${nav:,.2f} | 现金:${cash:,.2f} | 持仓:${mv_total:,.2f} || 🧠 思考: {res.get('thought')} || ⚡ 行动: {(' | '.join(exec_logs) if exec_logs else '观望')}"
        
        clients['supabase'].table("drones").update({
            "balance": nb, "positions": np, 
            "patrol_count": d.get('patrol_count', 0)+1,
            "logs": ([new_entry] + (d.get('logs') or []))[:100] # 提升到100条存储
        }).eq("id", d_id).execute()
        return True
    except Exception as e:
        st.error(f"研判异常: {e}")
        return False

# ==========================================
# 3. 界面渲染 (带旧格式兼容渲染器)
# ==========================================
st.sidebar.title("🤖 托管中心")
auto_mode = st.sidebar.toggle("开启 5 分钟自动托管", value=False)

st.title("🐝 Hive 智能金融审计中心")
d_res = clients['supabase'].table("drones").select("*").order("created_at", desc=True).execute().data

for d in d_res:
    with st.container(border=True):
        h_l, h_r = st.columns([5, 1])
        h_l.subheader(f"🐝 {d['name']} | 虎之眼审计看板")
        if h_r.button(f"🚀 放飞研判", key=f"f_{d['id']}", type="primary", use_container_width=True):
            if execute_flight(d['id'], clients):
                st.cache_data.clear()
                st.rerun()

        # 数据指标展示 (同上)
        cash, pos = float(d.get('balance', 0.0)), d.get('positions', {})
        mv_total = sum([get_verified_price(clients['poly'], s) * q * 100 for s, q in pos.items()])
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("现金", f"${cash:,.2f}")
        m2.metric("持仓市值", f"${mv_total:,.2f}")
        m3.metric("NAV (总资产)", f"${cash+mv_total:,.2f}", delta=f"{((cash+mv_total)/100000-1)*100:.2f}%")
        m4.metric("审计深度", f"{len(d.get('logs') or [])}")

        st.divider()
        st.write("🧠 **审计记忆 (历史全兼容模式)**")
        
        logs = d.get('logs', [])
        for log in logs[:20]:
            with st.chat_message("assistant", avatar="🐝"):
                # 🚨 兼容性解析逻辑
                if " || " in log:
                    parts = log.split(" || ")
                elif " | " in log:
                    parts = log.split(" | ")
                else:
                    parts = [log]

                # 渲染逻辑
                if len(parts) >= 3:
                    st.markdown(f'<span class="time-tag">{parts[0]}</span>', unsafe_allow_html=True)
                    st.markdown(f'<div class="data-block">{parts[1]}</div>', unsafe_allow_html=True)
                    st.markdown(f'<div class="thought-block">{parts[2].replace("🧠 思考:", "").strip()}</div>', unsafe_allow_html=True)
                    if len(parts) > 3:
                        st.markdown(f'<div class="action-block">{parts[3]}</div>', unsafe_allow_html=True)
                else:
                    # 如果只有一段或两段，直接平铺显示，不留白
                    st.info(log)

# --- 托管倒计时与循环 ---
if auto_mode and d_res:
    target_id = d_res[0]['id']
    if "last_auto_run" not in st.session_state: st.session_state.last_auto_run = 0
    
    now = time.time()
    if now - st.session_state.last_auto_run > 300:
        execute_flight(target_id, clients, is_auto=True)
        st.session_state.last_auto_run = now
        st.cache_data.clear()
        st.rerun()
    else:
        remaining = int(300 - (now - st.session_state.last_auto_run))
        st.sidebar.metric("下次自动研判倒计时", f"{remaining} 秒")
        time.sleep(2) # 降低刷新频率，减轻渲染负担
        st.rerun()