import streamlit as st
import json, time, os, random, re, pytz
import pandas as pd
from datetime import datetime, timedelta
from supabase import create_client
from google import genai 
from polygon import RESTClient

# ==========================================
# 1. 系统配置与专业样式
# ==========================================
VERSION = "v17.3 (Tiger Eye Robust Logic)"
st.set_page_config(page_title="Hive 智能交易员蜂巢", layout="wide")

st.markdown("""
    <style>
    .time-tag { color: #888; font-size: 0.8rem; font-family: monospace; }
    .data-block { color: #003366; font-weight: bold; font-family: monospace; font-size: 0.95rem; margin: 8px 0; border-bottom: 2px solid #1a73e8; padding-bottom: 3px; }
    .thought-block { font-size: 0.95rem; color: #111; background: #f0f2f6; padding: 15px; border-radius: 8px; border-left: 5px solid #d93025; margin: 10px 0; line-height: 1.6; }
    .action-block { color: #d93025; font-weight: bold; font-size: 0.95rem; margin-top: 5px; background: #fff5f5; padding: 8px; border-radius: 4px; border: 1px solid #ffcdd2; }
    .dna-tag-radical { background-color: #d93025; color: white; padding: 2px 8px; border-radius: 4px; font-size: 0.8rem; font-weight: bold; display: inline-block; margin-bottom: 5px; }
    .dna-tag-normal { background-color: #e8f0fe; color: #1967d2; padding: 2px 8px; border-radius: 4px; font-size: 0.8rem; display: inline-block; margin-bottom: 5px; }
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
# 2. 核心取价与期权链引擎 (复刻虎之眼 6.2.1)
# ==========================================
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
            # 虎之眼逻辑：优先使用中值价 (Mid-Price)
            if bp > 0 and ap > 0: return (bp + ap) / 2
            prev = poly.get_previous_close_agg(ticker)
            return get_val(prev[0] if prev else None, 'close')
        else:
            snap = poly.get_snapshot_ticker("stocks", ticker)
            lt = getattr(snap, 'last_trade', None)
            lq = getattr(snap, 'last_quote', None)
            tp = get_val(lt, 'p')
            bp, ap = get_val(lq, 'p'), get_val(lq, 'P')
            # 级联取价：成交 > 中值 > 昨收
            if tp > 0: return tp
            if bp > 0 and ap > 0: return (bp + ap) / 2
            prev = poly.get_previous_close_agg(ticker)
            return get_val(prev[0] if prev else None, 'close')
    except: return 0.0

def fetch_tiger_eye_chain(poly, underlying, curr_p):
    """复刻 6.2.1：现价上下 15% 穿透，多维度筛选活跃合约"""
    try:
        chain = list(poly.list_snapshot_options_chain(underlying, params={
            "strike_price.gte": curr_p * 0.85, 
            "strike_price.lte": curr_p * 1.15, 
            "limit": 100
        }))
        opts = []
        for o in chain:
            lq = getattr(o, 'last_quote', None)
            bp, ap = get_val(lq, 'p'), get_val(lq, 'P')
            mid = (bp + ap) / 2 if (bp > 0 and ap > 0) else get_val(o.day, 'close')
            vol = int(get_val(o.day, 'volume'))
            if mid > 0.05:
                opts.append({
                    "ticker": o.ticker, "price": round(mid, 2), "vol": vol,
                    "type": o.details.contract_type.upper() if hasattr(o, 'details') else "N/A"
                })
        opts.sort(key=lambda x: x['vol'], reverse=True)
        return opts[:15]
    except: return []

# ==========================================
# 3. 蜂巢系统管理逻辑
# ==========================================
def hatch_drone(clients, name, dna):
    clients['supabase'].table("drones").insert({
        "name": name, "style": dna, "balance": 100000.0, "positions": {},
        "logs": [f"🕒 初始 | 🐣 {name} 成功孵化 || 📊 资金: $100,000 || 🧠 思考: 正在校准宏观逻辑... || ⚡ 行动: 待命中"]
    }).execute()

def wipe_hive(clients):
    clients['supabase'].table("drones").delete().neq("id", "RESERVED_SYSTEM_ID").execute()

# ==========================================
# 4. 研判与交易大脑 (Brain)
# ==========================================
def execute_flight(d_id, clients, user_instruction=None):
    try:
        d = clients['supabase'].table("drones").select("*").eq("id", d_id).single().execute().data
        tk, curr_p = "GLD", get_precise_price(clients['poly'], "GLD")
        
        # 抓取虎之眼级弹药
        market_options = fetch_tiger_eye_chain(clients['poly'], tk, curr_p)
        
        cash, pos = float(d['balance']), d.get('positions') or {}
        mv_total = sum([get_precise_price(clients['poly'], s) * q * 100 for s, q in pos.items()])
        nav = cash + mv_total

        prompt = f"""你是交易员{d['name']}。DNA性格:{d.get('style')}。
        当前NAV: ${nav:,.2f} | {tk}现价: ${curr_p:.2f} | 现金: ${cash:,.2f}
        [虎之眼可用期权链]: {json.dumps(market_options)}
        [当前持仓]: {json.dumps(pos)}"""
        
        if user_instruction:
            prompt += f"\n🚨 核心指令(优先级最高): {user_instruction}"
        
        prompt += "\n要求: 基于性格和指令，中文详细思考盈亏及风险，给出JSON决策 {thought, trades:[{ticker, qty, action}]}。"
        
        r = clients['gen_client'].models.generate_content(model="gemini-2.0-flash", contents=prompt, config={'response_mime_type': 'application/json'})
        res = json.loads(r.text)
        
        nb, np, exec_logs = cash, pos.copy(), []
        for t in res.get('trades', []):
            sym = (t.get('ticker') or t.get('symbol', "")).upper()
            qty, act = int(t.get('qty', 0)), t.get('action', "").upper()
            px = get_precise_price(clients['poly'], sym)
            if px <= 0: continue
            
            cost = px * qty * (100 if len(sym)>10 else 1)
            if act == 'BUY' and nb >= cost:
                nb -= cost; np[sym] = np.get(sym, 0) + qty
                exec_logs.append(f"买入 {qty}手 {sym} @${px:.2f}")
            elif act == 'SELL' and np.get(sym, 0) >= qty:
                nb += cost; np[sym] -= qty
                if np[sym] <= 0: del np[sym]
                exec_logs.append(f"卖出 {qty}手 {sym} @${px:.2f}")

        now_tag = datetime.now(pytz.timezone('US/Eastern')).strftime('%m-%d %H:%M:%S')
        log_entry = f"🕒 {now_tag} || 📊 {tk}:${curr_p:.2f} | NAV:${nav:,.2f} || 🧠 思考: {res.get('thought', '审计完毕')} || ⚡ 行动: {(' | '.join(exec_logs) if exec_logs else '持仓观望')}"
        
        clients['supabase'].table("drones").update({
            "balance": nb, "positions": np, 
            "logs": ([log_entry] + (d.get('logs') or []))[:100],
            "patrol_count": d.get('patrol_count', 0) + 1
        }).eq("id", d_id).execute()
        return True
    except: return False

# ==========================================
# 5. 蜂巢管理界面
# ==========================================
st.sidebar.title("👑 蜂后控制中心")
with st.sidebar.expander("🐣 孵化新工蜂", expanded=False):
    n_name = st.text_input("工蜂代号", value=f"AI-{random.randint(100,999)}")
    n_dna = st.text_area("DNA 序列", value="激进型 | 末日博弈 | 冷静分析")
    if st.button("开始孵化", use_container_width=True):
        hatch_drone(clients, n_name, n_dna); st.rerun()

st.sidebar.divider()
auto_mode = st.sidebar.toggle("🤖 开启自动托管 (5min)", value=False)

if st.sidebar.button("🔥 清空蜂巢所有数据"):
    wipe_hive(clients); st.cache_data.clear(); st.rerun()

st.title("🐝 Hive 自动交易员蜂巢系统")
d_res = clients['supabase'].table("drones").select("*").order("created_at", desc=True).execute().data

for d in d_res:
    with st.container(border=True):
        h_l, h_r = st.columns([5, 1])
        h_l.subheader(f"🐝 {d['name']} | 资产监控台")
        if h_r.button("🚀 强制研判", key=f"f_{d['id']}", type="primary"):
            if execute_flight(d['id'], clients): st.cache_data.clear(); st.rerun()

        # 核心指标
        cash, pos = float(d['balance']), d.get('positions') or {}
        mv_total, pos_table = 0.0, []
        for s, q in pos.items():
            px = get_precise_price(clients['poly'], s)
            mv = px * q * 100
            mv_total += mv
            pos_table.append({"代码": s, "持仓": q, "中值估值": f"${mv:,.2f}"})

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("现金", f"${cash:,.2f}")
        m2.metric("持仓市值", f"${mv_total:,.2f}")
        m3.metric("NAV (净值)", f"${cash+mv_total:,.2f}", delta=f"{((cash+mv_total)/100000-1)*100:.2f}%")
        m4.metric("巡逻深度", d.get('patrol_count', 0))

        st.divider()
        c1, c2 = st.columns([1.5, 2])
        with c1:
            st.write("🧬 **DNA 序列**")
            for frag in d.get('style', '').split(' | '):
                t_s = "dna-tag-radical" if "激进" in frag else "dna-tag-normal"
                st.markdown(f'<span class="{t_s}">{frag}</span>', unsafe_allow_html=True)
            
            st.divider()
            # 🚨 灵魂对话框 (指令修正)
            st.write("💬 **逻辑对谈 / 指令修正**")
            u_input = st.text_input("下达修正指令 (如:忽略DXY铁律)...", key=f"chat_{d['id']}")
            if st.button("更新指令并研判", key=f"btn_{d['id']}"):
                if execute_flight(d['id'], clients, u_input): st.cache_data.clear(); st.rerun()
        
        with c2:
            st.write("📦 **实时投资组合 (Portfolio)**")
            if pos_table: st.dataframe(pd.DataFrame(pos_table), hide_index=True, use_container_width=True)
            else: st.caption("当前账户无持仓")

        st.divider()
        st.write("🧠 **三维度审计记忆 (Data / Thought / Action)**")
        for log in (d.get('logs') or [])[:15]:
            with st.chat_message("assistant", avatar="🐝"):
                parts = re.split(r'\s+\|\|\s+|\s+\|\s+', log)
                if len(parts) >= 3:
                    st.markdown(f'<span class="time-tag">{parts[0]}</span><div class="data-block">{parts[1]}</div><div class="thought-block">{parts[2].replace("🧠 思考:", "").strip()}</div><div class="action-block">{parts[3]}</div>', unsafe_allow_html=True)

# 托管逻辑
if auto_mode and d_res:
    if "last_auto_run" not in st.session_state: st.session_state.last_auto_run = 0
    now = time.time()
    if (now - st.session_state.last_auto_run) > 300:
        if execute_flight(d_res[0]['id'], clients):
            st.session_state.last_auto_run = now
            st.cache_data.clear(); st.rerun()
    else:
        st.sidebar.metric("下次巡逻倒计时", f"{int(300 - (now - st.session_state.last_auto_run))} 秒")
        time.sleep(2); st.rerun()