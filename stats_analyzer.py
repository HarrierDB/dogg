from datetime import datetime, timedelta, timezone
import sqlite3
import schedule
import time
import requests

class StatsAnalyzer:
    # 放到服务器上需要修改 tokens.db
    def __init__(self, db_path='tokens.db'):
        self.db_path = db_path
        self.feishu_webhook = "https://open.feishu.cn/open-apis/bot/v2/hook/d6548b76-2bd9-449c-be50-8cfafcb30b19"

    def send_to_feishu(self, text):
        """发送消息到飞书"""
        data = {
            "msg_type": "text",
            "content": {
                "text": text
            }
        }
        try:
            response = requests.post(self.feishu_webhook, json=data)
            if response.status_code == 200:
                print("飞书消息发送成功")
            else:
                print(f"飞书消息发送失败: {response.status_code}")
        except Exception as e:
            print(f"发送飞书消息时出错: {str(e)}")

    def get_24h_stats(self):
        """获取过去24小时内每个小时的创建次数和涨幅"""
        # now = datetime.now()
        # yesterday = now - timedelta(days=1)
        now_utc = datetime.now(timezone.utc)
        yesterday_utc = now_utc - timedelta(days=1)
        
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            query = """
            WITH hourly_tokens AS (
                SELECT 
                    strftime('%H', mt.created_at) as hour,
                    mt.token,
                    mt.ca,
                    ma.multiple,
                    ma.max_market_cap
                FROM monitored_tokens mt
                LEFT JOIN multiple_alerts ma ON mt.ca = ma.ca
                WHERE mt.created_at BETWEEN ? AND ?
            )
            SELECT 
                hour,
                GROUP_CONCAT(token) as tokens,
                GROUP_CONCAT(multiple) as multiples,
                GROUP_CONCAT(max_market_cap) as market_caps
            FROM hourly_tokens
            GROUP BY hour
            ORDER BY hour
            """
            
            cursor.execute(query, (yesterday_utc.strftime('%Y-%m-%d %H:%M:%S'), 
                                 now_utc.strftime('%Y-%m-%d %H:%M:%S')))
            
            # 初始化24小时的数据
            hourly_stats = {f"{i:02d}": {"tokens": [], "multiples": [], "market_caps": []} 
                          for i in range(24)}
            
            # 填充实际数据
            for hour, tokens, multiples, market_caps in cursor.fetchall():
                if tokens:  # 如果这个小时有代币
                    tokens = tokens.split(',')
                    multiples = [float(m) if m else 0 for m in (multiples.split(',') if multiples else [0] * len(tokens))]
                    market_caps = [float(m) if m else 0 for m in (market_caps.split(',') if market_caps else [0] * len(tokens))]
                    
                    hourly_stats[hour] = {
                        "tokens": tokens,
                        "multiples": multiples,
                        "market_caps": market_caps
                    }
            
            return hourly_stats
            
        finally:
            conn.close()

    def generate_report(self):
        """生成统计报告"""
        stats = self.get_24h_stats()
        
        # 获取统计的日期（当前时间的前一天）
        report_date = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        report = f"\n=== 金狗创建统计报告 ({report_date}) ===\n"
        
        # 计算每小时的收益和大市值代币数量
        hourly_profits = {}
        hourly_high_mcap_counts = {}
        
        # 按小时显示详细统计
        for hour, data in sorted(stats.items()):
            if data["tokens"]:  # 只显示有创建记录的小时
                # 将 UTC 时间转换为北京时间（+8小时）
                beijing_hour = (int(hour) + 8) % 24
                report += f"\n{beijing_hour:02d}时，创建{len(data['tokens'])}个代币"
                
                # 统计该小时的总收益和大市值代币数
                profit = 0
                high_mcap_count = 0
                valid_tokens = []  # 存储符合条件的代币信息
                
                # 用于记录每个代币的最大倍数
                token_max_multiple = {}  # 使用字典记录每个代币的最大倍数
                
                # 处理每个代币的详细信息
                for token, multiple, market_cap in zip(data["tokens"], data["multiples"], data["market_caps"]):
                    market_cap_m = market_cap / 1_000_000 if market_cap else 0
                    
                    # 统计大市值代币
                    if market_cap_m >= 4.2:
                        high_mcap_count += 1
                    
                    # 更新token的最大倍数
                    if multiple >= 3:
                        if token not in token_max_multiple or multiple > token_max_multiple[token]:
                            token_max_multiple[token] = multiple
                    
                    # 只显示符合条件的代币
                    if multiple >= 3 or market_cap_m >= 4.2:
                        valid_tokens.append((token, multiple, market_cap_m))
                
                # 计算总收益（使用每个代币的最大倍数）
                profit = sum(token_max_multiple.values())
                
                # 如果这个小时有代币但都不符合条件
                if len(data["tokens"]) > 0 and not valid_tokens:
                    report += "，均未超过4.2M"
                
                report += "\n"
                
                # 显示符合条件的代币详细信息
                valid_tokens = sorted(valid_tokens, key=lambda x: (-x[1], x[0]))  # 按倍数降序排列
                valid_tokens = list({t[0]: t for t in valid_tokens}.values())  # 按token去重，保留最高倍数
                for token, multiple, market_cap_m in valid_tokens:
                    report += f" - {token} {multiple:.1f}倍，最高市值{market_cap_m:.1f}M\n"
                
                if profit > 0:
                    hourly_profits[hour] = profit
                if high_mcap_count > 0:
                    hourly_high_mcap_counts[hour] = high_mcap_count
        
        # 添加收益排名前5的时段
        if hourly_profits:
            report += "\n24小时内金狗频繁出现在："
            top_profits = sorted(hourly_profits.items(), key=lambda x: x[1], reverse=True)[:5]
            for hour, profit in top_profits:
                beijing_hour = (int(hour) + 8) % 24
                report += f"{beijing_hour:02d}时({profit:.1f}倍收益)、"
            report = report.rstrip('、') + "\n"
        
        # 添加大市值代币数量排名前5的时段
        if hourly_high_mcap_counts:
            report += "\n24小时大市值代币集中时段："
            top_mcaps = sorted(hourly_high_mcap_counts.items(), key=lambda x: x[1], reverse=True)[:5]
            for hour, count in top_mcaps:
                beijing_hour = (int(hour) + 8) % 24
                report += f"{beijing_hour:02d}时({count}个)、"
            report = report.rstrip('、') + "\n"
        
        print(report)
        
        # 保存报告到文件
        with open('dogg_stats.log', 'a', encoding='utf-8') as f:
            f.write(report)
            
        # 发送到飞书
        self.send_to_feishu(report)

def run_analysis():
    """运行统计分析"""
    analyzer = StatsAnalyzer()
    analyzer.generate_report()

def main():
    print("启动金狗创建频率统计服务...")
    
    # 设置每天00:00运行
    schedule.every().day.at("00:00").do(run_analysis)
    
    # 先运行一次
    run_analysis()
    
    # 保持程序运行
    while True:
        schedule.run_pending()
        time.sleep(60)

if __name__ == "__main__":
    main() 