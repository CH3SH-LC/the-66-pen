"""千星奇遇沙箱工程的后端 MCP 服务包。

只包含标准 MCP stdio server（``backend.server``）与其冒烟脚本
（``backend.smoke``）。不含窗口操作、进程启动包装或任意 shell 通道。
"""

__all__ = ["server", "smoke"]
