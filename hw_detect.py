"""
硬件自动探测模块 — 从 OpenWrt 运行环境自动发现网络硬件信息。

探测逻辑：
  1. 检测桥接模式 (DSA / Swconfig)
  2. 获取 WAN 接口名
  3. 获取 LAN 端口列表
  4. Swconfig 模式下额外解析 switch 芯片参数

用户无需在配置文件中填写任何硬件信息。
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from typing import Optional

from uci import UciExecutor

# ... (omitted)

def _detect_swconfig_ports_from_cli(uci: UciExecutor, switch_name: str) -> list[int]:
    """尝试通过 swconfig 命令行列出所有端口"""
    if uci.is_export:
        return []

    # swconfig 不是 uci 子命令，必须直接执行
    try:
        # Output example: Port 0: ...
        result = subprocess.run(
            f"swconfig dev {switch_name} show | grep 'Port '",
            shell=True,
            capture_output=True,
            text=True
        )
        if result.returncode != 0:
            return []
        output = result.stdout
    except (FileNotFoundError, subprocess.CalledProcessError):
        return []
        
    ports = []
    for line in output.splitlines():
        if line.strip().startswith("Port "):
            try:
                # "Port 0:" -> "0"
                part = line.strip().split()[1].rstrip(":")
                ports.append(int(part))
            except (ValueError, IndexError):
                pass
    return sorted(list(set(ports)))
