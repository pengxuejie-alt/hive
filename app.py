import streamlit as st

# ==========================================
# 🚨 红线 1: 全局常量定义 (彻底解决 NameError & 白屏)
# ==========================================
VERSION = "v8.6 (Tiger-Eye Mirror Core)"
STRATEGY_LIB = {
    "波动率专家": "分析 IV 偏离，识别回归或突破时机。",
    "末日博弈": "聚焦高 Gamma，捕捉极速爆发收益。",
    "机构大单": "监控 OI/Vol 异动，识别主力新开仓信号。",
    "风险平价": "动态平衡仓位，维持组合生存力。"
}

# ==========================================
# 🚨 红线 2: UI 框架强制先行渲染 (严禁白屏)
# ==========================================
st.set_page_config(page_title="Hive 智能金融", layout="wide")
st.title("🐝 Hive 智能金融蜂群")

import re, json, time, os, random, pytz
import pandas as pd
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, wait
from supabase import create_client
from google import genai  # ✅ 红线 3: 库名对正
from polygon import RESTClient

# ==========================================
# 🚨 红线 2 (续): 虎眼核心工具函数 (1:1 镜像)
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

# --- 🚀 虎眼级：暴力情报采集引擎 (同步附件逻辑) ---
def fetch_tiger_intel(ticker, poly):
    try:
        tk = ticker.upper()
        # 1. 现货三级取价保底 (Trade > Day Close > Previous Close)
        sn = poly.get_snapshot_ticker("stocks", tk)
        prev = poly.get_previous_close_agg(tk)
        y_close = get_val(prev[0] if prev else None, 'close')
        
        lt = getattr(sn, 'last_trade', None)
        day = getattr(sn, 'day', None)
        curr_p = get_val(lt, 'p', 'price') or get_val(day, 'c') or y_close
        
        # 2. 期权链分层穿透 (同步虎眼筛选逻辑)
        rows = []
        # 💡 关键修复：强制 list(...) 释放生成器，防止线程死锁
        chain = list(poly.list_snapshot_options_chain(tk, params={
            "strike_price.gte": curr_p * 0.9,
            "strike_price.lte": curr_p * 1.1,
            "limit": 30
        }))
        
        for o in chain:
            vol, oi = int(get_val(o.day, 'volume')), int(get_val(o, 'open_interest'))
            g = getattr(o, 'greeks', None)
            olq, olt = getattr(o, 'last_quote', None), getattr(o, 'last_trade', None)
            # 期权价格：中值保底
            op = (get_val(olq, 'p', 'bid') + get_val(olq, 'P', 'ask'))/2 or get_val(olt, 'p', 'price')
            
            if op <= 0: continue
            rows.append({
                "信号": "🔥新开仓" if (vol > oi and vol > 100) else "-",
                "合约": o.details.ticker,
                "行权价": o.details.strike_price,
                "实时价": round(op, 3),
                "Δ Delta": round(get_val(g, 'delta'), 3),
                "Γ Gamma": round(get_val(g, 'gamma'), 4),
                "成交量": vol,
                "持仓量": oi
            })
        
        df = pd.DataFrame(rows).sort_values(by="成交量", ascending=False) if rows else pd.DataFrame()
        return {"ticker": tk, "price": curr_p, "df": df, "status": "OK"}
    except Exception as e:
        return {"ticker": ticker, "status": str(e), "price": 0.0, "df": pd.DataFrame()}

# --- 🧠 演化执行逻辑 (原子化 Prompt，防 ValueError) ---
def execute_evolution(d, slot, clients):
    with slot:
        targets = d.get('portfolio') or ['GLD']
        st.write(f"📡 **正在同步虎眼数据流: {targets}**")
        
        # 1. 采集行情
        with ThreadPoolExecutor(max_workers=5) as exe:
            futures = [exe.submit(fetch_tiger_intel, tk, clients['poly']) for tk in targets]
            done, _ = wait(futures, timeout=15)
            results = [f.result() for f in done]
        
        # 🚨 红线 6: 透明展示行情数据
        ai_brief = {}
        for res in results:
            if res['price'] > 0:
                st.subheader(f"💎 {res['ticker']} 现价: ${res['price']:.2f}")
                if not res['df'].empty:
                    st.dataframe(res['df'].head(10), use_container_width=True)
                    ai_brief[res['ticker']] = {"price": res['price'], "options": res['df'].head(8).to_dict('records')}
                else:
                    st.warning(f"{res['ticker']} 未捕获到活跃期权。")
                    ai_brief[res['ticker']] = {"price": res['price'], "options": []}

        if not ai_brief:
            st.error("❌ 无法获取任何标的价格，演化中断。"); return

        # 2. 决策研判 (原子化 Prompt 规避 f-string 大括号坑)
        st.write("🧠 **中枢研判中...**")
        raw_template = """
        你是工蜂 [NAME]，特质: [STYLE]。
        现金: [BALANCE] | 持仓: [POSITIONS]
        情报: [INTEL]
        要求：基于希腊值分析并返回 JSON。
        格式：{"thought": "中文分析", "trades": [{"ticker":"代码", "qty":1, "action":"BUY/SELL"}]}
        """
        final_prompt = raw_template.replace("[NAME]", d['name'])\
                                   .replace("[STYLE]", d.get('style', '通用'))\
                                   .replace("[BALANCE]", str(d['balance']))\
                                   .replace("[POSITIONS]", json.dumps(d.get('positions')))\
                                   .replace("[INTEL]", json.dumps(ai_brief, ensure_ascii=False))
        
        try:
            r = clients['gen_client'].models.generate_content(model="gemini-2.0-flash", contents=final_prompt, config={'response_mime_type': 'application/json'})
            decision = json.loads(r.text)
            thought = decision.get('thought', '观望中...')
            st.success(f"💭 {d['name']} 研判:\n\n{thought}")
            
            # 3. 结算逻辑 (红线 4: 持久化更新面板)
            nb, np, logs = float(d.get('balance', 100000)), (d.get('positions', {}) or {}).copy(), []
            for t in decision.get('trades', []):
                sym, qty, act = t.get('ticker','').upper(), t.get('qty',0), t.get('action','')
                px = ai_brief.get(sym, {}).get('price', 0)
                if px <= 0: # 检索期权价
                    for info in ai_brief.values():
                        for o in info['options']:
                            if o['合约'] == sym: px = o['实时价']
                if px <= 0: continue
                cost = qty * px * (100 if len(sym) > 6 else 1)
                if act == 'BUY' and nb >= cost:
                    nb -= cost; np[sym] = np.get(sym, 0) + qty; logs.append(f"买入 {sym}")
                elif act == 'SELL' and np.get(sym, 0) >= qty:
                    nb += cost; np[sym] -= qty; logs.append(f"卖出 {sym}")
                    if np[sym] <= 0: del np[sym]

            act_str = " | ".join(logs) if logs else "维持观望"
            mv = sum(q * ai_brief.get(s, {'price': 0})['price'] for s, q in np.items() if len(s) < 10)
            
            clients['supabase'].table("drones").update({
                "balance": nb, "positions": np, "total_assets": round(nb + mv, 2),
                "logs": ([f"[{datetime.now().strftime('%H:%M:%S')}] {act_str} | {thought}"] + (d.get('logs') or []))[:10],
                "patrol_count": (d.get('patrol_count', 0) + 1)
            }).eq("id", d["id"]).execute()
            st.write(f"📝 **结果:** {act_str}")
        except Exception as e: st.error(f"决策失败: {e}")

# ==========================================
# 🚨 UI 渲染主入口 (红线 4 & 5: 面板与按钮持久化)
# ==========================================
cl_pkg, err = init_hive_engine()
if err: st.error(err); st.stop()
clients = cl_pkg

try: d_res = clients['supabase'].table("drones").select("*").order("created_at", desc=True).execute().data
except: d_res = []

h1, h2 = st.columns([4, 1])
with h1: st.caption(f"{VERSION} | 虎眼逻辑 1:1 同步 | 避坑红线加固")
full_fly = h2.button("🚀 集群全量放飞", type="primary", use_container_width=True)

if full_fly and d_res:
    for d in d_res:
        with st.status(f"🐝 正在调度 {d['name']}...", expanded=True):
            execute_evolution(d, st.container(), clients)
    st.success("✅ 集群演化任务已同步"); st.button("刷新界面")
    st.stop()

tabs = st.tabs(["🏆 工蜂档案", "👑 蜂后孵化", "⚙️ 系统管理"])

with tabs[0]:
    if not d_res: st.info("空。")
    for d in d_res:
        label = f"🐝 {d.get('name')} | ${d.get('total_assets',0):,.2f} | 巡逻: {d.get('patrol_count',0)}次"
        with st.expander(label):
            col1, col2 = st.columns(2)
            with col1:
                st.write(f"🧬 **特质基因:** {d.get('style', '通用')}")
                st.caption(f"🧠 {d.get('persona', '初始状态')}")
            with col2:
                st.write("**📦 持仓:**")
                st.json(d.get('positions', {}))
            if st.button(f"🚀 单独放飞", key=f"f_{d['id']}"):
                execute_evolution(d, st.container(), clients)
            for l in (d.get('logs') or [])[:3]: st.caption(l)

with tabs[1]:
    st.subheader("👑 蜂后孵化")
    trait = st.selectbox("注入核心特质:", list(STRATEGY_LIB.keys()))
    if st.button("🔥 孵化"):
        clients['supabase'].table("drones").insert({
            "name": f"工蜂-{random.randint(100,999)}", "style": trait,
            "balance": 100000.0, "total_assets": 100000.0, "patrol_count": 0,
            "portfolio": ["GLD"], "positions": {}, "logs": ["诞生于 v8.6"]
        }).execute(); st.rerun()

with tabs[2]:
    if st.button("🗑️ 清空蜂群"):
        clients['supabase'].table("drones").delete().neq("name", "RESERVED").execute()
        st.rerun()