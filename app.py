import streamlit as st
import pandas as pd
from supabase import create_client
import json, time, os
from datetime import datetime, timezone
from google import genai
from polygon import RESTClient

# --- 1. 配置加载 (支持环境变量与 secrets) ---
def get_config(key):
    return os.environ.get(key) or st.secrets.get(key)

try:
    S_URL = get_config("SUPABASE_URL")
    S_KEY = get_config("SUPABASE_KEY")
    G_KEY = get_config("GEMINI_KEY")
    P_KEY = get_config("POLYGON_KEY")
    
    supabase = create_client(S_URL, S_KEY)
    gen_client = genai.Client(api_key=G_KEY)
    poly_client = RESTClient(api_key=P_KEY)
    MODEL_ID = "gemini-3-flash-preview"
except Exception as e:
    st.error(f"密钥配置异常: {e}")
    st.stop()

# --- 2. 增强型数据提取器 ---
def get_safe(obj, path, default=0):
    """深层属性提取，支持属性名别名兼容 (如 p 和 price)"""
    try:
        parts = path.split(".")
        for part in parts:
            if hasattr(obj, part):
                obj = getattr(obj, part)
            elif isinstance(obj, dict) and part in obj:
                obj = obj[part]
            else:
                return default
        return obj if obj is not None else default
    except:
        return default

def get_realtime_price_robust(ticker, is_option=False):
    """
    针对盘前优化的‘三级跳’找价逻辑：
    1. Snapshot 顶级价格 -> 2. Last Trade 成交价 -> 3. Day Close/Prev Day Close
    """
    try:
        prefix = "options" if is_option else "stocks"
        sn = poly_client.get_snapshot_ticker(prefix, ticker)
        
        # 优先级1: Snapshot 顶层直接提供的价格 (c 或 price)
        p = get_safe(sn, "price", get_safe(sn, "c", 0))
        
        # 优先级2: 最新一笔成交价 (last_trade.p)
        if p == 0:
            p = get_safe(sn, "last_trade.p", get_safe(sn, "last_trade.price", 0))
            
        # 优先级3: 今日开盘或昨日收盘价 (作为极端盘前保底)
        if p == 0:
            p = get_safe(sn, "day.c", get_safe(sn, "prev_day.c", 0))
            
        return float(p)
    except:
        return 0.0

# --- 3. 核心演化引擎 ---
def evolve_drone_with_status(d):
    """带进度反馈的工蜂演化流程"""
    with st.status(f"🐝 正在放飞 {d['name']}...", expanded=True) as status:
        try:
            # 步骤1: 采集行情
            status.write("📡 正在穿透 Polygon 嗅探盘前多维行情...")
            portfolio = d.get('portfolio', ['GLD'])
            m_data = {}
            for t in portfolio:
                if not t.isalpha() or len(t) > 5: continue
                base_price = get_realtime_price_robust(t)
                
                # 期权链采集
                opts = []
                try:
                    chain = poly_client.list_snapshot_options_chain(t, params={"limit": 25})
                    now = datetime.now()
                    for o in chain:
                        op = get_safe(o, "last_trade.p", get_safe(o, "day.c", 0))
                        if op > 0:
                            opts.append({
                                "ticker": o.ticker, 
                                "strike": o.details.strike_price,
                                "price": op, 
                                "vol": get_safe(o, "day.v", 0),
                                "days": (datetime.strptime(o.ticker[5:11], "%y%m%d") - now).days
                            })
                except: pass
                m_data[t] = {"price": base_price, "options": sorted(opts, key=lambda x: x['vol'], reverse=True)[:10]}

            # 步骤2: AI 决策
            status.write("🧠 正在咨询 Gemini 大脑生成演化方案...")
            prompt = f"你是工蜂{d['name']}。性格:{d['persona']}。逻辑:{d['logic']}。余额:{d['balance']}。持仓:{d.get('positions')}。记忆:{d.get('memory')}。行情:{json.dumps(m_data)}。返回JSON：{{'trades':[], 'thought':'', 'learning':''}}"
            r = gen_client.models.generate_content(model=MODEL_ID, contents=prompt, config={'response_mime_type': 'application/json'})
            cmd = json.loads(r.text)
            if isinstance(cmd, list): cmd = cmd[0]

            # 步骤3: 锁价交易
            status.write("⚖️ 正在校验成交价格与更新账本...")
            nb, np, reports = float(d['balance']), (d.get('positions', {}) or {}).copy(), []
            
            for t in cmd.get('trades', []):
                sym = t.get('symbol', t.get('ticker', ''))
                qty = t.get('qty', t.get('quantity', 0))
                if not sym or qty <= 0: continue
                
                # 交易瞬间再次锁价确保准确
                px = get_realtime_price_robust(sym, is_option=("O:" in sym))
                if px == 0: px = t.get('price', 0) # 实在没有则参考 AI 建议价
                
                cost = float(qty) * float(px) * (100 if "O:" in sym else 1)
                act = t.get('action', '').upper()
                
                if act == 'BUY' and nb >= cost:
                    nb -= cost
                    np[sym] = np.get(sym, 0) + qty
                    reports.append(f"🟢买入 {sym} @{px}")
                elif act == 'SELL' and np.get(sym, 0) >= qty:
                    nb += cost
                    np[sym] -= qty
                    if np[sym] <= 0: del np[sym]
                    reports.append(f"🔴卖出 {sym} @{px}")

            # 步骤4: 资产评估与数据库同步
            status.write("💾 正在将演化结果写入蜂巢数据库...")
            mv = 0.0
            for s, q in np.items():
                mv += q * get_realtime_price_robust(s, is_option=("O:" in s)) * (100 if "O:" in s else 1)

            ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
            log_str = f"[{ts}] {(' | '.join(reports) if reports else '🟡观望')} | 🧠 {cmd.get('thought','')}"
            
            supabase.table("drones").update({
                "balance": nb, 
                "positions": np, 
                "total_assets": round(nb + mv, 2),
                "logs": ([log_str] + (d.get('logs') or []))[:20],
                "patrol_count": (int(d.get('patrol_count') or 0)) + 1,
                "memory": cmd.get('learning', d.get('memory'))
            }).eq("id", d["id"]).execute()
            
            status.update(label=f"✅ {d['name']} 演化完成！", state="complete")
            return True
        except Exception as e:
            status.update(label=f"❌ 演化失败: {str(e)}", state="error")
            return False

# --- 4. UI 界面 ---
st.set_page_config(page_title="Hive 实时控制台", page_icon="🐝", layout="wide")
st.title("🐝 Hive 蜂巢实时控制台")

t1, t2, t3 = st.tabs(["🏆 工蜂档案", "👑 蜂后孵化", "⚙️ 系统管理"])

with t1:
    res = supabase.table("drones").select("*").order("created_at", desc=True).execute()
    drones_list = res.data or []
    
    # 顶部全局操作区
    col_t, col_b = st.columns([4, 1])
    col_t.subheader(f"在线工蜂 ({len(drones_list)})")
    if drones_list and col_b.button("🔥 一键放飞全部", type="primary", use_container_width=True):
        for d in drones_list:
            evolve_drone_with_status(d)
        st.rerun()

    if not drones_list:
        st.info("蜂巢空虚，请前往“蜂后孵化”添加工蜂。")
    
    for d in drones_list:
        with st.expander(f"🐝 {d['name']} | 资产: ${d.get('total_assets', 0):,.2f} | 现金: ${d['balance']:,.2f}"):
            # 特征卡片显示
            c1, c2, c3 = st.columns(3)
            c1.info(f"🎭 **性格基因**\n\n{d.get('persona', '未设定')}")
            c2.info(f"🧬 **逻辑蓝图**\n\n{d.get('logic', '标准交易逻辑')}")
            c3.info(f"💾 **演化记忆**\n\n{d.get('memory', '尚无演化经验')}")
            
            # 单体操作区
            col_run, col_data = st.columns([1, 4])
            if col_run.button(f"🚀 立即放飞", key=f"fly_{d['id']}"):
                if evolve_drone_with_status(d):
                    time.sleep(0.5)
                    st.rerun()
            
            if d.get('positions'):
                col_data.write("**当前持仓:**")
                col_data.write(d['positions'])
            
            st.divider()
            st.caption("**近期演化日志:**")
            for l in (d.get('logs') or [])[:5]:
                st.caption(l)

with t2:
    st.subheader("👑 孵化新工蜂")
    instr = st.text_area("输入基因指令 (例如：孵化一个专门在盘前买入GLD正股的保守型蜜蜂...):", height=100)
    col_l, col_r = st.columns(2)
    init_bal = col_l.number_input("初始资金 ($)", value=100000)
    
    if st.button("开始注入基因并孵化"):
        with st.spinner("蜂后正在产卵..."):
            p = f"设计工蜂。返回纯JSON对象(不要包含```json文字)：{{'name':'','logic':'','persona':'','portfolio':['GLD']}}。指令：{instr}"
            r = gen_client.models.generate_content(model=MODEL_ID, contents=p)
            try:
                # 清洗可能的 Markdown 格式
                clean_json = r.text.replace("```json", "").replace("```", "").strip()
                item = json.loads(clean_json)
                item.update({
                    "balance": init_bal,
                    "total_assets": init_bal,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "logs": ["已从蜂巢诞生。"],
                    "positions": {},
                    "memory": "新生状态，等待首次放飞。"
                })
                supabase.table("drones").insert(item).execute()
                st.success(f"工蜂 {item['name']} 孵化成功！")
                time.sleep(1)
                st.rerun()
            except Exception as e:
                st.error(f"解析指令失败: {e}")

with t3:
    st.subheader("⚙️ 系统管理")
    if st.button("🔥 危险操作：清空所有工蜂数据"):
        supabase.table("drones").delete().neq("name", "RESERVED").execute()
        st.success("蜂巢已重置。")
        st.rerun()