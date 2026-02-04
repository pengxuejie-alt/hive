import streamlit as st

# ==========================================
# 🚨 红线 1: 全局常量与 UI 强制渲染 (解决 NameError & 白屏)
# ==========================================
VERSION = "v8.9 (Full Dashboard & Cluster Fix)"
STRATEGY_LIB = {
    "波动率专家": "分析 IV 偏离，识别回归或突破时机。",
    "末日博弈": "聚焦高 Gamma，捕捉极速爆发收益。",
    "机构大单": "监控 OI/Vol 异动，识别主力新开仓信号。",
    "黄金猎手": "专注 GLD 深度波动，捕捉黄金市场套利空间。"
}

st.set_page_config(page_title="Hive 智能金融", layout="wide")
st.title("🐝 Hive 智能金融蜂群")

import json, time, os, random, pytz
import pandas as pd
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, wait
from supabase import create_client
from google import genai 
from polygon import RESTClient

# ==========================================
# 🚨 红线 2: 虎眼核心工具函数 (1:1 镜像)
# ==========================================
def get_val(obj, *keys):
    if not obj: return 0.0
    for k in keys:
        v = getattr(obj, k, None)
        if v is not None: return float(v)
    return 0.0

@st.cache_resource
def init_hive_engine():
    try:
        pk, gk = st.secrets["POLYGON_KEY"], st.secrets["GEMINI_KEY"]
        su, sk = st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"]
        return {
            "supabase": create_client(su, sk),
            "gen_client": genai.Client(api_key=gk),
            "poly": RESTClient(api_key=pk)
        }, None
    except Exception as e: return None, str(e)

# --- 🚀 虎眼级：暴力情报采集 (带并发碰撞保护) ---
def fetch_tiger_intel(ticker, poly):
    try:
        # 💡 解决 A-928 报错：加入随机微延迟，避开 Polygon 频率限制
        time.sleep(random.uniform(0.1, 0.6))
        tk = ticker.upper()
        sn = poly.get_snapshot_ticker("stocks", tk)
        prev = poly.get_previous_close_agg(tk)
        y_close = get_val(prev[0] if prev else None, 'close')
        
        lt, day = getattr(sn, 'last_trade', None), getattr(sn, 'day', None)
        # 优先级：成交价 > 今日收盘 > 昨日收盘
        curr_p = get_val(lt, 'p', 'price') or get_val(day, 'c') or y_close
        
        if curr_p <= 0: return {"ticker": tk, "status": "NO_PRICE", "price": 0.0, "df": pd.DataFrame()}

        chain = list(poly.list_snapshot_options_chain(tk, params={"strike_price.gte": curr_p*0.9, "strike_price.lte": curr_p*1.1, "limit": 20}))
        rows = []
        for o in chain:
            vol, oi = int(get_val(o.day, 'volume')), int(get_val(o, 'open_interest'))
            g = getattr(o, 'greeks', None)
            olq, olt = getattr(o, 'last_quote', None), getattr(o, 'last_trade', None)
            op = (get_val(olq, 'p', 'bid') + get_val(olq, 'P', 'ask'))/2 or get_val(olt, 'p', 'price')
            if op <= 0: continue
            rows.append({
                "信号": "🔥新开仓" if (vol > oi and vol > 100) else "-",
                "合约": o.details.ticker, "类型": o.details.contract_type.upper(),
                "行权价": o.details.strike_price, "现价": round(op, 3),
                "Δ Delta": round(get_val(g, 'delta'), 3), "成交量": vol, "持仓量": oi
            })
        return {"ticker": tk, "price": curr_p, "df": pd.DataFrame(rows).sort_values(by="成交量", ascending=False) if rows else pd.DataFrame(), "status": "OK"}
    except Exception as e: return {"ticker": ticker, "status": str(e), "price": 0.0, "df": pd.DataFrame()}

# ==========================================
# 🧠 演化执行逻辑 (结算、资产核算与看板持久化)
# ==========================================
def execute_evolution(d, slot, clients):
    with slot:
        targets = d.get('portfolio') or ['GLD']
        st.write(f"📡 **同步情报流: {targets}**")
        
        with ThreadPoolExecutor(max_workers=len(targets)) as exe:
            results = [exe.submit(fetch_tiger_intel, tk, clients['poly']).result() for tk in targets]
        
        ai_brief = {}
        for res in results:
            if res['status'] == "OK" and res['price'] > 0:
                st.subheader(f"💎 {res['ticker']} 现价: ${res['price']:.2f}")
                if not res['df'].empty:
                    st.dataframe(res['df'].head(8), use_container_width=True)
                    ai_brief[res['ticker']] = {"price": res['price'], "options": res['df'].head(5).to_dict('records')}

        if not ai_brief:
            st.error(f"❌ {d['name']} 采集受阻。可能原因：标的错误或 API 频率限制。"); return

        # 💡 强制研判深度：解决敷衍分析问题
        raw_t = """
        你是工蜂 [N]，特质基因: [S]。
        当前现金: [B] | 当前持仓: [P]。
        情报: [I]。
        要求：
        1. 必须返回 JSON: {"thought": "详细的中文字数不少于50字的策略分析", "trades": [{"ticker":"代码", "qty":1, "action":"BUY/SELL"}]}
        2. 若决定观望，trades 设为空，但 thought 必须基于 Delta 和信号给出理由。
        """
        final_prompt = raw_t.replace("[N]", d['name']).replace("[S]", d.get('style', '通用'))\
                             .replace("[B]", str(d['balance'])).replace("[P]", json.dumps(d.get('positions')))\
                             .replace("[I]", json.dumps(ai_brief, ensure_ascii=False))
        
        try:
            r = clients['gen_client'].models.generate_content(model="gemini-2.0-flash", contents=final_prompt, config={'response_mime_type': 'application/json'})
            decision = json.loads(r.text)
            thought = decision.get('thought', '分析缺失')
            st.success(f"💭 {d['name']} 研判过程:\n\n{thought}")
            
            # --- 💰 资产结算逻辑 ---
            nb = float(d.get('balance', 100000))
            np = (d.get('positions', {}) or {}).copy()
            logs = []

            for t in decision.get('trades', []):
                sym, qty, act = t.get('ticker','').upper(), abs(t.get('qty',0)), t.get('action','').upper()
                px = ai_brief.get(sym, {}).get('price', 0)
                if px <= 0: # 期权检索
                    for info in ai_brief.values():
                        for o in info['options']:
                            if o['合约'] == sym: px = o['现价']
                
                if px > 0:
                    multiplier = 100 if (len(sym) > 6 or "O:" in sym) else 1
                    cost = qty * px * multiplier
                    if act == 'BUY' and nb >= cost:
                        nb -= cost; np[sym] = np.get(sym, 0) + qty
                        logs.append(f"买入 {qty} {sym}")
                    elif act == 'SELL' and np.get(sym, 0) >= qty:
                        nb += cost; np[sym] -= qty
                        if np[sym] <= 0: del np[sym]
                        logs.append(f"卖出 {qty} {sym}")

            # 资产总值核算
            mv = sum(q * ai_brief.get(s, {'price': 0})['price'] for s, q in np.items() if len(s) < 10)
            act_str = " | ".join(logs) if logs else "维持观望"
            
            # 🚨 红线 4: 数据库持久化
            clients['supabase'].table("drones").update({
                "balance": round(nb, 2),
                "positions": np,
                "total_assets": round(nb + mv, 2),
                "patrol_count": (d.get('patrol_count', 0) + 1),
                "logs": ([f"[{datetime.now().strftime('%H:%M:%S')}] {act_str} | {thought}"] + (d.get('logs') or []))[:10]
            }).eq("id", d["id"]).execute()
            
            st.info(f"📊 资产已结算: ${round(nb + mv, 2):,.2f} | 巡逻次数已更新")
        except Exception as e: st.error(f"决策/结算异常: {e}")

# ==========================================
# 🚀 UI 主界面 (看板面板)
# ==========================================
cl_pkg, err = init_hive_engine()
if err: st.error(err); st.stop()
clients = cl_pkg

try: d_res = clients['supabase'].table("drones").select("*").order("created_at", desc=True).execute().data
except: d_res = []

h1, h2 = st.columns([4, 1])
with h1: st.caption(f"{VERSION} | 资产看板与巡逻统计已同步")
if h2.button("🚀 集群放飞", type="primary", use_container_width=True):
    for d in d_res:
        with st.status(f"🐝 正在调度 {d['name']}...", expanded=True):
            execute_evolution(d, st.container(), clients)
    st.rerun()

tabs = st.tabs(["🏆 工蜂档案看板", "👑 孵化中心", "⚙️ 系统管理"])

with tabs[0]:
    if not d_res: st.info("空。")
    for d in d_res:
        with st.expander(f"🐝 {d['name']} | 资产: ${d.get('total_assets',0):,.2f} | 巡逻: {d.get('patrol_count',0)}次", expanded=True):
            m1, m2, m3 = st.columns([1, 1, 2])
            with m1:
                st.metric("现金余额", f"${d['balance']:,.2f}")
                st.write(f"🧬 **特质:** {d['style']}")
            with m2:
                st.write("**📦 持仓明细:**")
                if d.get('positions'): st.json(d['positions'])
                else: st.caption("空仓中")
            with m3:
                st.write("**📜 决策日志:**")
                for log in (d.get('logs') or [])[:3]:
                    st.caption(log)
            if st.button(f"🎯 单独放飞 {d['name']}", key=f"f_{d['id']}"):
                execute_evolution(d, st.container(), clients)

with tabs[1]:
    st.subheader("👑 孵化新工蜂")
    new_style = st.selectbox("选择基因特质:", list(STRATEGY_LIB.keys()))
    if st.button("🔥 立即孵化"):
        clients['supabase'].table("drones").insert({
            "name": f"交易员-{random.randint(100,999)}", "style": new_style,
            "balance": 100000.0, "total_assets": 100000.0, "patrol_count": 0,
            "portfolio": ["GLD"], "positions": {}, "logs": ["诞生于 v8.9"]
        }).execute(); st.rerun()

with tabs[2]:
    if st.button("🗑️ 清空蜂群数据"):
        clients['supabase'].table("drones").delete().neq("name", "RESERVED").execute()
        st.rerun()