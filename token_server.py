from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List
from datetime import datetime, timedelta
import asyncio
import time
from requests_oauthlib import OAuth1Session
import requests
import json
from db_operations import TokenDB
from apscheduler.schedulers.background import BackgroundScheduler
from okx_dex_api import OkxDexAPI

app = FastAPI()
db = TokenDB()

# Twitter API配置
import os
from dotenv import load_dotenv

# 加载 .env 文件中的环境变量
load_dotenv()

# 从环境变量读取配置
api_key = os.getenv("TWITTER_API_KEY")
api_key_secret = os.getenv("TWITTER_API_KEY_SECRET")
access_token = os.getenv("TWITTER_ACCESS_TOKEN")
access_token_secret = os.getenv("TWITTER_ACCESS_TOKEN_SECRET")

# 初始化Twitter OAuth
oauth = OAuth1Session(
    api_key,
    client_secret=api_key_secret,
    resource_owner_key=access_token,
    resource_owner_secret=access_token_secret
)

# 创建调度器
scheduler = BackgroundScheduler()
scheduler.start()

class TokenData(BaseModel):
    token: str
    ca: str
    marketCap: str
    date: str
    sourceType: List[str]

def parse_market_cap(mcap_str: str) -> float:
    """解析市值字符串为数字"""
    try:
        number = float(mcap_str[:-1])
        unit = mcap_str[-1].upper()
        multipliers = {'K': 1e3, 'M': 1e6, 'B': 1e9}
        return number * multipliers.get(unit, 1)
    except:
        return 0.0

def fetch_dexscreener_data(token_address: str) -> dict:
    """从DexScreener获取代币数据"""
    try:
        url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
        response = requests.get(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "Mozilla/5.0"
            },
            timeout=10
        )
        
        if response.status_code == 200:
            return response.json()
        else:
            print(f"请求失败: HTTP {response.status_code}")
            return None
            
    except Exception as e:
        print(f"获取DexScreener数据失败: {str(e)}")
        return None
    
def parse_dexscreener_data(response_json: str) -> dict:
    """解析DexScreener API的响应数据"""
    try:
        data = json.loads(response_json)
        if not data.get('pairs'):
            print("没有找到pairs数据")
            return None
            
        first_pair = data['pairs'][0]
        
        # 基本信息
        price_usd = first_pair.get('priceUsd', '0')
        pair_created_at = first_pair.get('pairCreatedAt', 0)
        
        # 社交媒体信息（可能不存在）
        social_links = {}
        if 'info' in first_pair and 'socials' in first_pair['info']:
            for social in first_pair['info']['socials']:
                if social.get('type') == 'twitter':
                    social_links['twitter'] = social.get('url', '')
                    break
        
        created_time = datetime.fromtimestamp(pair_created_at/1000).strftime('%Y-%m-%d %H:%M:%S')
        
        return {
            'price_usd': float(price_usd),
            'created_time': created_time,
            'socials': social_links
        }
        
    except Exception as e:
        print(f"解析DexScreener数据时出错: {str(e)}")
        return None
    
def format_number(num: float) -> str:
    """
    格式化数字为K/M表示
    例如:
    900 -> 900
    1500 -> 1.5K
    1500000 -> 1.5M
    """
    if num < 1000:
        return f"{num:.0f}"
    elif num < 1000000:
        return f"{num/1000:.2f}K"
    else:
        return f"{num/1000000:.2f}M"

def format_tweet_text(data: TokenData | dict, dex_data: dict, multiple: float = None) -> str:
    """格式化推文内容"""
    if multiple is not None:
        # 计算创建时间到现在的间隔
        created_time = datetime.strptime(dex_data['created_time'], '%Y-%m-%d %H:%M:%S')
        time_diff = datetime.now() - created_time
        days = time_diff.days
        hours = time_diff.seconds // 3600
        
        social_links = f"𝕏 @{dex_data['socials']['twitter'].replace('https://x.com/', '')}" if 'twitter' in dex_data['socials'] else ""
        
        return f"""🚀 DOGG 金狗Call 推荐后的收益回溯 ${data['token']} 
{social_links}
🔥 经频道推送后市值上涨 {(multiple-1)*100:.0f}% 💹
⏱️ 推送时间: {data['received_time']}
💰 金狗推送 VIP无延时群推送市值: {format_number(data['initial_mcap'])}
💰 当前市值: {format_number(data['initial_mcap'] * multiple)}
💵 价格: ${dex_data['price_usd']:.8f}

📝 CA: {data['ca']}

⏰ 代币创建时间: {days}天{hours}小时前

进入DOGG金狗Call免费版邀请链接：https://applink.feishu.cn/client/chat/chatter/add_by_link?link_token=cf2sa554-bcbf-4982-9f18-7d96dc8c94fe
无延迟版咨询tg客服 @qingdaii

无延时VIP群价格：
0.3 SOL: 7天试用卡
1 SOL: 30天月卡
2.5 SOL: 季卡
4 SOL: 半年卡
7 SOL: 年卡

SOL 收款钱包：
932Gvws8YoB2RePNR1zi5wUKVHPbXB5kRS4RZ1iaYabS

本推文由程序自动统计并发布，不可作为任何投资参考！

#SOLANA #MEMECOIN #PUMPFUN #{data['token']} """
    else:
        # 首次推文（现在不用了）
        return ""

def send_tweet(text: str) -> bool:
    """发送推文"""
    print(f"推文内容:\n{text}")
    try:
        response = oauth.post(
            "https://api.twitter.com/2/tweets",
            json={"text": text}
        )
        
        if response.status_code != 201:
            print(f"发推失败: {response.status_code} {response.text}")
            return False
            
        print(f"发推成功！")
        return True
        
    except Exception as e:
        print(f"发推出错: {str(e)}")
        return False

# 常量定义
MULTIPLES = [5, 10, 20, 50, 100]  # 监控的倍数列表
TWEET_INTERVAL = 10  # 每次发推文之间的间隔（秒），这里是10s

def schedule_tweet(text: str, delay_minutes: int = 30):
    """安排延迟发送推文"""
    current_time = datetime.now()
    target_time = current_time + timedelta(minutes=delay_minutes)
    
    print(f"\n=== {current_time.strftime('%Y-%m-%d %H:%M:%S')} ===")
    print(f"推文已加入发送队列")
    print(f"预计发送时间: {target_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"推文内容:\n{text}")
    
    # 安排任务
    scheduler.add_job(
        send_tweet,
        'date',
        run_date=target_time,
        args=[text]
    )

async def monitor_token_price():
    """监控代币价格的后台任务"""
    print("开始监控代币价格...")
    last_tweet_time = 0
    
    while True:
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            print(f"\n=== {current_time} 开始新一轮检查 ===")
            
            try:
                tokens = await db.get_all_tokens()
                print(f"{current_time} 当前监控的代币数量: {len(tokens)}")
            except Exception as e:
                print(f"{current_time} ❌ 获取代币列表失败: {str(e)}")
                raise
            
            for token in tokens:
                try:
                    print(f"\n{current_time} 检查代币: {token['token']}")
                    dex_data = fetch_dexscreener_data(token['ca'])
                    if not dex_data:
                        print(f"{current_time} 获取{token['token']}的DexScreener数据失败")
                        continue
                    
                    # 添加价格记录
                    await db.add_price_record(token['ca'], dex_data)

                    current_mcap = dex_data['pairs'][0]['fdv']
                    multiple = current_mcap / token['initial_mcap']
                    print(f"{current_time} 当前市值: {current_mcap}, 涨幅倍数: {multiple:.2f}x")
                    
                    for target_multiple in MULTIPLES:
                        if multiple >= target_multiple:
                            try:
                                if not await db.check_multiple_alerted(token['ca'], target_multiple):
                                    current_timestamp = time.time()
                                    if current_timestamp - last_tweet_time < TWEET_INTERVAL:
                                        wait_time = int(TWEET_INTERVAL - (current_timestamp - last_tweet_time))
                                        print(f"{current_time} 距离上次发推未满{TWEET_INTERVAL}秒，等待{wait_time}秒...")
                                        continue
                                    
                                    print(f"{current_time} 达到{target_multiple}倍目标，准备发送提醒")
                                    parsed_dex_data = parse_dexscreener_data(json.dumps(dex_data))
                                    if parsed_dex_data:
                                        tweet_text = format_tweet_text(token, parsed_dex_data, multiple)
                                        # 修改这里：使用延迟发送而不是直接发送
                                        schedule_tweet(tweet_text, delay_minutes=30)
                                        await db.record_multiple_alert(token['ca'], target_multiple, current_mcap)
                                        last_tweet_time = time.time()
                                        print(f"{current_time} ✅ 已安排{target_multiple}倍提醒: {token['token']}")
                            except Exception as e:
                                print(f"{current_time} ❌ 处理倍数提醒时出错: {str(e)}")
                                continue
                except Exception as e:
                    print(f"{current_time} ❌ 处理代币 {token['token']} 时出错: {str(e)}")
                    continue
            
            print(f"\n{current_time} 等待120秒后进行下一轮检查...")
            
        except Exception as e:
            print(f"{current_time} ❌ 监控任务出错: {str(e)}")
        
        try:
            await asyncio.sleep(120)
        except Exception as e:
            print(f"{current_time} ❌ sleep 出错: {str(e)}")

async def check_tokens(ca: str):
    """检查特定代币的购买报价并记录
    
    Args:
        ca: 代币的合约地址
    """
    okx_api = OkxDexAPI()
    
    try:
        print(f"\n获取代币 {ca} 的购买报价")
        # 获取报价
        quote_result = await okx_api.get_quote(
            chain_id=501,
            amount=100000000,
            from_token_address="So11111111111111111111111111111111111111112",
            to_token_address=ca
        )
        
        if quote_result.get('code') == '0':
            # 记录购买信息
            await db.add_purchase_record(quote_result, ca)
            print(f"✅ 成功记录购买信息: {ca}")
            return quote_result
        else:
            print(f"❌ 获取报价失败: {quote_result.get('msg', '未知错误')}")
            return None
            
    except Exception as e:
        print(f"获取代币 {ca} 报价时出错: {str(e)}")
        return None

@app.post("/receive_token")
async def receive_token(data: TokenData):
    try:
        # 1. 打印接收到的原始数据
        print("\n=== 开始处理新请求 ===")
        print(f"接收到的数据: {data.dict()}")
        
        # 2. 获取DexScreener数据
        print("\n正在获取DexScreener数据...")
        dex_raw_data = fetch_dexscreener_data(data.ca)
        if not dex_raw_data:
            print("❌ 获取DexScreener数据失败")
            return {
                "status": "error",
                "message": "获取DexScreener数据失败"
            }
        print("✅ 成功获取DexScreener数据")
        
        # 3. 解析DexScreener数据并存入数据库
        print("\n正在解析DexScreener数据...")
        dex_data = parse_dexscreener_data(json.dumps(dex_raw_data))
        if not dex_data:
            print("❌ 解析DexScreener数据失败")
            return {
                "status": "error",
                "message": "解析DexScreener数据失败"
            }
        print(f"✅ 解析结果: {dex_data}")
        
        # 4. 存入数据库
        mcap = parse_market_cap(data.marketCap)
        if mcap > 0:
            if await db.add_token(data.token, data.ca, mcap, data.date, data.sourceType):
                print(f"添加到数据库: {data.token}")

        # 5. 获取 OKX DEX 报价并记录
        quote_result = await check_tokens(data.ca)
        
        return {
            "status": "success",
            "message": f"成功接收并存储 {data.token} 的数据",
            "initial_mcap": mcap,
            "dex_data": dex_data,
            "quote_data": quote_result
        }
        
    except Exception as e:
        print(f"\n❌ 发生错误: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"处理数据时出错: {str(e)}"
        )

@app.get("/monitored_tokens")
async def view_monitored_tokens():
    """查看监控列表"""
    stats = await db.get_token_stats()
    return {
        "total_count": len(stats),
        "tokens": stats
    }

@app.on_event("startup")
async def startup_event():
    await db.init_db()
    asyncio.create_task(monitor_token_price())

# 在程序退出时关闭调度器
@app.on_event("shutdown")
async def shutdown_event():
    scheduler.shutdown()



if __name__ == "__main__":
    import uvicorn
    print("启动Token数据接收服务...")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info") # 放到服务器上要改成0.0.0.0