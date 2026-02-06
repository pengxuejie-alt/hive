import streamlit as st
import json, time, os, random, re, pytz
import pandas as pd
from datetime import datetime, timedelta
from supabase import create_client
from google import genai 
from polygon import RESTClient

# ==========================================
# 1. 样式与初始化 (蜂巢 17.0)
# ==========================================
VERSION = "v17.0 (Hive Logic Reboot)"
st.set_page_config(page_title="Hive 智能交易员 v17.0", layout="wide")

st.markdown("""
    <style>
    .time-tag { color: #888; font-size: 0.8rem; font-family: monospace; }
    .data-block { color: #003366; font-weight: bold; font-family: monospace; font-size: 0.95rem; margin: 8px 0; border-bottom: 2px solid #1a73e8; }
    .thought-block { font-size: 0.95rem; color: #111; background: #f0f2f6; padding: 15px; border-radius: 8px; border-left: 5px solid #d93025; margin: 10px 0; line-height: 1.6; }
    .action-block { color: #d93025; font-weight: bold; font-size: 0.95rem; background: #fff5f5; padding: 8px; border-radius: 4px; border: 1px solid #ffcdd2; }
    .error-tag { color: #d93025; font-weight: bold; background: #ffebee; padding: 10px; border-radius: 5px; margin: 10px 0; }
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

# --- 核心取价与期权链抓取 (虎之眼 6.2.1 穿透逻辑) ---
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
            return get_val(poly.get_previous_close_agg(ticker)[0], 'close')
        else:
            snap = poly.get_snapshot_ticker("stocks", ticker)
            lt = getattr(snap, 'last_trade', None)
            tp = get_val(lt, 'p')
            return tp if tp > 0 else get_val(poly.get_previous_close_agg(ticker)[0], 'close')
    except: return 0.0

def fetch_active_options(poly, underlying, curr_p):
    try:
        # 获取平值附近 +-5% 的活跃期权链快照
        chain = list(poly.list_snapshot_options_chain(underlying, params={
            "strike_price.gte": curr_p * 0.95, 
            "strike_price.lte": curr_p * 1.05, 
            "limit": 20
        }))
        opts = []
        for o in chain:
            lq = getattr(o, 'last_quote', None)
            bp, ap = get_val(lq, 'p'), get_val(lq, 'P')
            mid = (bp + ap) / 2 if (bp > 0 and ap > 0) else get_val(o.day, 'close')
            if mid > 0.05:
                opts.append({"ticker": o.ticker, "price": round(mid, 2), "vol": int(get_val(o.day, 'volume'))})
        opts.sort(key=lambda x: x['vol'], reverse=True)
        return opts[:10]
    except: return []

# ==========================================
# 2. 研判逻辑 (带强制异常报告)
# ==========================================
def execute_flight(d_id, clients, user_instruction=None):
    try:
        d = clients['supabase'].table("drones").select("*").eq("id", d_id).single().execute().data
        tk, curr_p = "GLD", get_precise_price(clients['poly'], "GLD")
        
        # 🚨 期权链探测
        market_options = fetch_active_options(clients['poly'], tk, curr_p)
        if not market_options:
            error_log = f"🕒 {datetime.now().strftime('%m-%d %H:%M:%S')} || ⚠️ 研判中断：无法获取期权链弹药 || 🧠 思考: 市场行情接口未响应或非交易时段，无法获取期权流动性数据 || ⚡ 行动: 强制休眠"
            clients['supabase'].table("drones").update({"logs": ([error_log] + (d.get('logs') or []))[:50]}).eq("id", d_id).execute()
            return False

        cash, pos = float(d['balance']), d.get('positions') or {}
        mv_total = sum([get_precise_price(clients['poly'], s) * q * 100 for s, q in pos.items()])
        nav = cash + mv_total

        # 🚨 强制唤醒 Prompt
        prompt = f"""你是{d['name']}。性格:{d.get('style')}。
        NAV:${nav:,.2f} | {tk}现价:${curr_p:.2f} | 现金:${cash:,.2f}
        [可用期权代码]: {json.dumps(market_options)}
        [当前持仓]: {json.dumps(pos)}
        指令: 请基于当前持仓和可用期权，深度中文思考下一步动作。若你是激进型，请利用期权进行杠杆操作。返回严格JSON格式。"""
        
        if user_instruction:
            prompt += f"\n用户特别指令: {user_instruction}"

        r = clients['gen_client'].models.generate_content(model="gemini-2.0-flash", contents=prompt, config={'response_mime_type': 'application/json'})
        res = json.loads(r.text)
        
        # 思考与交易逻辑
        thought = res.get('thought') or res.get('analysis') or "🚨 AI 返回了空思考，请检查模型连接。"
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
        log_entry = f"🕒 {now_tag} || 📊 {tk}:${curr_p:.2f} | NAV:${nav:,.2f} | 现金:${cash:,.2f} || 🧠 思考: {thought} || ⚡ 行动: {(' | '.join(exec_logs) if exec_logs else '持仓观望')}"
        
        clients['supabase'].table("drones").update({
            "balance": nb, "positions": np, 
            "logs": ([log_entry] + (d.get('logs') or []))[:100],
            "patrol_count": d.get('patrol_count', 0) + 1
        }).eq("id", d_id).execute()
        return True
    except Exception as e:
        st.error(f"逻辑崩溃: {e}"); return False

# ==========================================
# 3. 界面渲染 (蜂巢管理台)
# ==========================================
st.sidebar.title("👑 蜂后控制中心")
with st.sidebar.expander("🐣 孵化新工蜂"):
    n_name = st.text_input("工蜂名称", value=f"AI-{random.randint(100,999)}")
    n_dna = st.text_area("DNA 指令", value="激进型 | 末日博弈 | 专注 GLD 期权")
    if st.button("开始孵化", use_container_width=True):
        clients['supabase'].table("drones").insert({"name": n_name, "style": n_dna, "balance": 100000.0, "positions": {}, "logs": []}).execute()
        st.rerun()

auto_mode = st.sidebar.toggle("🤖 开启 5 分钟自动托管", value=False)
if st.sidebar.button("🔥 清空所有工蜂数据"):
    clients['supabase'].table("drones").delete().neq("id", "RESERVED").execute()
    st.rerun()

st.title("🐝 Hive 自动交易员蜂巢系统")
d_res = clients['supabase'].table("drones").select("*").order("created_at", desc=True).execute().data

for d in d_res:
    with st.container(border=True):
        h_l, h_r = st.columns([5, 1])
        h_l.subheader(f"🐝 {d['name']} | 资产审计监控")
        if h_r.button("🚀 强制研判", key=f"f_{d['id']}", type="primary"):
            execute_flight(d['id'], clients)
            st.cache_data.clear(); st.rerun()

        # 数据指标
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
        m3.metric("NAV (净值)", f"${cash+mv_total:,.2f}", delta=f"{((cash+mv_total)/100000-1)*100:.2f}%")
        m4.metric("巡逻深度", d.get('patrol_count', 0))

        st.divider()
        c1, c2 = st.columns([1.5, 2])
        with c1:
            st.write("💬 **逻辑修正对谈**")
            u_in = st.text_input("对该工蜂下达指令...", key=f"chat_{d['id']}")
            if st.button("发送并执行", key=f"btn_{d['id']}"):
                execute_flight(d['id'], clients, u_in)
                st.cache_data.clear(); st.rerun()
        with c2:
            st.write("📦 **实时投资组合**")
            if pos_table: st.dataframe(pd.DataFrame(pos_table), hide_index=True, use_container_width=True)
            else: st.caption("账户空仓")

        st.divider()
        for log in (d.get('logs') or [])[:15]:
            with st.chat_message("assistant", avatar="🐝"):
                parts = re.split(r'\s+\|\|\s+|\s+\|\s+', log)
                if len(parts) >= 3:
                    st.markdown(f'<span class="time-tag">{parts[0]}</span><div class="data-block">{parts[1]}</div><div class="thought-block">{parts[2].replace("🧠 思考:", "").strip()}</div><div class="action-block">{parts[3]}</div>', unsafe_allow_html=True)

# 自动托管
if auto_mode and d_res:
    if "last_auto_run" not in st.session_state: st.session_state.last_auto_run = 0
    now = time.time()
    if (now - st.session_state.last_auto_run) > 300:
        if execute_flight(d_res[0]['id'], clients):
            st.session_state.last_auto_run = now
            st.cache_data.clear(); st.rerun()
    else:
        st.sidebar.metric("下次自动巡逻", f"{int(300 - (now - st.session_state.last_auto_run))} 秒")
        time.sleep(2); st.rerun()