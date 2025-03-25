import aiosqlite
import time
from datetime import datetime
from typing import List, Dict, Any, Optional

class TokenDB:
    def __init__(self, db_path: str = 'tokens.db'):
        self.db_path = db_path

    async def init_db(self):
        """初始化数据库"""
        async with aiosqlite.connect(self.db_path) as db:
            # 代币基本信息表
            await db.execute('''
            CREATE TABLE IF NOT EXISTS monitored_tokens (
                ca TEXT PRIMARY KEY,
                token TEXT NOT NULL,
                initial_mcap REAL NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_alert_time INTEGER DEFAULT 0,
                received_time TEXT,
                sourceType TEXT  -- 新增 sourceType 列
            )''')
            
            # 代币涨幅提醒记录表
            await db.execute('''
            CREATE TABLE IF NOT EXISTS multiple_alerts (
                ca TEXT,
                multiple INTEGER,  -- 3, 5, 10, 20, 50, 100
                alert_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (ca, multiple),
                FOREIGN KEY (ca) REFERENCES monitored_tokens(ca)
            )''')
            
            # 创建价格历史记录表
            await db.execute('''
            CREATE TABLE IF NOT EXISTS price_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ca TEXT NOT NULL,
                price_usd REAL,
                price_native REAL,
                volume_24h REAL,
                fdv REAL,
                market_cap REAL,
                liquidity_usd REAL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (ca) REFERENCES monitored_tokens(ca)
            )''')
            
            # 创建购买记录表
            await db.execute('''
            CREATE TABLE IF NOT EXISTS purchase_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ca TEXT NOT NULL,                           -- 代币合约地址
                from_token_symbol TEXT NOT NULL,            -- 支付代币符号（如 wSOL）
                from_token_amount REAL NOT NULL,            -- 支付数量
                from_token_price REAL NOT NULL,             -- 支付代币单价（USD）
                to_token_symbol TEXT NOT NULL,              -- 购买代币符号
                to_token_amount REAL NOT NULL,              -- 获得代币数量
                to_token_price REAL NOT NULL,              -- 购买代币单价（USD）
                price_impact REAL,                         -- 价格影响百分比
                trade_fee REAL,                            -- 交易费用
                dex_name TEXT,                             -- DEX名称
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'pending',              -- 交易状态：pending/success/failed
                tx_hash TEXT,                              -- 交易哈希
                FOREIGN KEY (ca) REFERENCES monitored_tokens(ca)
            )''')
            
            await db.commit()

    async def add_token(self, token: str, ca: str, initial_mcap: float, received_time: str, source_type: str) -> bool:
        """添加代币到监控列表（只记录第一次）"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                # 检查是否已存在
                async with db.execute('SELECT 1 FROM monitored_tokens WHERE ca = ?', (ca,)) as cursor:
                    if await cursor.fetchone() is None:
                        # 不存在才插入
                        await db.execute('''
                        INSERT INTO monitored_tokens (ca, token, initial_mcap, received_time, sourceType)
                        VALUES (?, ?, ?, ?, ?)
                        ''', (ca, token, initial_mcap, received_time, source_type))
                        await db.commit()
                        print(f"✅ 新增代币: {token}")
                        return True
                    else:
                        print(f"⏭️ 代币已存在，跳过: {token}")
                        return False
        except Exception as e:
            print(f"❌ 添加代币失败: {str(e)}")
            return False

    async def get_all_tokens(self) -> List[Dict[str, Any]]:
        """获取72小时内的所有监控中的代币"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute('''
            SELECT ca, token, initial_mcap, last_alert_time, received_time, sourceType
            FROM monitored_tokens
            WHERE datetime(received_time) > datetime('now', '-72 hours')
            ''') as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    async def record_alert(self, ca: str, multiple: int) -> bool:
        """记录价格提醒"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute('''
                INSERT INTO price_alerts (ca, multiple)
                VALUES (?, ?)
                ''', (ca, multiple))
                
                await db.execute('''
                UPDATE monitored_tokens
                SET last_alert_time = ?
                WHERE ca = ?
                ''', (int(time.time()), ca))
                
                await db.commit()
                return True
        except Exception as e:
            print(f"记录提醒失败: {str(e)}")
            return False

    async def get_token_stats(self) -> List[Dict[str, Any]]:
        """获取代币统计信息"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute('''
            SELECT t.ca, t.token, t.initial_mcap, t.created_at,
                   COUNT(DISTINCT p.multiple) as alert_count
            FROM monitored_tokens t
            LEFT JOIN price_alerts p ON t.ca = p.ca
            GROUP BY t.ca
            ''') as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows] 

    async def check_multiple_alerted(self, ca: str, multiple: int) -> bool:
        """检查特定倍数是否已经提醒过"""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                'SELECT 1 FROM multiple_alerts WHERE ca = ? AND multiple = ?',
                (ca, multiple)
            ) as cursor:
                return await cursor.fetchone() is not None

    async def record_multiple_alert(self, ca: str, multiple: int, max_market_cap: float) -> bool:
        """记录新的倍数提醒"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    'INSERT INTO multiple_alerts (ca, multiple, max_market_cap) VALUES (?, ?, ?)',
                    (ca, multiple, max_market_cap)
                )
                await db.commit()
                return True
        except Exception as e:
            print(f"记录倍数提醒失败: {str(e)}")
            return False 

    async def add_price_record(self, ca: str, dex_data: dict) -> bool:
        """添加价格记录"""
        try:
            # 获取第一个交易对的数据（通常是最主要的）
            pair = dex_data['pairs'][0]
            
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute('''
                INSERT INTO price_history 
                (ca, price_usd, price_native, volume_24h, fdv, market_cap, liquidity_usd)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (
                    ca,
                    float(pair.get('priceUsd', 0)),
                    float(pair.get('priceNative', 0)),
                    pair.get('volume', {}).get('h24', 0),
                    pair.get('fdv', 0),
                    pair.get('marketCap', 0),
                    pair.get('liquidity', {}).get('usd', 0)
                ))
                await db.commit()
                return True
        except Exception as e:
            print(f"记录价格数据时出错: {str(e)}")
            return False 

    async def add_purchase_record(self, quote_data: dict, ca: str) -> bool:
        """添加购买记录"""
        try:
            data = quote_data['data'][0]
            from_token = data['fromToken']
            to_token = data['toToken']
            dex_info = data['quoteCompareList'][0] if data['quoteCompareList'] else None
            
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute('''
                INSERT INTO purchase_records (
                    ca,
                    from_token_symbol,
                    from_token_amount,
                    from_token_price,
                    to_token_symbol,
                    to_token_amount,
                    to_token_price,
                    price_impact,
                    trade_fee,
                    dex_name
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    ca,
                    from_token['tokenSymbol'],
                    float(data['fromTokenAmount']) / (10 ** int(from_token['decimal'])),
                    float(from_token['tokenUnitPrice']),
                    to_token['tokenSymbol'],
                    float(data['toTokenAmount']) / (10 ** int(to_token['decimal'])),
                    float(to_token['tokenUnitPrice']),
                    float(data['priceImpactPercentage']),
                    float(data['tradeFee']),
                    dex_info['dexName'] if dex_info else None
                ))
                await db.commit()
                return True
        except Exception as e:
            print(f"记录购买数据时出错: {str(e)}")
            return False

    async def update_purchase_status(self, record_id: int, status: str, tx_hash: str = None) -> bool:
        """更新购买记录状态"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                if tx_hash:
                    await db.execute('''
                    UPDATE purchase_records 
                    SET status = ?, tx_hash = ?
                    WHERE id = ?
                    ''', (status, tx_hash, record_id))
                else:
                    await db.execute('''
                    UPDATE purchase_records 
                    SET status = ?
                    WHERE id = ?
                    ''', (status, record_id))
                await db.commit()
                return True
        except Exception as e:
            print(f"更新购买记录状态时出错: {str(e)}")
            return False 