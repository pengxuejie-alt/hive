import streamlit as st
import re, json, time, os, random
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from supabase import create_client
from google import genai
from polygon import RESTClient

# --- 1. 基础配置与安全初始化 ---
VERSION = "v6.0 (Architecture Fixed)"
st.set_page_config(page_title="Hive 智能金融", layout="wide")

def get_config(key): return os.environ.get(key) or st.secrets.get(key)

@st.cache_resource
def init_all_clients():
    try:
        s_url = get_config("SUPABASE_URL")
        s_key = get_config("SUPABASE_KEY")
        g_key = get_config("GEMINI_KEY")
        p_key = get_config("POLYGON_KEY")
        if not all([s_url, s_key, g_key, p_key]): return None, "环境变量缺失"
        return {
            "supabase": create_client(s_url, s_key),
            "gen_client": genai.Client(api_key=g_key),
            "poly_client": RESTClient(api_key=p_key)
        }, None
    except Exception as e: return None, str(e)

# --- 2. 核心行情工具 (参数对齐版) ---
def fetch_nectar(ticker, poly_client):
    try:
        ticker = ticker.upper()
        sn = poly_client.get_snapshot_ticker("stocks", ticker)
        # 多层级取价逻辑
        day_px = getattr(sn.day, 'c', 0) if hasattr(sn, 'day') and sn.day else 0
        last_px = getattr(sn.last_trade, 'p', 0) if hasattr(sn, 'last_trade') and sn.last_trade else 0
        prev_px = getattr(sn.prev_day, 'c', 0) if hasattr(sn, 'prev_day') and sn.prev_day else 0
        
        final_px = day_px or last_px or prev_px
        return {"代码": ticker, "现价": final_px, "细节": f"D:{day_px}/L:{last_px}/P:{prev_px}"}
    except: return {"代码": ticker, "现价": 0, "细节": "读取失败"}

# --- 3. 演化执行函数 ---
def execute_worker_cycle(d, slot, supabase, gen_client, poly_client):
    with slot:
        try:
            st.markdown("### 📡 阶段一：情报穿透")
            targets = d.get('portfolio', ['GLD'])
            with ThreadPoolExecutor(max_workers=5) as exe:
                results = list(exe.map(lambda t: fetch_nectar(t, poly_client), targets))
            
            nectar_data = {r['代码']: {"现价": r['现价']} for r in results if r['现价'] > 0}
            st.table(results) # 透明显示行情详情

            if not nectar_data:
                st.error("❌ 未能获取有效行情，停止演化。")
                return

            st.markdown("### 🧠 阶段二：神经研判")
            prompt = f"你是工蜂{d['name']}。现金:{d['balance']}。持仓:{json.dumps(d.get('positions'))}。行情:{json.dumps(nectar_data)}。请用中文返回JSON:{{'thought':'分析','trades':[]}}"
            r = gen_client.models.generate_content(model="gemini-2.0-flash", contents=prompt, config={'response_mime_type': 'application/json'})
            decision = json.loads(r.text)
            if isinstance(decision, list): decision = decision[0]
            st.success(f"💭 思考: {decision.get('thought')}")

            st.markdown("### ⚖️ 阶段三：指令执行")
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

            res_str = " | ".join(reports) if reports else "维持观望"
            mv = sum(q * nectar_data.get(s, {}).get('现价', 0) for s, q in np.items())
            
            supabase.table("drones").update({
                "balance": nb, "positions": np, "total_assets": round(nb + mv, 2),
                "logs": ([f"[{datetime.now().strftime('%H:%M:%S')}] {res_str} | {decision.get('thought')}"] + (d.get('logs') or []))[:10],
                "patrol_count": (d.get('patrol_count', 0) + 1)
            }).eq("id", d["id"]).execute()
            st.write(f"📝 **最终动作: {res_str}**")
        except Exception as e: st.error(f"发生错误: {e}")

# --- 4. 界面主逻辑 ---
def main():
    st.title("🐝 Hive 智能金融蜂群")
    
    clients, err = init_all_clients()
    if err:
        st.error(f"配置错误: {err}")
        st.stop()
    
    supabase, gen_client, poly_client = clients["supabase"], clients["gen_client"], clients["poly_client"]

    h1, h2 = st.columns([4, 1])
    with h1: st.caption(f"{VERSION} | 架构自检通过")
    full_fly = h2.button("🔥 一键全量放飞", type="primary", use_container_width=True)

    try:
        d_res = supabase.table("drones").select("*").order("created_at", desc=True).execute().data
    except: d_res = []

    if full_fly and d_res:
        for d in d_res:
            with st.status(f"🐝 正在放飞 {d['name']}...", expanded=True) as s:
                execute_worker_cycle(d, s, supabase, gen_client, poly_client)
        st.success("✅ 集群任务完成")
        st.button("刷新页面")
        st.stop()

    tabs = st.tabs(["🏆 工蜂档案", "👑 蜂后孵化", "⚙️ 系统管理"])

    with tabs[0]:
        if not d_res: st.info("档案库为空，请先孵化。")
        for d in d_res:
            label = f"🐝 {d.get('name')} | 资产: ${d.get('total_assets',0):,.2f} | 巡逻: {d.get('patrol_count',0)}"
            with st.expander(label):
                col1, col2 = st.columns(2)
                with col1:
                    st.write(f"🧬 **基因:** {d.get('persona')}")
                    st.write(f"🧠 **记忆:** {d.get('memory')}")
                with col2:
                    st.write("**📦 持仓:**")
                    st.json(d.get('positions', {}))
                
                if st.button(f"🚀 单独放飞", key=f"run_{d['id']}"):
                    execute_worker_cycle(d, st.container(), supabase, gen_client, poly_client)
                for log in (d.get('logs') or [])[:3]: st.caption(log)

    with tabs[1]:
        st.subheader("👑 蜂后批量孵化")
        instr = st.text_area("指令 (如：孵化3只GLD交易员):", value="孵化3只GLD交易员")
        if st.button("🔥 执行孵化"):
            match = re.search(r'(\d+)只', instr)
            count = int(match.group(1)) if match else 1
            with st.spinner(f"正在孵化 {count} 只..."):
                for i in range(count):
                    p = f"设计JSON：{{'name':'','persona':'','portfolio':['GLD']}}。内容中文。指令：{instr}"
                    res = gen_client.models.generate_content(model="gemini-2.0-flash", contents=p, config={'response_mime_type': 'application/json'})
                    item = json.loads(res.text)
                    if isinstance(item, list): item = item[0]
                    supabase.table("drones").insert({
                        "name": f"{item.get('name', '工蜂')}-{random.randint(100,999)}",
                        "persona": item.get('persona', '初始基因'),
                        "balance": 100000.0, "total_assets": 100000.0, "initial_balance": 100000.0,
                        "patrol_count": 0, "positions": {}, "logs": ["诞生"],
                        "created_at": datetime.now(timezone.utc).isoformat()
                    }).execute()
            st.success("孵化成功"); time.sleep(1); st.rerun()

    with tabs[2]:
        if st.button("🗑️ 清空所有数据"):
            supabase.table("drones").delete().neq("name", "RESERVED").execute()
            st.rerun()

if __name__ == "__main__":
    main()