name = "python"
version = "3.11"

def commands():
    import os
    import sys
    global env

    env.PATH.prepend(os.path.dirname(sys.executable))
