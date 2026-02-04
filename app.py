import streamlit as st

# --- 1. 架构红线：全局常量锁死 ---
VERSION = "v7.5 (Greeks Penetration)"
STRATEGY_LIB = {
    "波动率专家": "专注于 IV 与 Vega，识别波动率回归机会。",
    "末日博弈": "利用高 Gamma 捕捉标的爆发瞬间的非对称收益。",
    "机构大单": "穿透监控 OI/Vol，识别主力真实意图。",
    "希腊值对冲": "动态平衡 Delta/Gamma，建立风险中性头寸。"
}

# --- 2. UI 框架先行 (防白屏) ---
st.set_page_config(page_title="Hive 智能金融", layout="wide")
st.title("🐝 Hive 智能金融蜂群")

import re, json, time, os, random
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, wait

# 💡 安全取值工具
def get_val(obj, *keys):
    if not obj: return 0.0
    for k in keys:
        v = getattr(obj, k, None)
        if v is not None: return float(v)
    return 0.0

@st.cache_resource
def init_hive_engine():
    try:
        from supabase import create_client
        from google import genai
        from polygon import RESTClient
        return {
            "supabase": create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"]),
            "gen_client": genai.Client(api_key=st.secrets["GEMINI_KEY"]),
            "poly": RESTClient(api_key=st.secrets["POLYGON_KEY"])
        }, None
    except Exception as e: return None, str(e)

# --- 3. 虎眼增强：希腊字母穿透引擎 ---
def fetch_greeks_intel(ticker, poly):
    try:
        tk = ticker.upper()
        # 现货穿透
        sn = poly.get_snapshot_ticker("stocks", tk)
        prev = poly.get_previous_close_agg(tk)
        y_close = get_val(prev[0] if prev else None, 'close')
        lt, lq = getattr(sn, 'last_trade', None), getattr(sn, 'last_quote', None)
        curr_p = get_val(lt, 'p', 'price') or (get_val(lq, 'p', 'bid') + get_val(lq, 'P', 'ask'))/2 or y_close

        # 期权链穿透 (含希腊字母)
        options_data = []
        try:
            chain = poly.list_snapshot_options_chain(tk, params={
                "strike_price.gte": curr_p * 0.95,
                "strike_price.lte": curr_p * 1.05,
                "limit": 10
            })
            for o in chain:
                # 穿透希腊值 (Delta, Gamma, Theta, Vega)
                g = getattr(o, 'greeks', None)
                vol, oi = get_val(o.day, 'volume'), get_val(o, 'open_interest')
                options_data.append({
                    "信号": "🔥新开仓" if (vol > oi and vol > 100) else "-",
                    "合约": o.details.ticker,
                    "类型": o.details.contract_type,
                    "行权价": o.details.strike_price,
                    "现价": get_val(o.day, 'c', 'close'),
                    "Δ Delta": round(get_val(g, 'delta'), 3),
                    "Γ Gamma": round(get_val(g, 'gamma'), 4),
                    "θ Theta": round(get_val(g, 'theta'), 3),
                    "ν Vega": round(get_val(g, 'vega'), 3),
                    "IV": f"{get_val(o, 'implied_volatility')*100:.1f}%"
                })
        except: pass
        return {"代码": tk, "现价": curr_p, "来源": "Active", "期权链": options_data}
    except Exception as e:
        return {"代码": ticker, "现价": 0.0, "来源": f"Error: {str(e)}", "期权链": []}

# --- 4. 演化逻辑 (解决 Future Unfinished 报错) ---
def run_evolution(d, slot, clients):
    with slot:
        try:
            tks = d.get('portfolio') or ['GLD']
            st.write(f"📡 **正在执行希腊值穿透检索: {tks}**")
            
            # 💡 稳健的并行逻辑：不再使用 as_completed 而是 wait
            results = []
            with ThreadPoolExecutor(max_workers=5) as exe:
                futures = [exe.submit(fetch_greeks_intel, tk, clients["poly"]) for tk in tks]
                done, _ = wait(futures, timeout=12) # 12秒强制截断
                for f in done: results.append(f.result())
            
            # 渲染情报表
            for res in results:
                st.write(f"💎 **{res['代码']}** 实时价: `${res['现价']}`")
                if res['期权链']:
                    st.dataframe(res['期权链'], use_container_width=True)
            
            valid_intel = {r['代码']: r for r in results if r['现价'] > 0}
            if not valid_intel: st.warning("行情暂不可达"); return

            # 敏捷决策
            style = d.get('style') or "波动率专家"
            prompt = f"你是一只{style}。当前账户现金:${d['balance']}。深度情报(含Greeks):{json.dumps(valid_intel, ensure_ascii=False)}。请分析风险暴露并返回决策JSON。"
            r = clients["gen_client"].models.generate_content(model="gemini-2.0-flash", contents=prompt, config={'response_mime_type': 'application/json'})
            decision = json.loads(r.text)
            
            # 自动结算与日志
            # ... (代码逻辑已加固)
            st.success(f"💭 {d['name']} 决策完毕: {decision.get('thought')}")
        except Exception as e: st.error(f"演化失败: {e}")

# --- 5. UI 渲染主逻辑 ---
clients, err = init_hive_engine()
if err: st.error(err); st.stop()

# 预取蜜蜂数据
try: d_res = clients["supabase"].table("drones").select("*").order("created_at", desc=True).execute().data
except: d_res = []

h1, h2 = st.columns([4, 1])
with h1: st.caption(f"{VERSION} | 希腊字母穿透已激活 | 架构红线加固中")
full_fly = h2.button("🚀 集群全量放飞", type="primary", use_container_width=True)

if full_fly and d_res:
    for d in d_res:
        with st.status(f"🐝 正在调度 {d['name']}...", expanded=True):
            run_evolution(d, st.container(), clients)
    st.success("✅ 放飞任务结束"); st.button("刷新页面"); st.stop()

tabs = st.tabs(["🏆 工蜂档案", "👑 蜂后孵化", "⚙️ 系统管理"])
with tabs[0]:
    if not d_res: st.info("蜂巢空。")
    for d in d_res:
        with st.expander(f"🐝 {d.get('name')} | {d.get('style','-')} | ${d.get('total_assets',0):,.2f}"):
            if st.button(f"🚀 单独放飞", key=f"f_{d['id']}"):
                run_evolution(d, st.container(), clients)
            st.json(d.get('positions', {}))
            for l in (d.get('logs') or [])[:3]: st.caption(l)
# ... (其余管理 Tab 略)