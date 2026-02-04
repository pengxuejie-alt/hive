import streamlit as st
import json, time, os, random, re, pytz
import pandas as pd  # 🚨 确保 Pandas 导入，防止 NameError
from datetime import datetime, timedelta
from supabase import create_client
from google import genai 
from polygon import RESTClient

# ==========================================
# 1. 核心初始化 (复刻虎之眼 v6.3.1 架构)
# ==========================================
VERSION = "v12.6 (Professional Wealth Edition)"
st.set_page_config(page_title="Hive 智能金融蜂群", layout="wide")

# 注入专业理财软件风格的 CSS
st.markdown("""
    <style>
    .metric-card { background-color: #f8f9fa; padding: 15px; border-radius: 10px; border-left: 5px solid #007bff; }
    .audit-data { color: #6c757d; font-size: 0.9rem; margin-bottom: 5px; }
    .audit-thought { color: #212529; background-color: #e9ecef; padding: 10px; border-radius: 5px; margin: 5px 0; }
    .audit-action { font-weight: bold; color: #28a745; }
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
if err: st.error(f"引擎启动失败: {err}"); st.stop()
clients = cl_pkg

# --- 虎之眼专用取值工具 (复刻附件逻辑) ---
def get_val(obj, *keys):
    if not obj: return 0.0
    for k in keys:
        v = getattr(obj, k, None)
        if v is not None: return float(v)
    return 0.0

# ==========================================
# 2. 虎之眼高精度穿透逻辑 (修复 GLD 0 价格问题)
# ==========================================
def get_verified_price(poly, ticker):
    try:
        # 判断是期权合约还是股票标的 (核心修复：不再盲目加 O:)
        is_option = ticker.startswith("O:") or len(ticker) > 10
        
        if not is_option:
            # --- 股票标的路径 (如 GLD) ---
            snap = poly.get_snapshot_ticker("stocks", ticker)
            prev = poly.get_previous_close_agg(ticker)
            y_close = get_val(prev[0] if prev else None, 'close')
            
            lt, lq = getattr(snap, 'last_trade', None), getattr(snap, 'last_quote', None)
            tp = get_val(lt, 'p', 'price') # 实时成交
            bp = get_val(lq, 'p', 'bid')   # 买入价
            ap = get_val(lq, 'P', 'ask')   # 卖出价
            
            # 优先级: 实时成交价 > 买卖价中值 > 昨日收盘价
            curr_p = tp if tp > 0 else (((bp + ap) / 2) if (bp > 0 and ap > 0) else y_close)
            return curr_p
        else:
            # --- 期权路径 (分钟线回溯过滤 0 成交) ---
            end = datetime.now()
            start = end - timedelta(days=5)
            aggs = poly.get_aggs(ticker, 1, "minute", start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
            if aggs:
                for i in range(len(aggs)-1, -1, -1):
                    if aggs[i].volume > 0: return float(aggs[i].close)
            prev = poly.get_previous_close_agg(ticker)
            return float(prev[0].close) if prev else 0.0
    except:
        return 0.0

def parse_symbol(symbol):
    if not symbol.startswith("O:"): return symbol
    match = re.match(r"O:([A-Z]+)(\d{2})(\d{2})(\d{2})([CP])(\d+)", symbol)
    if match:
        tk, yy, mm, dd, cp, strike = match.groups()
        return f"{tk} {mm}/{dd} ${int(strike)/1000} {'Call' if cp=='C' else 'Put'}"
    return symbol

# ==========================================
# 3. 三维度决策引擎 (Data / Thought / Action)
# ==========================================
def execute_flight_v12(d, clients):
    dna = d.get('style', 'Risk:Neutral')
    history = (d.get('logs') or [])[:3]
    tk = "GLD"
    curr_p = get_verified_price(clients['poly'], tk)
    
    prompt = f"""你是{d['name']}。性格DNA:{dna} | 历史记忆:{history}
    当前市场数据: 现金${d['balance']:,.2f}, 持仓{json.dumps(d.get('positions'))}, {tk}实时现价${curr_p}
    
    请严格按 JSON 格式返回汇报：
    {{
      "data_rpt": "记录当前行情异动和关键数据点",
      "thought": "基于 DNA 和历史记忆的推演过程",
      "action_plan": "决定买卖的具体逻辑",
      "trades": [{"ticker": "O:...", "qty": 10, "action": "BUY/SELL"}]
    }}"""
    
    try:
        r = clients['gen_client'].models.generate_content(model="gemini-2.0-flash", contents=prompt, config={'response_mime_type': 'application/json'})
        res = json.loads(r.text)
        nb, np = float(d['balance']), (d.get('positions') or {}).copy()
        exec_logs = []
        
        for t in res.get('trades', []):
            sym, qty, act = t['ticker'].upper(), int(t['qty']), t['action'].upper()
            px = get_verified_price(clients['poly'], sym)
            if px <= 0: continue
            cost = px * qty * (100 if "O:" in sym else 1)
            
            if act == 'BUY' and nb >= cost:
                nb -= cost; np[sym] = np.get(sym, 0) + qty
                exec_logs.append(f"买入 {qty}手 {sym} @${px:.2f}")
            elif act == 'SELL' and np.get(sym, 0) >= qty:
                nb += cost; np[sym] -= qty
                if np[sym] <= 0: del np[sym]
                exec_logs.append(f"卖出 {qty}手 {sym} @${px:.2f}")

        # 构造三段审计日志
        full_log = f"📊 数据:{res.get('data_rpt')} | 🧠 思考:{res.get('thought')} | ⚡ 行动:{' | '.join(exec_logs) if exec_logs else '持仓观望'}"
        
        clients['supabase'].table("drones").update({
            "balance": nb, "positions": np, "patrol_count": d.get('patrol_count', 0)+1,
            "logs": ([full_log] + (d.get('logs') or []))[:20]
        }).eq("id", d["id"]).execute()
        return True
    except: return False

# ==========================================
# 4. 专业金融看板渲染 (通栏卡片式布局)
# ==========================================
st.title("🐝 Hive 智能金融审计中心")
tabs = st.tabs(["🏆 蜂群看板", "👑 DNA 孵化器", "⚙️ 管理"])

with tabs[0]:
    d_res = clients['supabase'].table("drones").select("*").order("created_at", desc=True).execute().data
    for d in d_res:
        with st.container(border=True): # 🏆 通栏专业卡片
            # 第一行：标题栏与操作按钮 (置顶对齐)
            head_l, head_r = st.columns([5, 1])
            with head_l:
                st.subheader(f"🐝 工蜂实例: {d['name']}")
                st.caption(f"ID: {d['id']} | 巡逻频次: {d.get('patrol_count', 0)}")
            with head_r:
                if st.button(f"🔥 执行研判", key=f"f_{d['id']}", type="primary", use_container_width=True):
                    if execute_flight_v12(d, clients): st.rerun()

            # 第二行：资产健康指标 (专业 Metric 网格)
            cash, pos = float(d.get('balance', 0.0)), d.get('positions', {})
            mv_total, pos_table = 0.0, []
            for sym, qty in pos.items():
                px = get_verified_price(clients['poly'], sym)
                mv = px * qty * (100 if "O:" in sym else 1)
                mv_total += mv
                pos_table.append({"代码": parse_symbol(sym), "头寸": f"{qty}手", "单价": f"${px:.2f}", "估值": f"${mv:,.2f}"})

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("可用现金 (Cash)", f"${cash:,.2f}")
            m2.metric("持仓估值 (MV)", f"${mv_total:,.2f}")
            m3.metric("总资产净值 (NAV)", f"${cash+mv_total:,.2f}", delta=f"{((cash+mv_total)/100000-1)*100:.2f}%")
            m4.metric("审计健康度", "良好" if len(d.get('logs', [])) > 5 else "观测中")

            st.divider()

            # 第三行：核心情报 (DNA 与 实时头寸并排)
            info_l, info_r = st.columns([1, 2])
            with info_l:
                st.write("🧬 **DNA 决策序列**")
                dna_raw = d.get('style', '')
                if " | " in dna_raw:
                    for frag in dna_raw.split(' | '): st.info(frag)
                else:
                    st.warning(dna_raw)
                    if st.button("基因提纯", key=f"re_{d['id']}"):
                        new_dna = clients['gen_client'].models.generate_content(model="gemini-2.0-flash", contents=f"重构DNA短语: {dna_raw}").text.strip()
                        clients['supabase'].table("drones").update({"style": new_dna}).eq("id", d["id"]).execute(); st.rerun()
            
            with info_r:
                st.write("📦 **实时投资组合 (Portfolio)**")
                if pos_table:
                    st.dataframe(pd.DataFrame(pos_table), hide_index=True, use_container_width=True)
                else:
                    st.caption("当前账户无活跃头寸")

            # 第四行：三维度审计记忆 (平铺展开，消除滑动冲突)
            st.divider()
            st.write("🧠 **三维度决策审计轨迹 (Data / Thought / Action)**")
            logs = d.get('logs') or []
            if logs:
                for l in logs[:5]: # 仅展示最近5次，保证页面不至于过长
                    parts = l.split(" | ")
                    with st.chat_message("assistant", avatar="🐝"):
                        for p in parts:
                            if "📊 数据" in p: st.markdown(f"**{p}**")
                            elif "🧠 思考" in p: st.caption(p)
                            elif "⚡ 行动" in p:
                                if "买入" in p or "卖出" in p: st.success(p)
                                else: st.warning(p)
            else:
                st.caption("等待首次放飞以生成审计记忆...")