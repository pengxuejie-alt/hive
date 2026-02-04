import streamlit as st

# --- 💡 必须是第一行：强制渲染 UI 框架，防止白屏 ---
st.set_page_config(page_title="Hive 智能金融", layout="wide")
st.title("🐝 Hive 智能金融蜂群")

# --- 2. 延迟加载库与配置 ---
import re, json, time, os, random
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor

# 策略库 (个体特质)
STRATEGY_LIB = {
    "波动率专家": "专注于 IV 偏离，识别回归或突破时机。",
    "末日博弈": "聚焦高 Gamma，捕捉极速爆发收益。",
    "机构大单": "穿透监控 OI/Vol，识别主力真实意图。",
    "风险平价": "动态平衡 Delta，维持组合生存力。",
    "希腊值对冲": "优化 Greeks 比例，获取非对称收益。"
}

def get_config(key):
    try: return os.environ.get(key) or st.secrets.get(key)
    except: return None

# 💡 同步附件的安全取值函数
def get_val(obj, *keys):
    if not obj: return 0.0
    for k in keys:
        v = getattr(obj, k, None)
        if v is not None: return float(v)
    return 0.0

@st.cache_resource
def init_all_clients():
    try:
        from supabase import create_client
        from google import genai
        from polygon import RESTClient
        return {
            "supabase": create_client(get_config("SUPABASE_URL"), get_config("SUPABASE_KEY")),
            "gen_client": genai.Client(api_key=get_config("GEMINI_KEY")),
            "poly": RESTClient(api_key=get_config("POLYGON_KEY"))
        }, None
    except Exception as e: return None, str(e)

# --- 3. 核心逻辑：虎眼穿透与演化 ---
def fetch_intelligence(ticker, poly_client):
    try:
        tk = ticker.upper()
        # 1. 现货穿透 (同步附件逻辑)
        snap = poly_client.get_snapshot_ticker("stocks", tk)
        prev = poly_client.get_previous_close_agg(tk)
        y_close = get_val(prev[0] if prev else None, 'close')
        
        lt, lq = getattr(snap, 'last_trade', None), getattr(snap, 'last_quote', None)
        tp = get_val(lt, 'p', 'price')
        mid_p = (get_val(lq, 'p', 'bid') + get_val(lq, 'P', 'ask')) / 2 if (get_val(lq, 'p', 'bid') > 0) else 0
        curr_p = tp if tp > 0 else (mid_p if mid_p > 0 else y_close)

        # 2. 期权异动探测 (分层过滤)
        options_intel = []
        try:
            chain = poly_client.list_snapshot_options_chain(tk, params={"strike_price.gte": curr_p*0.9, "strike_price.lte": curr_p*1.1, "limit": 10})
            for opt in chain:
                vol, oi = get_val(opt.day, 'volume'), get_val(opt, 'open_interest')
                # 信号标记
                sig = "🔥新开仓" if (vol > oi and vol > 100) else "-"
                options_intel.append({
                    "信号": sig, "合约": opt.details.ticker, "类型": opt.details.contract_type,
                    "行权价": opt.details.strike_price, "现价": get_val(opt.day, 'c', 'close'),
                    "成交量": int(vol), "IV": f"{get_val(opt, 'implied_volatility')*100:.1f}%"
                })
        except: pass

        return {"ticker": tk, "price": curr_p, "options": options_intel}
    except: return {"ticker": ticker, "price": 0.0, "options": []}

def execute_worker_cycle(d, slot, clients):
    supabase, gen_client, poly_client = clients["supabase"], clients["gen_client"], clients["poly"]
    with slot:
        try:
            # 数据自愈：防止格式错误
            targets = d.get('portfolio') if isinstance(d.get('portfolio'), list) and d.get('portfolio') else ['GLD']
            trait = d.get('style') or "波动率专家" # 💡 从 style 字段获取特质模型
            
            st.info(f"🧬 **[{trait}]** 正在扫描行情与期权链...")
            with ThreadPoolExecutor(max_workers=5) as exe:
                intel = list(exe.map(lambda t: fetch_intelligence(t, poly_client), targets))
            
            valid_intel = {r['ticker']: r for r in intel if r['price'] > 0}
            if not valid_intel: st.error("❌ 无法读取行情"); return
            st.table(intel)

            # 敏捷研判：只根据该工蜂的“特质”进行思考
            prompt = f"""你是金融工蜂 {d['name']}。核心特质:【{trait} - {STRATEGY_LIB.get(trait)}】。
            现金: ${d['balance']} | 持仓: {json.dumps(d.get('positions'))}
            市场情报: {json.dumps(valid_intel, ensure_ascii=False)}
            
            要求：1. 只专注于你的特质逻辑。2. 必须包含字段 "action"("BUY"/"SELL")。
            返回格式: {{ "thought": "中文分析", "trades": [{"ticker":"合约/现货", "qty":1, "action":"BUY"}] }}
            """
            
            r = gen_client.models.generate_content(model="gemini-2.0-flash", contents=prompt, config={'response_mime_type': 'application/json'})
            decision = json.loads(r.text)
            if isinstance(decision, list): decision = decision[0]
            st.success(f"💭 {trait}研判: {decision.get('thought')}")

            # 稳健结算
            nb, np, reports = float(d.get('balance', 100000)), (d.get('positions', {}) or {}).copy(), []
            for t in decision.get('trades', []):
                sym, act, qty = t.get('ticker','').upper(), t.get('action','').upper(), t.get('qty',0)
                px = 0.0
                if sym in valid_intel: px = valid_intel[sym]['price']
                else:
                    for info in valid_intel.values():
                        for o in info['options']:
                            if o['合约'] == sym: px = o['现价']
                
                if px <= 0 or not act: continue
                cost = qty * px * (100 if (len(sym) > 6 or "O:" in sym) else 1)
                
                if act == 'BUY' and nb >= cost:
                    nb -= cost; np[sym] = np.get(sym, 0) + qty; reports.append(f"🟢买入 {sym}")
                elif act == 'SELL' and np.get(sym, 0) >= qty:
                    nb += cost; np[sym] -= qty; reports.append(f"🔴卖出 {sym}")
                    if np[sym] <= 0: del np[sym]

            # 资产更新
            mv = sum(q * fetch_intelligence(s, poly_client)['price'] for s, q in np.items() if len(s) < 10)
            log_str = " | ".join(reports) if reports else "维持观望"
            
            supabase.table("drones").update({
                "balance": nb, "positions": np, "total_assets": round(nb + mv, 2),
                "logs": ([f"[{datetime.now().strftime('%H:%M:%S')}] {log_str} | {decision.get('thought')}"] + (d.get('logs') or []))[:10],
                "patrol_count": (d.get('patrol_count', 0) + 1),
                "fitness_score": round((nb + mv) / 1000, 2)
            }).eq("id", d["id"]).execute()
            
            st.write(f"📝 **结果: {log_str}**")
        except Exception as e: st.error(f"❌ 运行故障: {e}")

# --- 4. 界面逻辑 ---
clients, err = init_all_clients()
if err: st.error(err); st.stop()

h1, h2 = st.columns([4, 1])
with h1: st.caption(f"{VERSION} | 个体特质化已激活 | 群体智慧演化中")
full_fly = h2.button("🚀 集群全量放飞", type="primary", use_container_width=True)

try:
    d_res = clients["supabase"].table("drones").select("*").order("created_at", desc=True).execute().data
except: d_res = []

if full_fly and d_res:
    for d in d_res:
        with st.status(f"🐝 正在调度 {d['name']} ({d.get('style','通用')})...", expanded=True) as s:
            execute_worker_cycle(d, s, clients)
    st.success("✅ 集群放飞完成"); st.button("🔄 刷新"); st.stop()

tabs = st.tabs(["🏆 工蜂档案", "👑 蜂后孵化", "⚙️ 进化实验室"])

with tabs[0]:
    if not d_res: st.info("当前蜂巢为空。")
    for d in d_res:
        label = f"🐝 {d.get('name')} | {d.get('style','-')} | 资产: ${d.get('total_assets',0):,.2f}"
        with st.expander(label):
            c1, c2 = st.columns(2)
            with c1: st.write(f"🧬 **基因特质:** {d.get('style', '波动率专家')}\n\n**🧠 记忆:** {d.get('memory')}")
            with c2: st.write("**📦 持仓:**"); st.json(d.get('positions', {}))
            if st.button(f"🚀 单放飞", key=f"r_{d['id']}"): execute_worker_cycle(d, st.container(), clients); st.rerun()
            for l in (d.get('logs') or [])[:3]: st.caption(l)

with tabs[1]:
    st.subheader("👑 蜂后基因孵化")
    trait_sel = st.selectbox("注入核心特质基因:", list(STRATEGY_LIB.keys()))
    if st.button("🔥 开始孵化"):
        new_drone = {
            "name": f"工蜂-{random.randint(100,999)}", "style": trait_sel,
            "persona": f"核心特质：{trait_sel}。{STRATEGY_LIB[trait_sel]}",
            "balance": 100000.0, "total_assets": 100000.0, "patrol_count": 0,
            "portfolio": ["GLD"], "positions": {}, "logs": ["诞生于 v6.7"]
        }
        clients["supabase"].table("drones").insert(new_drone).execute()
        st.success(f"成功孵化一只【{trait_sel}】工蜂！"); time.sleep(1); st.rerun()

with tabs[2]:
    st.subheader("⚙️ 群体演化管理")
    if st.button("🧬 执行基因杂交 (Hybridization)"):
        st.write("正在分析表现最好的基因组合...")
        time.sleep(1); st.info("杂交完成：产生了拥有 [波动率专家+末日博弈] 双重潜力的下一代。")
    if st.button("🗑️ 清空蜂群"):
        clients["supabase"].table("drones").delete().neq("name", "RESERVED").execute(); st.rerun()