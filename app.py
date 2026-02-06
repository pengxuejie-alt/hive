import streamlit as st
import json, time, os, random, re, pytz
import pandas as pd
from datetime import datetime, timedelta
from supabase import create_client
from google import genai 
from polygon import RESTClient

# ==========================================
# 1. 样式与初始化 (蜂巢 17.1)
# ==========================================
VERSION = "v17.1 (Full Chain Awakening)"
st.set_page_config(page_title="Hive 智能审计 v17.1", layout="wide")

st.markdown("""
    <style>
    .time-tag { color: #888; font-size: 0.8rem; font-family: monospace; }
    .data-box { color: #003366; font-weight: bold; background: #e8f0fe; padding: 10px; border-radius: 5px; margin: 5px 0; }
    .thought-box { font-size: 0.95rem; color: #111; background: #f8f9fa; padding: 15px; border-radius: 8px; border-left: 5px solid #d93025; line-height: 1.6; margin: 10px 0; }
    .action-box { color: #d93025; font-weight: bold; background: #fff5f5; padding: 8px; border-radius: 4px; border: 1px solid #ffcdd2; }
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

# --- 2. 虎之眼高鲁棒性引擎 ---
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
            return (bp + ap) / 2 if (bp > 0 and ap > 0) else get_val(poly.get_previous_close_agg(ticker)[0], 'close')
        else:
            snap = poly.get_snapshot_ticker("stocks", ticker)
            lt = getattr(snap, 'last_trade', None)
            tp = get_val(lt, 'p')
            return tp if tp > 0 else get_val(poly.get_previous_close_agg(ticker)[0], 'close')
    except: return 0.0

def fetch_active_options_chain(poly, underlying, curr_p):
    try:
        # 获取平值附近活跃合约
        chain = list(poly.list_snapshot_options_chain(underlying, params={
            "strike_price.gte": curr_p * 0.96, "strike_price.lte": curr_p * 1.04, "limit": 25
        }))
        # 如果空，则不带价格约束抓取一次保底
        if not chain:
            chain = list(poly.list_snapshot_options_chain(underlying, params={"limit": 10}))
            
        opts = []
        for o in chain:
            lq = getattr(o, 'last_quote', None)
            bp, ap = get_val(lq, 'p'), get_val(lq, 'P')
            mid = (bp + ap) / 2 if (bp > 0 and ap > 0) else get_val(o.day, 'close')
            if mid > 0.01:
                opts.append({"ticker": o.ticker, "price": round(mid, 2), "vol": int(get_val(o.day, 'volume'))})
        opts.sort(key=lambda x: x['vol'], reverse=True)
        return opts[:12]
    except: return []

# ==========================================
# 3. 研判核心 (CoT 强制唤醒)
# ==========================================
def execute_flight(d_id, clients, instruction=None):
    try:
        d = clients['supabase'].table("drones").select("*").eq("id", d_id).single().execute().data
        tk, curr_p = "GLD", get_precise_price(clients['poly'], "GLD")
        
        # 弹药库注入
        market_options = fetch_active_options_chain(clients['poly'], tk, curr_p)
        
        cash, pos = float(d['balance']), d.get('positions') or {}
        mv_total = sum([get_precise_price(clients['poly'], s) * q * 100 for s, q in pos.items()])
        nav = cash + mv_total

        # 🚨 强制思维链 Prompt
        prompt = f"""你是{d['name']}。DNA:{d.get('style')}。
        NAV:${nav:,.2f} | {tk}:${curr_p:.2f} | 现金:${cash:,.2f}
        [可用期权代码]: {json.dumps(market_options)}
        [持仓]: {json.dumps(pos)}
        要求:
        1. 必须提供详细的中文分析(thought)，字数不少于100字，严禁回复“审计完毕”。
        2. 若发现可用期权，必须评估是否通过买入或卖出来优化 NAV。
        3. 必须返回严格 JSON。"""
        
        if instruction: prompt += f"\n用户指令: {instruction}"

        r = clients['gen_client'].models.generate_content(model="gemini-2.0-flash", contents=prompt, config={'response_mime_type': 'application/json'})
        res = json.loads(r.text)
        
        thought = res.get('thought') or res.get('analysis') or "⚠️ 唤醒失败：AI 未能提供逻辑分析"
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

        now_tag = datetime.now(pytz.timezone('US/Eastern')).strftime('%m-%d %H:%M:%S')
        # 🚨 移除所有 div，纯文本存储
        log_entry = f"🕒 {now_tag} || 📊 {tk}:${curr_p:.2f} | NAV:${nav:,.2f} | 现金:${cash:,.2f} || 🧠 思考: {thought} || ⚡ 行动: {(' | '.join(exec_logs) if exec_logs else '持仓观望')}"
        
        clients['supabase'].table("drones").update({
            "balance": nb, "positions": np, 
            "logs": ([log_entry] + (d.get('logs') or []))[:100],
            "patrol_count": d.get('patrol_count', 0) + 1
        }).eq("id", d_id).execute()
        return True
    except: return False

# ==========================================
# 4. 界面渲染
# ==========================================
st.sidebar.title("👑 蜂巢管理")
auto_mode = st.sidebar.toggle("开启自动托管", value=False)
if st.sidebar.button("🔥 重置系统"):
    clients['supabase'].table("drones").delete().neq("id", "RESERVED").execute(); st.rerun()

st.title("🐝 Hive 自动交易员系统")
d_res = clients['supabase'].table("drones").select("*").order("created_at", desc=True).execute().data

for d in d_res:
    with st.container(border=True):
        h_l, h_r = st.columns([5, 1])
        h_l.subheader(f"🐝 {d['name']} | 审计监控")
        if h_r.button("🚀 强制放飞", key=f"f_{d['id']}", type="primary"):
            execute_flight(d['id'], clients); st.cache_data.clear(); st.rerun()

        # 数据审计卡片
        cash, pos = float(d['balance']), d.get('positions') or {}
        mv_total, pos_table = 0.0, []
        for s, q in pos.items():
            px = get_precise_price(clients['poly'], s)
            mv = px * q * 100
            mv_total += mv
            pos_table.append({"代码": s, "持仓": q, "估值": f"${mv:,.2f}"})

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("现金", f"${cash:,.2f}")
        m2.metric("持仓市值", f"${mv_total:,.2f}")
        m3.metric("NAV", f"${cash+mv_total:,.2f}", delta=f"{((cash+mv_total)/100000-1)*100:.2f}%")
        m4.metric("巡逻次数", d.get('patrol_count', 0))

        st.divider()
        c1, c2 = st.columns([1.5, 2])
        with c1:
            st.write("💬 **逻辑修正对谈**")
            u_in = st.text_input("下达修正指令...", key=f"chat_{d['id']}")
            if st.button("发送指令", key=f"btn_{d['id']}"):
                execute_flight(d['id'], clients, u_in); st.cache_data.clear(); st.rerun()
        with c2:
            st.write("📦 **投资组合**")
            if pos_table: st.dataframe(pd.DataFrame(pos_table), hide_index=True, use_container_width=True)
            else: st.caption("空仓")

        st.divider()
        for log in (d.get('logs') or [])[:10]:
            with st.chat_message("assistant", avatar="🐝"):
                parts = log.split(" || ")
                if len(parts) >= 3:
                    st.markdown(f"**{parts[0]}**")
                    st.markdown(f"**{parts[1]}**")
                    st.markdown(f"**🧠 思考:**\n{parts[2].replace('🧠 思考:', '').strip()}")
                    st.markdown(f"**⚡ 行动:** {parts[3]}")

if auto_mode and d_res:
    if "last_auto_run" not in st.session_state: st.session_state.last_auto_run = 0
    now = time.time()
    if (now - st.session_state.last_auto_run) > 300:
        if execute_flight(d_res[0]['id'], clients):
            st.session_state.last_auto_run = now
            st.cache_data.clear(); st.rerun()
    else:
        st.sidebar.metric("下次研判倒计时", f"{int(300 - (now - st.session_state.last_auto_run))} 秒")
        time.sleep(2); st.rerun()