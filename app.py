import streamlit as st
import re, json, time, os, random, pytz
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from supabase import create_client
import google.generativeai as genai
from polygon import RESTClient

# --- 1. 初始化与 UI 配置 (架构加固) ---
st.set_page_config(page_title="Hive 虎之眼系统", layout="wide")
VERSION = "v6.3 (Tiger-Eye Hive)"

def get_config(key):
    try: return os.environ.get(key) or st.secrets.get(key)
    except: return None

# 💡 100% 同步附件的 get_val 逻辑
def get_val(obj, *keys):
    if not obj: return 0.0
    for k in keys:
        v = getattr(obj, k, None)
        if v is not None: return float(v)
    return 0.0

@st.cache_resource
def init_clients():
    try:
        pk, gk = get_config("POLYGON_KEY"), get_config("GEMINI_KEY")
        su, sk = get_config("SUPABASE_URL"), get_config("SUPABASE_KEY")
        if not all([pk, gk, su, sk]): return None, "⚠️ 配置缺失，请检查 Secrets"
        return {
            "supabase": create_client(su, sk),
            "poly": RESTClient(api_key=pk),
            "ai_model": genai.GenerativeModel("gemini-2.0-flash")
        }, None
    except Exception as e: return None, str(e)

# --- 2. 虎眼级行情穿透引擎 ---
def fetch_data_tiger_eye(ticker, poly_client):
    try:
        tk = ticker.upper()
        # 1. 抓取快照与昨日收盘 (同步附件策略)
        snap = poly_client.get_snapshot_ticker("stocks", tk)
        prev = poly_client.get_previous_close_agg(tk)
        y_close = get_val(prev[0] if prev else None, 'close')
        
        lt, lq = getattr(snap, 'last_trade', None), getattr(snap, 'last_quote', None)
        
        # 2. 三级穿透取价
        tp = get_val(lt, 'p', 'price') # 最后成交价
        bp = get_val(lq, 'p', 'bid')   # 买价
        ap = get_val(lq, 'P', 'ask')   # 卖价
        mid_p = (bp + ap) / 2 if (bp > 0 and ap > 0) else 0
        
        # 优先级：成交 > 买卖中值 > 昨日收盘
        final_p = tp if tp > 0 else (mid_p if mid_p > 0 else y_close)
        
        return {
            "代码": tk, 
            "现价": final_p, 
            "来源": "Trade" if tp > 0 else ("Quote" if mid_p > 0 else "Prev"),
            "涨跌幅": get_val(snap, 'todays_change_percent')
        }
    except:
        return {"代码": ticker, "现价": 0.0, "来源": "Error"}

# --- 3. 演化核心 (修复空列表 Bug) ---
def execute_worker_cycle(d, slot, clients):
    supabase, ai_model, poly_client = clients["supabase"], clients["ai_model"], clients["poly"]
    
    with slot:
        try:
            # 💡 修复：确保 portfolio 不为空
            targets = d.get('portfolio') or ['GLD'] 
            st.write(f"📡 **正在穿透分析标的: {', '.join(targets)}**")
            
            with ThreadPoolExecutor(max_workers=5) as exe:
                results = list(exe.map(lambda t: fetch_data_tiger_eye(t, poly_client), targets))
            
            nectar_data = {r['代码']: r for r in results if r['现价'] > 0}
            st.table(results)

            if not nectar_data:
                st.error("❌ 穿透失败：所有标的价格层级均返回 0。请检查代码或 API 权限。")
                return

            st.write("🧠 **虎眼研判中...**")
            prompt = f"""分析标的 {targets}。
            当前资产: 现金 ${d['balance']}, 持仓 {json.dumps(d.get('positions'))}
            实时情报: {json.dumps(nectar_data, ensure_ascii=False)}
            要求：请用专业中文给出策略，并返回以下JSON格式：
            {{ "thought": "专业行情分析", "trades": [{"ticker":"GLD","qty":10,"action":"BUY"}], "learning": "总结" }}
            """
            response = ai_model.generate_content(prompt)
            # 处理可能的 JSON 块包裹
            clean_json = re.search(r'\{.*\}', response.text, re.DOTALL).group()
            decision = json.loads(clean_json)

            st.success(f"💭 思考逻辑: {decision.get('thought')}")

            # 交易结算与日志 (patrol_count)
            nb, np = float(d.get('balance', 0)), (d.get('positions', {}) or {}).copy()
            trades_done = []
            for t in decision.get('trades', []):
                sym = t.get('ticker', '').upper()
                px = nectar_data.get(sym, {}).get('现价', 0)
                if px <= 0: continue
                cost = t.get('qty', 0) * px * (100 if len(sym) > 6 else 1)
                if t['action'] == 'BUY' and nb >= cost:
                    nb -= cost; np[sym] = np.get(sym, 0) + t['qty']; trades_done.append(f"买入 {sym}@{px}")
                elif t['action'] == 'SELL' and np.get(sym, 0) >= t['qty']:
                    nb += cost; np[sym] -= t['qty']; trades_done.append(f"卖出 {sym}@{px}")
                    if np[sym] <= 0: del np[sym]

            # 计算总资产
            mv = sum(q * nectar_data.get(s, {}).get('现价', 0) for s, q in np.items())
            report = " | ".join(trades_done) if trades_done else "观望"
            
            supabase.table("drones").update({
                "balance": nb, "positions": np, "total_assets": round(nb + mv, 2),
                "logs": ([f"[{datetime.now().strftime('%H:%M:%S')}] {report} | {decision.get('thought')}"] + (d.get('logs') or []))[:10],
                "patrol_count": (d.get('patrol_count', 0) + 1)
            }).eq("id", d["id"]).execute()
            
            st.write(f"📝 **最终决策: {report}**")
        except Exception as e: st.error(f"❌ 执行异常: {e}")

# --- 4. 界面逻辑 ---
def main():
    st.title("🐅 虎之眼金融蜂群系统")
    clients, err = init_clients()
    if err: st.error(err); st.stop()

    h1, h2 = st.columns([4, 1])
    with h1: st.caption(f"{VERSION} | 穿透引擎就绪 | 数据库已连接")
    full_fly = h2.button("🚀 一键全量放飞", type="primary", use_container_width=True)

    try:
        d_res = clients["supabase"].table("drones").select("*").order("created_at", desc=True).execute().data
    except: d_res = []

    if full_fly and d_res:
        for d in d_res:
            with st.status(f"🐝 正在调度 {d['name']}...", expanded=True) as s:
                execute_worker_cycle(d, s, clients)
        st.success("✅ 集群演化完成"); st.button("刷新"); st.stop()

    tabs = st.tabs(["🏆 工蜂档案", "👑 蜂后孵化", "⚙️ 系统管理"])
    with tabs[0]:
        if not d_res: st.info("空。")
        for d in d_res:
            with st.expander(f"🐝 {d.get('name')} | 资产: ${d.get('total_assets',0):,.2f} | 巡逻: {d.get('patrol_count',0)}次"):
                c1, c2 = st.columns(2)
                with c1: st.write(f"🧬 **基因:** {d.get('persona')}")
                with c2: st.write("**📦 持仓:**"); st.json(d.get('positions', {}))
                if st.button(f"🚀 单独放飞", key=f"run_{d['id']}"):
                    execute_worker_cycle(d, st.container(), clients)
                for l in (d.get('logs') or [])[:3]: st.caption(l)
    # (其余孵化与清空逻辑保持不变)
    with tabs[2]:
        if st.button("🗑️ 清空所有数据"):
            clients["supabase"].table("drones").delete().neq("name", "RESERVED").execute(); st.rerun()

if __name__ == "__main__":
    main()