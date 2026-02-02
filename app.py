import os, json, pytz
import google.generativeai as genai
from polygon import RESTClient
from datetime import datetime

# --- 蜂巢环境配置 ---
# 严格遵循用户意志，使用认可的 Gemini 3 Flash Preview 模型
AI_MODEL_NAME = "gemini-3-flash-preview"
POLY_KEY = os.environ.get("POLYGON_KEY")
GEMINI_KEY = os.environ.get("GEMINI_KEY")
HIVE_FILE = "hive.json"

# 初始化客户端
client = RESTClient(api_key=POLY_KEY)
genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel(AI_MODEL_NAME)

def is_market_open():
    """判断美股或港股是否在交易时段（已整合跨时区逻辑）"""
    tz_ny = pytz.timezone('US/Eastern')
    tz_hk = pytz.timezone('Asia/Hong_Kong')
    now_ny = datetime.now(tz_ny)
    now_hk = datetime.now(tz_hk)

    # 美股开盘逻辑 (美东 09:30 - 16:00, 周一至周五)
    us_open = now_ny.weekday() < 5 and (
        (now_ny.hour == 9 and now_ny.minute >= 30) or (10 <= now_ny.hour < 16)
    )
    # 港股开盘逻辑 (北京 09:30 - 16:00, 周一至周五)
    hk_open = now_hk.weekday() < 5 and (
        (now_hk.hour == 9 and now_hk.minute >= 30) or (10 <= now_hk.hour < 16)
    )
    return us_open or hk_open

def load_hive():
    if os.path.exists(HIVE_FILE):
        try:
            with open(HIVE_FILE, "r", encoding='utf-8') as f:
                return json.load(f)
        except:
            return {"queen": "Alpha", "drones": []}
    return {"queen": "Alpha", "drones": []}

def save_hive(data):
    with open(HIVE_FILE, "w", encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    # 自动备份逻辑
    tz = pytz.timezone('US/Eastern')
    now = datetime.now(tz)
    if 15 <= now.hour < 17:
        backup_file = f"hive_{now.strftime('%Y%m%d')}.json"
        with open(backup_file, "w", encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

def patrol():
    hive = load_hive()
    if not is_market_open(): 
        print("☕ 当前非交易时段，工蜂在蜂巢待命。")
        return

    for drone in hive.get("drones", []):
        try:
            print(f"正在调度工蜂: {drone['name']}...")
            
            # 1. 扫描投资组合
            market_data = {}
            for ticker in drone["portfolio"]:
                try:
                    snap = client.get_snapshot_ticker("stocks", ticker)
                    market_data[ticker] = {
                        "price": getattr(snap.last_trade, 'p', 0),
                        "change_p": getattr(snap.todays_change_percent, 'p', 0)
                    }
                except:
                    print(f"无法获取标的 {ticker} 的快照")
            
            if not market_data: continue

            # 2. 风险防御逻辑 (5% 防御线)
            changes = [market_data[t]["change_p"] for t in market_data]
            max_decline = min(changes) if changes else 0
            
            if max_decline < -5:
                drone["status"] = "DEFENSIVE"
                print(f"⚠️ {drone['name']} 进入防守模式 (最大跌幅: {max_decline:.2f}%)")
            else:
                drone["status"] = "ACTIVE"
            
            # 3. 调用 AI 决策 (Gemini 3 Flash Preview)
            correlation_insight = f"组合涨跌分布：最大涨幅 {max(changes):.2f}%，最大跌幅 {min(changes):.2f}%"
            
            prompt = f"""
            你是工蜂 {drone['name']}。性格：{drone.get('style', '稳健')}。
            当前监控数据：{market_data}
            核心基因逻辑：{drone['logic']}
            {correlation_insight}
            请分析标的联动性并给出“采蜜建议”（保持/买入/卖出）及简短理由。
            """
            response = model.generate_content(prompt)
            
            # 4. 记录日志
            new_log = {
                "time": datetime.now().strftime("%H:%M"),
                "data": market_data,
                "advice": response.text[:200], # 增加长度以容纳 3.0 更丰富的建议
                "status": drone["status"]
            }
            if "logs" not in drone: drone["logs"] = []
            drone["logs"].append(new_log)
            drone["logs"] = drone["logs"][-20:] # 保留最近 20 条记录
            
        except Exception as e:
            print(f"工蜂 {drone['name']} 遭遇迷航: {e}")
            continue
    
    save_hive(hive)

if __name__ == "__main__":
    patrol()