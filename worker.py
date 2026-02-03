import os, json, pytz
import google.generativeai as genai
from polygon import RESTClient
from supabase import create_client
from datetime import datetime

# --- 初始化环境 ---
# 确保在 GitHub Secrets 或本地环境变量中配置了以下 Key
client_poly = RESTClient(api_key=os.environ.get("POLYGON_KEY"))
supabase = create_client(os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY"))
genai.configure(api_key=os.environ.get("GEMINI_KEY"))
model = genai.GenerativeModel("gemini-3-flash-preview")

def is_market_open():
    """判断美股盘中时间 (ET 09:30 - 16:00)"""
    et_tz = pytz.timezone('US/Eastern')
    now = datetime.now(et_tz)
    if now.weekday() >= 5: return False
    start = now.replace(hour=9, minute=30, second=0, microsecond=0)
    end = now.replace(hour=16, minute=0, second=0, microsecond=0)
    return start <= now <= end

def get_market_context(symbol):
    """获取标的的期权链及基础行情"""
    try:
        # 获取标的最后成交价
        last_trade = client_poly.get_last_trade(symbol)
        price = last_trade.price if last_trade else 0
        
        # 获取期权快照 (筛选最近到期的 ATM/OTM/ITM 合约)
        chain = client_poly.list_snapshot_options_chain(
            symbol,
            params={"expiration_date.gte": datetime.now().strftime("%Y-%m-%d"), "limit": 10}
        )
        
        options = []
        for opt in chain:
            greeks = getattr(opt, 'greeks', {})
            options.append({
                "ticker": opt.ticker,
                "strike": opt.details.strike_price,
                "type": opt.details.contract_type,
                "delta": getattr(greeks, 'delta', 'N/A'),
                "price": opt.last_trade.p,
                "iv": getattr(opt, 'implied_volatility', 'N/A')
            })
        return {"price": price, "options_pool": options}
    except Exception as e:
        print(f"获取 {symbol} 行情失败: {e}")
        return {"price": 0, "options_pool": []}

def patrol_and_evolve():
    market_open = is_market_open()
    drones = supabase.table("drones").select("*").execute().data
    
    for d in drones:
        try:
            print(f"--- 兵蜂巡检: {d['name']} ---")
            
            # 1. 获取行情数据
            portfolio = d.get('portfolio', ['SPY'])
            m_data = {ticker: get_market_context(ticker) for ticker in portfolio}
            
            # 2. 构建 Prompt：植入交易协议与复盘逻辑
            restriction = "" if market_open else "【非交易时段：禁止 BUY/SELL。请仅分析并在 learning 中记录你想做的交易复盘。】"
            
            prompt = f"""你是专业交易员兵蜂 {d['name']}。
            基因逻辑: {d['logic']} ({d['persona']})
            往期复盘记忆: {d.get('memory')}
            账户余额: ${d['balance']} | 当前持仓: {d.get('positions')}
            实时行情: {m_data}
            
            {restriction}

            【交易协议强制约束】:
            - 股票/ETF: 使用简洁代码 (如 'FCX', 'TSLA')。
            - 期权: 必须使用 Polygon 标准格式 'O:SYMBOLYYMMDD[C/P]行权价' (例如 'O:FCX260116C00050000')。
            - 严禁在 symbol 字段写入任何描述性文字（如 'Collar Strategy'），否则将导致系统计算错误。
            
            返回纯JSON: 
            {{
                "action": "BUY/SELL/HOLD", 
                "symbol": "...", 
                "qty": 0, 
                "price": 0, 
                "reason": "基于基因和行情的决策逻辑", 
                "learning": "本次巡检的深度复盘心得"
            }}"""

            # 3. AI 决策
            res = model.generate_content(prompt).text.strip()
            # 兼容 Markdown 代码块格式
            clean_res = res.replace("```json", "").replace("```", "").strip()
            cmd = json.loads(clean_res)
            
            # 4. 非交易时段强制 HOLD
            if not market_open: cmd['action'] = 'HOLD'
            
            # 5. 更新账本逻辑
            update = {}
            
            # 日志记录：保存思考过程
            new_log = {
                "time": datetime.now().strftime("%m-%d %H:%M"), 
                "thought": cmd['reason'], 
                "action": cmd['action'],
                "symbol": cmd.get('symbol')
            }
            update['logs'] = ([new_log] + (d.get('logs') or []))[:10]
            
            # 执行模拟交易
            if cmd['action'] == 'BUY':
                cost = cmd['qty'] * cmd['price']
                if d['balance'] >= cost:
                    update['balance'] = float(d['balance']) - cost
                    pos = d.get('positions', {}).copy()
                    pos[cmd['symbol']] = pos.get(cmd['symbol'], 0) + cmd['qty']
                    update['positions'] = pos

            # 6. 记忆迭代：将复盘心得写入 memory
            # 注意：杂交时应清空此处，仅保留此处产生的“后天复盘”
            update['memory'] = f"最新记录：{cmd['learning']}"
            
            # 计算总资产与峰值 (用于回撤计算)
            current_cash = float(update.get('balance', d['balance']))
            update['peak_balance'] = max(float(d.get('peak_balance') or 0), current_cash, 1.0)
            
            # 7. 保存至数据库
            supabase.table("drones").update(update).eq("id", d["id"]).execute()
            print(f"✅ {d['name']} 状态已同步。指令: {cmd['action']}")

        except Exception as e:
            print(f"❌ {d['name']} 异常: {e}")

if __name__ == "__main__":
    patrol_and_evolve()