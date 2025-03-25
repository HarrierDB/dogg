valid_tokens = [
    ("SWQUERY", 5.0, 5.9),
    ("SWQUERY", 10.0, 9.4),
    ("TOKEN1", 5.0, 5.9),
    ("TOKEN2", 3.0, 4.0)
]
# 显示符合条件的代币详细信息
valid_tokens = sorted(valid_tokens, key=lambda x: (-x[1], x[0]))  # 按倍数降序排列
valid_tokens = list({t[0]: t for t in valid_tokens}.values())  # 按token去重，保留最高倍数

print(valid_tokens)


import time
from functools import wraps

def timer(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        start = time.time()
        result = func(*args, **kwargs)
        end = time.time()
        print(f"{end-start}")
        return result
    return wrapper
