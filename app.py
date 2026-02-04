import streamlit as st
import json, time, os, random, re, pytz
import pandas as pd
from datetime import datetime, timedelta
from supabase import create_client
from google import genai 
from polygon import RESTClient

# ==========================================
# 1. 样式与初始化 (专业对齐)
# ==========================================
VERSION = "v16.3 (Ultimate Display Fix)"
st.set_page_config(page_title="虎之眼智能金融审计", layout="wide")

st.markdown("""
    <style>
    .time-tag { color: #888; font-size: 0.8rem; font-family: monospace; }
    .data-block { color: #003366; font-weight: bold; font-family: monospace; font-size: 0.95rem; margin-top: 5px; border-bottom: 2px solid #1a73e8; padding-bottom: 3px; }
    .thought-block { font-size: 0.95rem; color: #111; background: #f0f2f6; padding: 15px; border-radius: 8px; border-left: 5px solid #1a73e8; margin: 10px 0; line-height: 1.6; }
    .action-block { color: #d93025; font-weight: bold; font-size: 0.95rem; margin-top: 5px; background: #fff5f5; padding: 5px; border-radius: 4px; }
    .dna-tag { background-color: #e8f0fe; color: #1967d2; padding: 2px 8px; border-radius: 4px; font-size: 0.8rem; margin-bottom: 5px; display: inline-block; }
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

def get_price(poly, ticker):
    if not ticker: return 0.0
    is_opt = len(ticker) > 10 or ticker.startswith("O:")
    try:
        if is_opt:
            prev = poly.get_previous_close_agg(ticker)
            return get_val(prev[0] if prev else None, 'close')
        else:
            snap = poly.get_snapshot_ticker("stocks", ticker)
            prev = poly.get_previous_close_agg(ticker)
            y_close = get_val(prev[0] if prev else None, 'close')
            lt = getattr(snap, 'last_trade', None)
            tp = get_val(lt, 'p', 'price')
            return tp if tp > 0 else y_close
    except: return 0.0

# ==========================================
# 2. 决策逻辑
# ==========================================
def execute_flight(d_id, clients, is_auto=False):
    try:
        d = clients['supabase'].table("drones").select("*").eq("id", d_id).single().execute().data
        est = pytz.timezone('US/Eastern')
        now_tag = datetime.now(est).strftime('%m-%d %H:%M:%S')
        tk = "GLD"
        curr_p = get_price(clients['poly'], tk)
        cash, pos = float(d['balance']), d.get('positions') or {}
        
        mv_total = 0.0
        for s, q in pos.items():
            px = get_price(clients['poly'], s)
            mult = 100 if (len(s) > 10 or s.startswith("O:")) else 1
            mv_total += px * q * mult
        nav = cash + mv_total

        prompt = f"你是{d['name']}。性格:{d.get('style')}。NAV:${nav:,.2f}, GLD:${curr_p:.2f}。请用中文深度分析并提供JSON决策。"
        r = clients['gen_client'].models.generate_content(model="gemini-2.0-flash", contents=prompt, config={'response_mime_type': 'application/json'})
        res = json.loads(r.text)
        
        thought = res.get('thought') or res.get('analysis') or "AI 思考提取中..."
        nb, np = cash, pos.copy()
        exec_logs = []
        for t in res.get('trades', []):
            sym = (t.get('ticker') or t.get('symbol', "")).upper()
            qty, act = int(t.get('qty', 0)), t.get('action', "").upper()
            px = get_price(clients['poly'], sym)
            if px <= 0: continue
            cost = px * qty * (100 if len(sym)>10 else 1)
            if act == 'BUY' and nb >= cost:
                nb -= cost; np[sym] = np.get(sym, 0) + qty
                exec_logs.append(f"买入 {qty}手 {sym} @${px:.2f}")
            elif act == 'SELL' and np.get(sym, 0) >= qty:
                nb += cost; np[sym] -= qty
                if np[sym] <= 0: del np[sym]
                exec_logs.append(f"卖出 {qty}手 {sym} @${px:.2f}")

        tag = "[自动] " if is_auto else ""
        log_entry = f"🕒 {tag}{now_tag} || 📊 {tk}:${curr_p:.2f} | NAV:${nav:,.2f} | 现金:${cash:,.2f} | 持仓:${mv_total:,.2f} || 🧠 思考: {thought} || ⚡ 行动: {(' | '.join(exec_logs) if exec_logs else '观望')}"
        
        clients['supabase'].table("drones").update({
            "balance": nb, "positions": np, 
            "logs": ([log_entry] + (d.get('logs') or []))[:100]
        }).eq("id", d_id).execute()
        return True
    except Exception as e:
        st.error(f"研判失败: {e}")
        return False

# ==========================================
# 3. 界面渲染 (找回 DNA 与 持仓表格)
# ==========================================
st.sidebar.title("🤖 托管中心")
auto_mode = st.sidebar.toggle("开启 5 分钟自动托管", value=False)

st.title("🐝 Hive 智能金融审计中心")
d_res = clients['supabase'].table("drones").select("*").order("created_at", desc=True).execute().data

for d in d_res:
    with st.container(border=True):
        h_l, h_r = st.columns([5, 1])
        h_l.subheader(f"🐝 {d['name']} | 虎之眼审计监控")
        if h_r.button(f"🚀 放飞研判", key=f"f_{d['id']}", type="primary", use_container_width=True):
            if execute_flight(d['id'], clients): st.cache_data.clear(); st.rerun()

        # Metrics
        cash, pos = float(d['balance']), d.get('positions') or {}
        mv_total, pos_table = 0.0, []
        for s, q in pos.items():
            px = get_price(clients['poly'], s)
            mult = 100 if (len(s) > 10 or s.startswith("O:")) else 1
            mv = px * q * mult
            mv_total += mv
            pos_table.append({"代码": s, "持仓": f"{q}手", "单价": f"${px:.2f}", "市值": f"${mv:,.2f}"})

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("现金", f"${cash:,.2f}")
        m2.metric("持仓市值", f"${mv_total:,.2f}")
        m3.metric("NAV (总资产)", f"${cash+mv_total:,.2f}", delta=f"{((cash+mv_total)/100000-1)*100:.2f}%")
        m4.metric("审计深度", f"{len(d.get('logs') or [])}")

        st.divider()
        # 🚨 找回 DNA 和 持仓明细
        c1, c2 = st.columns([1, 2.5])
        with c1:
            st.write("🧬 **DNA 基因序列**")
            for frag in d.get('style', '').split(' | '):
                st.markdown(f'<span class="dna-tag">{frag}</span>', unsafe_allow_html=True)
        with c2:
            st.write("📦 **实时投资组合 (Portfolio)**")
            if pos_table: st.dataframe(pd.DataFrame(pos_table), hide_index=True, use_container_width=True)
            else: st.caption("账户当前空仓")

        st.divider()
        st.write("🧠 **审计追踪 (Data / Thought / Action)**")
        
        # 🚨 强兼容性日志渲染器
        for log in (d.get('logs') or [])[:15]:
            with st.chat_message("assistant", avatar="🐝"):
                # 尝试多种分隔符解析
                if " || " in log: parts = log.split(" || ")
                elif " | " in log: parts = log.split(" | ")
                else: parts = [log]
                
                if len(parts) >= 3:
                    st.markdown(f'<span class="time-tag">{parts[0]}</span>', unsafe_allow_html=True)
                    st.markdown(f'<div class="data-block">{parts[1]}</div>', unsafe_allow_html=True)
                    st.markdown(f'<div class="thought-block">{parts[2].replace("🧠 思考:", "").strip()}</div>', unsafe_allow_html=True)
                    if len(parts) > 3: st.markdown(f'<div class="action-block">{parts[3]}</div>', unsafe_allow_html=True)
                else:
                    st.info(f"📜 早期/非标准日志: {log}")

if auto_mode and d_res:
    if "last_auto_run" not in st.session_state: st.session_state.last_auto_run = 0
    now = time.time()
    if (now - st.session_state.last_auto_run) > 300:
        if execute_flight(d_res[0]['id'], clients, is_auto=True):
            st.session_state.last_auto_run = now
            st.cache_data.clear(); st.rerun()
    else:
        st.sidebar.metric("下次自动巡逻", f"{int(300 - (now - st.session_state.last_auto_run))} 秒")
        time.sleep(2); st.rerun()