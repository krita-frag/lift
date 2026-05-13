name = "python"
version = "3.11"

# 使用系统 Python
# 这是一个 shim 包，用于满足依赖关系
def commands():
    import os
    import sys
    global env
    
    # 将当前 Python 的路径添加到环境中
    env.PATH.prepend(os.path.dirname(sys.executable))
