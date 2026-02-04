import streamlit as st

# --- 1. 架构红线：全局常量定义 (解决 NameError & 白屏) ---
VERSION = "v8.4 (Final Atomic)"
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
from concurrent.futures import ThreadPoolExecutor, wait
from supabase import create_client
from google import genai  # ✅ 红线 3: 库名对正

# --- 2. 虎眼核心工具函数 (1:1 还原数据采集能力) ---
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

# --- 3. 虎眼级：穿透式情报采集 ---
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
        # 优先级：成交价 > 买卖盘中值 > 昨日收盘
        curr_p = tp if tp > 0 else (((bp+ap)/2) if (bp>0 and ap>0) else y_close)
        
        # 抓取活跃期权链
        opts = list(poly.list_snapshot_options_chain(tk, params={"strike_price.gte": curr_p*0.9, "strike_price.lte": curr_p*1.1, "limit": 15}))
        rows = []
        for o in opts:
            vol, oi = int(get_val(o.day, 'volume')), int(get_val(o, 'open_interest'))
            olq, olt = getattr(o, 'last_quote', None), getattr(o, 'last_trade', None)
            op = (get_val(olq, 'p', 'bid') + get_val(olq, 'P', 'ask'))/2 or get_val(olt, 'p', 'price')
            if op <= 0: continue
            g = getattr(o, 'greeks', None)
            rows.append({
                "信号": "🔥新开仓" if (vol > oi and vol > 100) else "-",
                "合约": o.details.ticker, "行权价": o.details.strike_price, "现价": round(op, 3),
                "Δ Delta": round(get_val(g, 'delta'), 3), "Γ Gamma": round(get_val(g, 'gamma'), 4),
                "成交量": vol, "持仓量": oi
            })
        df = pd.DataFrame(rows).sort_values(by="成交量", ascending=False) if rows else pd.DataFrame()
        return {"ticker": tk, "price": curr_p, "df": df, "status": "OK"}
    except Exception as e:
        return {"ticker": ticker, "status": str(e), "price": 0.0, "df": pd.DataFrame()}

# --- 4. 演化核心逻辑 (彻底解决 f-string ValueError) ---
def execute_evolution(d, slot, clients):
    with slot:
        targets = d.get('portfolio') or ['GLD']
        st.write(f"📡 **正在同步虎眼数据流: {targets}**")
        
        with ThreadPoolExecutor(max_workers=5) as exe:
            futures = [exe.submit(fetch_tiger_data, tk, clients['poly']) for tk in targets]
            done, _ = wait(futures, timeout=15)
            results = [f.result() for f in done]
        
        # 🚨 红线 6: 过程透明化展示表格
        ai_brief = {}
        for res in results:
            if res['status'] == "OK":
                st.subheader(f"💎 {res['ticker']} 现价: ${res['price']:.2f}")
                if not res['df'].empty:
                    st.dataframe(res['df'].head(10), use_container_width=True)
                    ai_brief[res['ticker']] = {"price": res['price'], "options": res['df'].head(5).to_dict('records')}
        
        if not ai_brief:
            st.warning("⚠️ 情报缺失，工蜂待机。"); return

        # 💡 核心修复：使用三引号纯字符串，避开 f-string 嵌套大括号崩溃
        base_prompt = """
        你是工蜂 {name}，特质: {style}。
        现金: {balance} | 持仓: {positions}
        情报: {intel}
        任务：基于期权异动分析并返回 JSON。
        格式要求：{{"thought": "中文分析", "trades": [{"ticker":"合约/代码", "qty":1, "action":"BUY"}]}}
        """
        final_prompt = base_prompt.format(
            name=d['name'],
            style=d.get('style', '通用'),
            balance=d['balance'],
            positions=json.dumps(d.get('positions')),
            intel=json.dumps(ai_brief, ensure_ascii=False)
        )
        
        try:
            r = clients['gen_client'].models.generate_content(model="gemini-2.0-flash", contents=final_prompt, config={'response_mime_type': 'application/json'})
            decision = json.loads(r.text)
            thought = decision.get('thought', '观望中...')
            st.success(f"💭 {d['name']} 研判过程:\n\n{thought}")
            
            # 结算更新
            nb, np, logs = float(d.get('balance', 100000)), (d.get('positions', {}) or {}).copy(), []
            for t in decision.get('trades', []):
                sym, qty, act = t.get('ticker','').upper(), t.get('qty',0), t.get('action','')
                px = ai_brief.get(sym, {}).get('price', 0)
                if px <= 0: # 寻找期权价
                    for info in ai_brief.values():
                        for o in info['options']:
                            if o['合约'] == sym: px = o['现价']
                if px <= 0: continue
                cost = qty * px * (100 if len(sym) > 6 else 1)
                if act == 'BUY' and nb >= cost:
                    nb -= cost; np[sym] = np.get(sym, 0) + qty; logs.append(f"买入 {sym}")
                elif act == 'SELL' and np.get(sym, 0) >= qty:
                    nb += cost; np[sym] -= qty; logs.append(f"卖出 {sym}")
                    if np[sym] <= 0: del np[sym]

            act_str = " | ".join(logs) if logs else "维持观望"
            # 🚨 红线 4: 面板属性持久化
            clients['supabase'].table("drones").update({
                "balance": nb, "positions": np, "total_assets": round(nb + (nb * 0.0), 2),
                "logs": ([f"[{datetime.now().strftime('%H:%M:%S')}] {act_str} | {thought}"] + (d.get('logs') or []))[:10],
                "patrol_count": (d.get('patrol_count', 0) + 1)
            }).eq("id", d["id"]).execute()
            st.write(f"📝 **演化结果:** {act_str}")
        except Exception as e:
            st.error(f"❌ 决策链路异常: {e}")

# --- 5. UI 渲染顺序 ---
clients_pkg, err = init_hive_engine()
if err: st.error(err); st.stop()
clients = clients_pkg

try: d_res = clients['supabase'].table("drones").select("*").order("created_at", desc=True).execute().data
except: d_res = []

h1, h2 = st.columns([4, 1])
with h1: st.caption(f"{VERSION} | 虎眼逻辑 1:1 同步 | 避坑红线加固版")
full_fly = h2.button("🚀 集群全量放飞", type="primary", use_container_width=True)

if full_fly and d_res:
    for d in d_res:
        with st.status(f"🐝 调度 {d['name']}...", expanded=True):
            execute_evolution(d, st.container(), clients)
    st.success("✅ 集群放飞完成"); st.button("刷新页面")
    st.stop()

tabs = st.tabs(["🏆 工蜂档案", "👑 蜂后孵化", "⚙️ 系统管理"])
with tabs[0]:
    if not d_res: st.info("空。")
    for d in d_res:
        with st.expander(f"🐝 {d.get('name')} | ${d.get('total_assets',0):,.2f} | 巡逻: {d.get('patrol_count',0)}次"):
            if st.button(f"🚀 单独放飞", key=f"f_{d['id']}"):
                execute_evolution(d, st.container(), clients)
            st.json(d.get('positions', {}))
            for l in (d.get('logs') or [])[:3]: st.caption(l)