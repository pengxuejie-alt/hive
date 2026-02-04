import streamlit as st
import re, json, time, os, random, pytz
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from supabase import create_client
from google import genai
from polygon import RESTClient

# --- 1. 架构加固：顶层配置 (必须在任何逻辑之前) ---
st.set_page_config(page_title="Hive 智能金融", layout="wide")
VERSION = "v6.2 (Tiger-Eye Fixed)"

def get_config(key):
    try:
        return os.environ.get(key) or st.secrets.get(key)
    except:
        return None

# 💡 参考附件：安全数值提取
def get_val(obj, *keys):
    if not obj: return 0.0
    for k in keys:
        v = getattr(obj, k, None)
        if v is not None: return float(v)
    return 0.0

@st.cache_resource
def init_all_clients():
    try:
        p_key = get_config("POLYGON_KEY")
        g_key = get_config("GEMINI_KEY")
        s_url = get_config("SUPABASE_URL")
        s_key = get_config("SUPABASE_KEY")
        
        if not all([p_key, g_key, s_url, s_key]):
            return None, "⚠️ 配置缺失：请检查 Streamlit Secrets 环境设置。"
            
        return {
            "supabase": create_client(s_url, s_key),
            "gen_client": genai.Client(api_key=g_key),
            "poly_client": RESTClient(api_key=p_key)
        }, None
    except Exception as e:
        return None, f"❌ 初始化故障: {str(e)}"

# --- 2. 虎眼穿透逻辑 (同步附件逻辑) ---
def fetch_tiger_eye_data(ticker, poly_client):
    try:
        tk = ticker.upper()
        # 1. 获取 Snapshot
        snap = poly_client.get_snapshot_ticker("stocks", tk)
        # 2. 获取昨日收盘作为兜底
        prev = poly_client.get_previous_close_agg(tk)
        y_close = get_val(prev[0] if prev else None, 'close')
        
        lt = getattr(snap, 'last_trade', None)
        lq = getattr(snap, 'last_quote', None)
        
        # 提取成交价 p, 买价 bid, 卖价 ask
        tp = get_val(lt, 'p', 'price') 
        bp = get_val(lq, 'p', 'bid')
        ap = get_val(lq, 'P', 'ask')
        mid_p = (bp + ap) / 2 if (bp > 0 and ap > 0) else 0
        
        # 穿透优先级：成交价 > 买卖中值 > 昨日收盘
        final_p = tp if tp > 0 else (mid_p if mid_p > 0 else y_close)
        
        return {
            "代码": tk, 
            "现价": final_p, 
            "来源": "Trade" if tp > 0 else ("Quote" if mid_p > 0 else "Prev")
        }
    except Exception as e:
        return {"代码": tk, "现价": 0.0, "error": str(e)}

# --- 3. 演化核心 ---
def execute_worker_cycle(d, slot, clients):
    supabase = clients["supabase"]
    gen_client = clients["gen_client"]
    poly_client = clients["poly_client"]
    
    with slot:
        try:
            st.write("📡 **正在启动穿透行情搜集...**")
            targets = d.get('portfolio', ['GLD'])
            with ThreadPoolExecutor(max_workers=5) as exe:
                results = list(exe.map(lambda t: fetch_tiger_eye_data(t, poly_client), targets))
            
            nectar_data = {r['代码']: {"现价": r['现价']} for r in results if r['现价'] > 0}
            st.table(results)

            if not nectar_data:
                st.error("❌ 穿透失败：无法获取任何行情。")
                return

            st.write("🧠 **中枢研判分析中...**")
            prompt = f"你是金融工蜂{d['name']}。现金:{d['balance']}。行情:{json.dumps(nectar_data)}。请用中文返回决策JSON:{{'thought':'分析','trades':[]}}"
            r = gen_client.models.generate_content(model="gemini-2.0-flash", contents=prompt, config={'response_mime_type': 'application/json'})
            decision = json.loads(r.text)
            if isinstance(decision, list): decision = decision[0]
            st.success(f"💭 思考: {decision.get('thought')}")

            # 交易结算
            nb, np, reports = float(d.get('balance', 100000)), (d.get('positions', {}) or {}).copy(), []
            for t in decision.get('trades', []):
                sym = t.get('ticker', '').upper()
                px = nectar_data.get(sym, {}).get('现价', 0)
                if px <= 0: continue
                qty = t.get('qty', 0)
                cost = qty * px * (100 if len(sym) > 6 else 1)
                
                if t.get('action') == 'BUY' and nb >= cost:
                    nb -= cost; np[sym] = np.get(sym, 0) + qty
                    reports.append(f"买入 {sym}@{px}")
                elif t.get('action') == 'SELL' and np.get(sym, 0) >= qty:
                    nb += cost; np[sym] -= qty
                    if np[sym] <= 0: del np[sym]
                    reports.append(f"卖出 {sym}@{px}")

            act_str = " | ".join(reports) if reports else "观望"
            mv = sum(q * nectar_data.get(s, {}).get('现价', 0) for s, q in np.items())
            
            supabase.table("drones").update({
                "balance": nb, "positions": np, "total_assets": round(nb + mv, 2),
                "logs": ([f"[{datetime.now().strftime('%H:%M:%S')}] {act_str} | {decision.get('thought')}"] + (d.get('logs') or []))[:10],
                "patrol_count": (d.get('patrol_count', 0) + 1)
            }).eq("id", d["id"]).execute()
            st.write(f"📝 **结果: {act_str}**")
        except Exception as e:
            st.error(f"❌ 流程中断: {e}")

# --- 4. 界面渲染逻辑 ---
def main():
    st.title("🐝 Hive 智能金融蜂群")
    
    # 💡 优先尝试初始化，即使失败也继续渲染标题
    clients, err = init_all_clients()
    
    if err:
        st.error(err)
        st.info("💡 如果首页能显示但报此错，请检查 Streamlit Secrets。")
        st.stop()

    h1, h2 = st.columns([4, 1])
    with h1: st.caption(f"{VERSION} | 架构自检通过 | 穿透引擎已就绪")
    full_fly = h2.button("🔥 一键全量放飞", type="primary", use_container_width=True)

    try:
        d_res = clients["supabase"].table("drones").select("*").order("created_at", desc=True).execute().data
    except:
        d_res = []

    if full_fly and d_res:
        for d in d_res:
            with st.status(f"🐝 正在放飞 {d['name']}...", expanded=True) as s:
                execute_worker_cycle(d, s, clients)
        st.success("✅ 集群放飞完成")
        st.button("刷新页面")
        st.stop()

    tabs = st.tabs(["🏆 工蜂档案", "👑 蜂后孵化", "⚙️ 系统管理"])

    with tabs[0]:
        if not d_res: st.info("档案库空。")
        for d in d_res:
            label = f"🐝 {d.get('name')} | 资产: ${d.get('total_assets',0):,.2f} | 巡逻: {d.get('patrol_count',0)}"
            with st.expander(label):
                c1, c2 = st.columns(2)
                with c1:
                    st.write(f"🧬 **基因:** {d.get('persona')}")
                with c2:
                    st.write("**📦 持仓:**")
                    st.json(d.get('positions', {}))
                
                if st.button(f"🚀 单独放飞", key=f"btn_{d['id']}"):
                    execute_worker_cycle(d, st.container(), clients)
                for l in (d.get('logs') or [])[:3]: st.caption(l)

    with tabs[1]:
        st.subheader("👑 蜂后批量孵化")
        instr = st.text_area("指令:", value="孵化3只GLD量化员")
        if st.button("🔥 开始"):
            st.info("孵化中..."); time.sleep(1); st.rerun()

    with tabs[2]:
        if st.button("🗑️ 清空所有数据"):
            clients["supabase"].table("drones").delete().neq("name", "RESERVED").execute()
            st.rerun()

if __name__ == "__main__":
    main()