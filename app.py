import streamlit as st
import json, time, os, random, re, pytz
import pandas as pd
from datetime import datetime, timedelta
from supabase import create_client
from google import genai 
from polygon import RESTClient

# ==========================================
# 1. 样式与初始化
# ==========================================
VERSION = "v15.2 (NAV Logic Lockdown)"
st.set_page_config(page_title="虎之眼智能金融审计", layout="wide")

st.markdown("""
    <style>
    .time-tag { color: #888; font-size: 0.8rem; font-family: monospace; }
    .data-block { color: #003366; font-weight: bold; font-family: monospace; font-size: 0.95rem; margin-top: 5px; border-bottom: 2px solid #1a73e8; padding-bottom: 3px; }
    .thought-block { font-size: 0.9rem; color: #333; background: #f4f6f8; padding: 12px; border-radius: 8px; border-left: 4px solid #ccd; margin: 8px 0; line-height: 1.5; white-space: pre-wrap; }
    .action-block { color: #d93025; font-weight: bold; font-size: 0.95rem; margin-top: 5px; background: #fff5f5; padding: 5px; border-radius: 4px; }
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

# ==========================================
# 2. 🚨 强化取价逻辑：增加标的与期权的隔离
# ==========================================
def get_verified_price(poly, ticker):
    try:
        # 区分期权和股票 (期权通常长度 > 10)
        if ticker.startswith("O:") or len(ticker) > 10:
            # 期权取价：取最近 5 天内有成交的最后一笔分钟线
            end = datetime.now()
            aggs = poly.get_aggs(ticker, 1, "minute", (end-timedelta(days=5)).strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
            if aggs:
                for i in range(len(aggs)-1, -1, -1):
                    if aggs[i].volume > 0: return float(aggs[i].close)
            # 兜底：取昨日收盘
            p = poly.get_previous_close_agg(ticker)
            return float(p[0].close) if p else 0.0
        else:
            # 股票取价 (GLD)：直接穿透 Stocks Snapshot
            snap = poly.get_snapshot_ticker("stocks", ticker)
            price = getattr(snap.last_trade, 'p', 0)
            if price > 0: return float(price)
            # 兜底：取昨日收盘
            p = poly.get_previous_close_agg(ticker)
            return float(p[0].close) if p else 0.0
    except:
        return 0.0

# ==========================================
# 3. 决策逻辑 (带资产合理性检查)
# ==========================================
def execute_flight(d_id, clients, is_auto=False):
    try:
        d = clients['supabase'].table("drones").select("*").eq("id", d_id).single().execute().data
        est = pytz.timezone('US/Eastern')
        now_tag = datetime.now(est).strftime('%m-%d %H:%M:%S')
        
        tk = "GLD"
        curr_p = get_verified_price(clients['poly'], tk)
        if curr_p <= 0: return False # 行情失败则跳过

        cash, pos = float(d['balance']), d.get('positions') or {}
        
        # 🚨 修正市值计算：期权乘数 100，标的乘数 1
        mv_total = 0.0
        for s, q in pos.items():
            px = get_verified_price(clients['poly'], s)
            multiplier = 100 if (s.startswith("O:") or len(s) > 10) else 1
            mv_total += px * q * multiplier
        
        nav = cash + mv_total

        # 🚨 资产熔断：如果 NAV 异常（比如超过 50 万），强制修正
        if nav > 500000: nav = cash # 简单熔断，防止 AI 幻觉

        prompt = f"你是{d['name']}。NAV ${nav:,.2f}, GLD现价 ${curr_p:.2f}, 持仓:{json.dumps(pos)}。请中文思考并分析盈亏，按 JSON 返回。"
        
        r = clients['gen_client'].models.generate_content(model="gemini-2.0-flash", contents=prompt, config={'response_mime_type': 'application/json'})
        res = json.loads(r.text)
        
        clean_thought = str(res.get('thought', '分析中...')).strip()
        nb, np = cash, pos.copy()
        exec_logs = []
        for t in res.get('trades', []):
            sym = (t.get('ticker') or t.get('symbol', "")).upper()
            qty, act = int(t.get('qty', 0)), t.get('action', "").upper()
            px = get_verified_price(clients['poly'], sym)
            if px <= 0: continue
            
            mult = 100 if (sym.startswith("O:") or len(sym) > 10) else 1
            cost = px * qty * mult
            if act == 'BUY' and nb >= cost:
                nb -= cost; np[sym] = np.get(sym, 0) + qty
                exec_logs.append(f"买入 {qty}手 {sym} @${px:.2f}")
            elif act == 'SELL' and np.get(sym, 0) >= qty:
                nb += cost; np[sym] -= qty
                if np[sym] <= 0: del np[sym]
                exec_logs.append(f"卖出 {qty}手 {sym} @${px:.2f}")

        tag = "[自动] " if is_auto else ""
        log_entry = f"🕒 {tag}{now_tag} || 📊 {tk}:${curr_p:.2f} | NAV:${nav:,.2f} | 现金:${cash:,.2f} | 持仓:${mv_total:,.2f} || 🧠 思考: {clean_thought} || ⚡ 行动: {(' | '.join(exec_logs) if exec_logs else '持仓观望')}"
        
        clients['supabase'].table("drones").update({
            "balance": nb, "positions": np, 
            "patrol_count": d.get('patrol_count', 0)+1,
            "logs": ([log_entry] + (d.get('logs') or []))[:100]
        }).eq("id", d_id).execute()
        return True
    except: return False

# ==========================================
# 4. 界面渲染
# ==========================================
st.sidebar.title("🤖 托管中心")
auto_mode = st.sidebar.toggle("开启 5 分钟自动托管", value=False)

st.title("🐝 Hive 智能金融审计中心")
d_res = clients['supabase'].table("drones").select("*").order("created_at", desc=True).execute().data

for d in d_res:
    with st.container(border=True):
        h_l, h_r = st.columns([5, 1])
        h_l.subheader(f"🐝 {d['name']} | 资产监控")
        if h_r.button(f"🚀 放飞研判", key=f"f_{d['id']}", type="primary", use_container_width=True):
            if execute_flight(d['id'], clients): st.cache_data.clear(); st.rerun()

        # Metrics 计算 (UI 侧也要对齐逻辑)
        cash, pos = float(d['balance']), d.get('positions') or {}
        mv_total, pos_table = 0.0, []
        for s, q in pos.items():
            px = get_verified_price(clients['poly'], s)
            mult = 100 if (s.startswith("O:") or len(s) > 10) else 1
            mv = px * q * mult
            mv_total += mv
            pos_table.append({"代码": s, "持仓": f"{q}手", "单价": f"${px:.2f}", "市值": f"${mv:,.2f}"})

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("现金", f"${cash:,.2f}")
        m2.metric("持仓市值", f"${mv_total:,.2f}")
        m3.metric("NAV (总资产)", f"${cash+mv_total:,.2f}", delta=f"{((cash+mv_total)/100000-1)*100:.2f}%")
        m4.metric("审计深度", f"{len(d.get('logs') or [])}")

        st.divider()
        st.write("📦 **实时投资组合 (Portfolio)**")
        if pos_table: st.dataframe(pd.DataFrame(pos_table), hide_index=True, use_container_width=True)
        else: st.caption("空仓")

        st.divider()
        st.write("🧠 **三维度审计记忆 (Data / Thought / Action)**")
        for log in (d.get('logs') or [])[:15]:
            with st.chat_message("assistant", avatar="🐝"):
                parts = log.split(" || ")
                if len(parts) >= 3:
                    st.markdown(f'<span class="time-tag">{parts[0]}</span><div class="data-block">{parts[1]}</div><div class="thought-block">{parts[2].replace("🧠 思考:", "").strip()}</div><div class="action-block">{parts[3]}</div>', unsafe_allow_html=True)

if auto_mode and d_res:
    if "last_auto_run" not in st.session_state: st.session_state.last_auto_run = 0
    now = time.time()
    if now - st.session_state.last_auto_run > 300:
        execute_flight(d_res[0]['id'], clients, is_auto=True)
        st.session_state.last_auto_run = now
        st.cache_data.clear(); st.rerun()
    else:
        st.sidebar.metric("下次自动巡逻", f"{int(300 - (now - st.session_state.last_auto_run))} 秒")
        time.sleep(2); st.rerun()