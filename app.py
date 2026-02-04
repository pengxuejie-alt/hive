import streamlit as st
import re, json, time, os, random
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from supabase import create_client
from google import genai
from polygon import RESTClient

# --- 1. 核心初始化 (补全所有基础变量) ---
VERSION = "v5.7 (Fixed)"  # 💡 补全被漏掉的变量
st.set_page_config(page_title="Hive 金融蜂群", layout="wide")
st.title("🐝 Hive 智能金融蜂群")

def get_config(key): return os.environ.get(key) or st.secrets.get(key)

@st.cache_resource
def init_clients():
    try:
        return {
            "supabase": create_client(get_config("SUPABASE_URL"), get_config("SUPABASE_KEY")),
            "gen_client": genai.Client(api_key=get_config("GEMINI_KEY")),
            "poly_client": RESTClient(api_key=get_config("POLYGON_KEY"))
        }
    except: return None

clients = init_clients()
if not clients: st.error("❌ 环境配置读取失败，请检查 Secrets"); st.stop()

supabase = clients["supabase"]
gen_client = clients["gen_client"]
poly_client = clients["poly_client"]

# --- 2. 演化核心逻辑 (修正版：三步透明化) ---
def execute_worker_cycle(d, slot):
    with slot:
        try:
            # 第一步：情报
            st.write("🔍 **情报搜集：正在读取实时股价...**")
            targets = d.get('portfolio', ['GLD'])
            def fetch_px(t):
                try:
                    sn = poly_client.get_snapshot_ticker("stocks", t)
                    px = getattr(sn, 'price', 0) or getattr(sn.last_trade, 'p', 0)
                    return {"代码": t, "现价": px}
                except: return {"代码": t, "现价": 0}
            
            with ThreadPoolExecutor(max_workers=5) as exe:
                results = list(exe.map(fetch_px, targets))
            nectar_data = {r['代码']: r for r in results if r['现价'] > 0}
            st.info(f"📈 实时行情汇总：{json.dumps(nectar_data, ensure_ascii=False)}")

            # 第二步：研判
            st.write("🧠 **研判分析：中枢神经逻辑运算...**")
            prompt = f"你是金融工蜂{d['name']}。性格:{d['persona']}。现金:{d['balance']}。持仓:{json.dumps(d.get('positions'))}。行情:{json.dumps(nectar_data)}。请用中文返回JSON:{{'thought':'分析','trades':[],'learning':'经验'}}"
            r = gen_client.models.generate_content(model="gemini-2.0-flash", contents=prompt, config={'response_mime_type': 'application/json'})
            decision = json.loads(r.text)
            if isinstance(decision, list): decision = decision[0]
            st.success(f"💭 思考逻辑：{decision.get('thought')}")

            # 第三步：交易
            st.write("⚖️ **执行阶段：提交交易指令...**")
            nb, np, reports = float(d.get('balance', 100000)), (d.get('positions', {}) or {}).copy(), []
            for t in decision.get('trades', []):
                sym, qty = t.get('ticker', '').upper(), t.get('qty', 0)
                px = nectar_data.get(sym, {}).get('现价', 0)
                if px <= 0: continue
                cost = qty * px * (100 if len(sym) > 6 else 1)
                if t.get('action') == 'BUY' and nb >= cost:
                    nb -= cost; np[sym] = np.get(sym, 0) + qty
                    reports.append(f"买入 {sym}")
                elif t.get('action') == 'SELL' and np.get(sym, 0) >= qty:
                    nb += cost; np[sym] -= qty
                    if np[sym] <= 0: del np[sym]
                    reports.append(f"卖出 {sym}")

            act_sum = " | ".join(reports) if reports else "观望"
            log_msg = f"[{datetime.now().strftime('%H:%M:%S')}] 动作:{act_sum} | 思考:{decision.get('thought')}"
            mv = sum(q * nectar_data.get(s, {}).get('现价', 0) for s, q in np.items())
            
            supabase.table("drones").update({
                "balance": nb, "positions": np, "total_assets": round(nb + mv, 2),
                "logs": ([log_msg] + (d.get('logs') or []))[:10],
                "memory": decision.get('learning', d.get('memory')),
                "patrol_count": (d.get('patrol_count', 0) + 1)
            }).eq("id", d["id"]).execute()
            
            st.write(f"📝 **结果：{act_sum}**")
        except Exception as e: st.error(f"❌ 运行失败: {e}")

# --- 3. UI 渲染 ---
h1, h2 = st.columns([4, 1])
with h1: st.caption(f"{VERSION} | 纯净金融演化模式")
full_fly = h2.button("🔥 一键全量放飞", type="primary", use_container_width=True)

# 💡 安全获取数据
try:
    d_res = supabase.table("drones").select("*").order("created_at", desc=True).execute().data
except:
    d_res = []

if full_fly and d_res:
    for d in d_res:
        with st.status(f"🐝 正在放飞 {d['name']}...", expanded=True) as status:
            execute_worker_cycle(d, status)
    st.success("✅ 集群放飞完成")
    st.button("🔄 刷新查看状态")
    st.stop()

tabs = st.tabs(["🏆 工蜂档案", "👑 蜂后孵化", "⚙️ 系统管理"])

with tabs[0]:
    if not d_res: st.info("当前蜂巢为空。")
    for d in d_res:
        with st.expander(f"🐝 {d.get('name')} | 资产: ${d.get('total_assets',0):,.2f} | 巡逻: {d.get('patrol_count',0)}次"):
            c_l, c_r = st.columns(2)
            with c_l:
                st.write(f"🧬 **基因:** {d.get('persona')}")
                st.write(f"🧠 **记忆:** {d.get('memory')}")
            with c_r:
                st.write("**📦 持仓:**"); st.json(d.get('positions', {}))
            
            slot = st.container()
            if st.button(f"🚀 单独放飞", key=f"s_{d['id']}"):
                execute_worker_cycle(d, slot)
            for l in (d.get('logs') or [])[:3]: st.caption(l)

with tabs[1]:
    st.subheader("👑 蜂后孵化")
    instr = st.text_area("孵化指令:", value="孵化3只量化交易员")
    if st.button("🔥 执行"):
        count = 1
        m = re.search(r'(\d+)只', instr)
        if m: count = int(m.group(1))
        def spawn(idx):
            p = f"设计JSON：{{'name':'','persona':'','portfolio':['GLD']}}。指令：{instr}"
            res = gen_client.models.generate_content(model="gemini-2.0-flash", contents=p, config={'response_mime_type': 'application/json'})
            item = json.loads(res.text)
            if isinstance(item, list): item = item[0]
            supabase.table("drones").insert({
                "name": f"{item.get('name', '工蜂')}-{random.randint(100,999)}",
                "persona": item.get('persona', '初始'),
                "balance": 100000.0, "total_assets": 100000.0, "initial_balance": 100000.0,
                "patrol_count": 0, "positions": {}, "logs": ["诞生"],
                "created_at": datetime.now(timezone.utc).isoformat()
            }).execute()
        with ThreadPoolExecutor(max_workers=count) as exe:
            list(exe.map(spawn, range(count)))
        st.success("已完成"); time.sleep(1); st.rerun()

with tabs[2]:
    st.subheader("⚙️ 系统管理")
    if st.button("🗑️ 彻底清空数据", type="secondary"):
        supabase.table("drones").delete().neq("name", "RESERVED").execute()
        st.rerun()