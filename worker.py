import os, json, pytz
import google.generativeai as genai
from polygon import RESTClient
from datetime import datetime

# --- 蜂巢环境配置 ---
POLY_KEY = os.environ.get("POLYGON_KEY")
GEMINI_KEY = os.environ.get("GEMINI_KEY")
HIVE_FILE = "hive.json"

client = RESTClient(api_key=POLY_KEY)
genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel("gemini-1.5-flash")

def is_market_open():
    tz = pytz.timezone('US/Eastern')
    now = datetime.now(tz)
    if now.weekday() >= 5: return False
    return now.replace(hour=9, minute=30) <= now <= now.replace(hour=16, minute=0)

def load_hive():
    if os.path.exists(HIVE_FILE):
        with open(HIVE_FILE, "r", encoding='utf-8') as f: return json.load(f)
    return {"drones": []}

def save_hive(data):
    with open(HIVE_FILE, "w", encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    # 自动备份：接近 16:00 ET 时保存带日期的备份
    tz = pytz.timezone('US/Eastern')
    now = datetime.now(tz)
    if 15 <= now.hour < 17:  # 15:00-17:00
        backup_file = f"hive_{now.strftime('%Y%m%d')}.json"
        with open(backup_file, "w", encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

def patrol():
    hive = load_hive()
    if not is_market_open(): 
        print("休市中，工蜂在蜂巢待命。")
        return

    for drone in hive.get("drones", []):
        try:
            print(f"正在调度工蜂: {drone['name']}...")
            
            # 1. 扫描整个投资组合 (Portfolio Radar)
            market_data = {}
            for ticker in drone["portfolio"]:
                snap = client.get_snapshot_ticker("stocks", ticker)
                market_data[ticker] = {
                    "price": getattr(snap.last_trade, 'p', 0),
                    "change_p": getattr(snap.todays_change_percent, 'p', 0)
                }
            
            # 2. 风险防御：检测跌幅超 5%
            max_decline = min([market_data[t]["change_p"] for t in market_data], default=0)
            if max_decline < -5:
                drone["status"] = "DEFENSIVE"
                print(f"⚠️ {drone['name']} 进入防守模式 (最大跌幅: {max_decline:.2f}%)")
            
            # 3. 调用 AI 决策 (Swarm Intelligence) - 增强联动性分析
            changes = [market_data[t]["change_p"] for t in market_data]
            correlation_insight = f"组合涨跌分布：最大涨幅 {max(changes):.2f}%，最大跌幅 {min(changes):.2f}%，波动差异 {max(changes) - min(changes):.2f}%"
            
            prompt = f"""
            你是工蜂 {drone['name']}。性格：{drone['style']}。
            当前监控组合：{market_data}
            核心逻辑：{drone['logic']}
            {correlation_insight}
            请重点分析组合内标的的联动性，是否存在分化？给出采蜜建议（保持/买入/卖出）并简述理由。
            """
            response = model.generate_content(prompt)
            pip install google-generativeai polygon-api-client pytz
            # 4. 记录日志 (Honey Collection)
            new_log = {
                "time": datetime.now().strftime("%H:%M"),
                "data": market_data,
                "advice": response.text[:150],
                "status": drone.get("status", "ACTIVE")
            }
            drone["logs"].append(new_log)
            drone["logs"] = drone["logs"][-20:]
            
        except Exception as e:
            print(f"工蜂 {drone['name']} 遭遇迷航: {e}")
            continue
    
    save_hive(hive)

if __name__ == "__main__":
    patrol()