import streamlit as st

# --- 🚨 红线 1: 全局变量与 UI 强制渲染 ---
VERSION = "v8.2 (Transparent Decision)"
STRATEGY_LIB = {
    "波动率专家": "分析 IV 偏离，识别回归或突破时机。",
    "末日博弈": "聚焦高 Gamma，捕捉极速爆发收益。",
    "机构大单": "监控 OI/Vol 异动，识别主力新开仓信号。"
}

st.set_page_config(page_title="Hive 智能金融", layout="wide")
st.title("🐝 Hive 智能金融蜂群")

import re, json, time, os, random, pytz
import pandas as pd
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from supabase import create_client
from google import genai 

# --- 🚨 红线 2: 虎眼核心工具函数 ---
def get_val(obj, *keys):
    if not obj: return 0.0
    for k in keys:
        v = getattr(obj, k, None)
        if v is not None: return float(v)
    return 0.0

@st.cache_resource
def init_hive_engine():
    try:
        from polygon import RESTClient
        return {
            "supabase": create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"]),
            "gen_client": genai.Client(api_key=st.secrets["GEMINI_KEY"]),
            "poly": RESTClient(api_key=st.secrets["POLYGON_KEY"])
        }, None
    except Exception as e: return None, str(e)

# --- 🚀 虎眼行情引擎 ---
def fetch_tiger_data(ticker, poly):
    try:
        tz = pytz.timezone('US/Eastern')
        tk = ticker.upper()
        sn = poly.get_snapshot_ticker("stocks", tk)
        prev = poly.get_previous_close_agg(tk)
        y_close = get_val(prev[0] if prev else None, 'close')
        lt, lq = getattr(sn, 'last_trade', None), getattr(sn, 'last_quote', None)
        tp = get_val(lt, 'p', 'price')
        bp, ap = get_val(lq, 'p', 'bid'), get_val(lq, 'P', 'ask')
        curr_p = tp if tp > 0 else (((bp+ap)/2) if (bp>0 and ap>0) else y_close)
        
        opts = list(poly.list_snapshot_options_chain(tk, params={"strike_price.gte": curr_p*0.9, "strike_price.lte": curr_p*1.1, "limit": 30}))
        rows, v_sum = [], {'c': 0, 'p': 0}
        for o in opts:
            vol, oi = int(get_val(o.day, 'volume')), int(get_val(o, 'open_interest'))
            olq, olt = getattr(o, 'last_quote', None), getattr(o, 'last_trade', None)
            op = (get_val(olq, 'p', 'bid') + get_val(olq, 'P', 'ask'))/2 or get_val(olt, 'p', 'price')
            if op <= 0: continue
            g = getattr(o, 'greeks', None)
            rows.append({
                "信号": "🔥新开仓" if (vol > oi and vol > 100) else "-",
                "合约": o.details.ticker, "行权价": o.details.strike_price, "实时价": round(op, 3),
                "Δ": round(get_val(g, 'delta'), 3), "Γ": round(get_val(g, 'gamma'), 4),
                "IV": f"{get_val(o, 'implied_volatility')*100:.1f}%", "成交量": vol, "持仓量": oi
            })
        df = pd.DataFrame(rows).sort_values(by="成交量", ascending=False)
        return {"ticker": tk, "price": curr_p, "df": df, "status": "OK"}
    except Exception as e:
        return {"ticker": ticker, "status": f"Err: {e}", "price": 0.0, "df": pd.DataFrame()}

# --- 🧠 演化执行核心 ---
def execute_evolution(d, slot, clients):
    with slot:
        targets = d.get('portfolio') or ['GLD']
        st.write(f"📡 **正在穿透虎眼情报流: {targets}**")
        
        with ThreadPoolExecutor(max_workers=len(targets)) as exe:
            results = list(exe.map(lambda t: fetch_tiger_data(t, clients['poly']), targets))
        
        # 🚨 坑 6: 过程透明化，将采集到的数据喂给 AI 前先展示
        ai_brief = {}
        for res in results:
            if res['status'] == "OK":
                st.subheader(f"💎 {res['ticker']} 实时情报 (现价: ${res['price']:.2f})")
                st.dataframe(res['df'].head(15), use_container_width=True)
                # 转化数据为 AI 易读格式
                ai_brief[res['ticker']] = {
                    "current_price": res['price'],
                    "option_moves": res['df'].head(10).to_dict('records')
                }
        
        if not ai_brief:
            st.warning("⚠️ 采集到空情报，工蜂选择按兵不动。"); return

        # 2. 决策研判 (强效 Prompt 注入)
        st.write("🧠 **正在将情报提交至中枢研判...**")
        prompt = f"""
        你是工蜂 {d['name']}，具有【{d.get('style', '通用')}】特质。
        当前现金: ${d['balance']} | 持仓: {json.dumps(d.get('positions'))}
        
        市场情报:
        {json.dumps(ai_brief, ensure_ascii=False, indent=2)}
        
        要求：
        1. 必须基于希腊值和期权异动进行中文策略分析。
        2. 必须返回 JSON 格式：{{"thought": "中文分析过程", "trades": [{"ticker":"合约或现货代码", "qty":10, "action":"BUY/SELL"}]}}
        3. 如果认为观望更佳，trades 数组应为空，但 thought 必须说明理由。
        """
        
        try:
            r = clients['gen_client'].models.generate_content(model="gemini-2.0-flash", contents=prompt, config={'response_mime_type': 'application/json'})
            decision = json.loads(r.text)
            thought = decision.get('thought') or "（AI 未提供具体思考逻辑）"
            st.success(f"💭 {d['name']} 深度研判:\n\n{thought}")
            
            # 3. 结算逻辑 (坑 4: 属性面板持久化更新)
            nb, np, logs = float(d.get('balance', 0)), (d.get('positions', {}) or {}).copy(), []
            for t in decision.get('trades', []):
                sym, qty, act = t.get('ticker','').upper(), t.get('qty',0), t.get('action','')
                px = 0.0
                if sym in ai_brief: px = ai_brief[sym]['current_price']
                else: # 尝试在期权链中找价
                    for info in ai_brief.values():
                        for o in info['option_moves']:
                            if o['合约'] == sym: px = o['实时价']
                
                if px <= 0: continue
                cost = qty * px * (100 if len(sym) > 6 else 1)
                if act == 'BUY' and nb >= cost:
                    nb -= cost; np[sym] = np.get(sym, 0) + qty; logs.append(f"买入 {sym}")
                elif act == 'SELL' and np.get(sym, 0) >= qty:
                    nb += cost; np[sym] -= qty; logs.append(f"卖出 {sym}")
                    if np[sym] <= 0: del np[sym]
            
            # 更新数据库 (patrol_count 累加)
            act_str = " | ".join(logs) if logs else "维持观望"
            mv = sum(q * fetch_tiger_data(s, clients['poly'])['price'] for s, q in np.items() if len(s) < 10)
            
            clients['supabase'].table("drones").update({
                "balance": nb, "positions": np, "total_assets": round(nb + mv, 2),
                "logs": ([f"[{datetime.now().strftime('%H:%M:%S')}] {act_str} | {thought}"] + (d.get('logs') or []))[:10],
                "patrol_count": (d.get('patrol_count', 0) + 1)
            }).eq("id", d["id"]).execute()
            st.write(f"📝 **演化结果:** {act_str}")
        except Exception as e:
            st.error(f"❌ 研判中断: {e}")

# --- 🚨 UI 面板持久化 ---
cl_pkg, err = init_hive_engine()
if err: st.error(err); st.stop()
clients = cl_pkg

try: d_res = clients['supabase'].table("drones").select("*").order("created_at", desc=True).execute().data
except: d_res = []

h1, h2 = st.columns([4, 1])
with h1: st.caption(f"{VERSION} | 虎眼逻辑已对齐 | AI 决策透明化")
full_fly = h2.button("🚀 集群全量放飞", type="primary", use_container_width=True)

if full_fly and d_res:
    for d in d_res:
        with st.status(f"🐝 正在调度 {d['name']}...", expanded=True):
            execute_evolution(d, st.container(), clients)
    st.success("✅ 全部演化任务已同步"); st.button("刷新")
    st.stop()

tabs = st.tabs(["🏆 工蜂档案", "👑 蜂后孵化", "⚙️ 系统管理"])
with tabs[0]:
    if not d_res: st.info("空。")
    for d in d_res:
        with st.expander(f"🐝 {d.get('name')} | ${d.get('total_assets',0):,.2f} | 巡逻: {d.get('patrol_count',0)}次"):
            c1, c2 = st.columns(2)
            with c1: st.write(f"🧬 **基因:** {d.get('style', '通用')}"); st.caption(f"🧠 {d.get('persona')}")
            with c2: st.write("**📦 持仓:**"); st.json(d.get('positions', {}))
            if st.button(f"🚀 单独放飞", key=f"f_{d['id']}"):
                execute_evolution(d, st.container(), clients)
            for l in (d.get('logs') or [])[:3]: st.caption(l)