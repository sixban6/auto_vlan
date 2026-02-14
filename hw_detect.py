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


# ------------------------------------------------------------------
# 探测结果数据模型
# ------------------------------------------------------------------
@dataclass(frozen=True)
class SwitchInfo:
    """Swconfig 模式下探测到的交换芯片参数"""
    name: str              # 交换芯片名 (如 "switch0")
    cpu_port: int          # CPU 端口号
    cpu_interface: str     # CPU 端口对应的网络接口
    lan_ports: list[int]   # LAN 物理端口列表
    wan_port: int          # WAN 端口号


@dataclass(frozen=True)
class HardwareInfo:
    """自动探测到的硬件信息"""
    mode: str              # "dsa" | "swconfig"
    wan_interface: str     # WAN 物理接口名
    lan_ports: list[str]   # LAN 端口列表 (DSA 模式)
    switch: Optional[SwitchInfo] = None  # Swconfig 模式下的 switch 信息


# ------------------------------------------------------------------
# DSA 默认值 (dry-run 模式)
# ------------------------------------------------------------------
DSA_DEFAULTS = HardwareInfo(
    mode="dsa",
    wan_interface="eth0",
    lan_ports=["eth1", "eth2"],
)


# ------------------------------------------------------------------
# 探测函数
# ------------------------------------------------------------------
def detect_hardware(uci: UciExecutor) -> HardwareInfo:
    """
    自动探测 OpenWrt 硬件信息。

    export 模式下返回 DSA 默认值;
    运行时 (含 dry-run) 尝试通过 uci 命令探测实际配置，失败则回退默认值。
    """
    if uci.is_export:
        print(">>> [硬件探测] export 模式，使用默认值 (DSA)")
        return DSA_DEFAULTS

    # 1. 优先探测 Swconfig (兼容旧设备/当前配置)
    # 用户反馈：某些双支持设备配置为 switch 时，脚本误判为 DSA
    is_swconfig = _detect_is_swconfig(uci)
    if is_swconfig:
        return _detect_swconfig(uci)

    # 2. 探测 DSA
    is_dsa = _detect_is_dsa_config(uci)
    if is_dsa:
        return _detect_dsa(uci)

    # 3. 默认回退到 DSA (假定为现代设备或无配置)
    print(">>> [硬件探测] 未检测到明确配置，默认使用 DSA 模式")
    return _detect_dsa(uci)


def _detect_is_swconfig(uci: UciExecutor) -> bool:
    """检测是否为 swconfig 模式 (检查是否存在 switch section)"""
    # 匹配 network.@switch[0]=switch 或 network.switch0=switch
    result = uci.query("show network | grep '=switch'")
    return bool(result)


def _detect_is_dsa_config(uci: UciExecutor) -> bool:
    """检测是否为 DSA 模式 (检查是否存在 bridge-vlan section)"""
    result = uci.query("show network | grep '=bridge-vlan'")
    return bool(result)


def _detect_dsa(uci: UciExecutor) -> HardwareInfo:
    """DSA 模式下探测硬件"""
    print(">>> [硬件探测] 检测到 DSA 模式")

    # WAN 接口: 优先 device，回退 ifname
    wan = (
        uci.query("get network.wan.device")
        or uci.query("get network.wan.ifname")
        or "eth0"
    )
    print(f"    WAN 接口: {wan}")

    # LAN 端口: 从 br-lan 的 ports 列表获取
    lan_ports = _detect_dsa_lan_ports(uci)
    lan_ports.sort()
    print(f"    LAN 端口: {lan_ports}")

    return HardwareInfo(
        mode="dsa",
        wan_interface=wan,
        lan_ports=lan_ports,
    )


def _detect_dsa_lan_ports(uci: UciExecutor) -> list[str]:
    """探测 DSA 模式下的 LAN 端口"""
    # 尝试从 br-lan device 配置获取端口列表
    raw = uci.query("get network.@device[0].ports")
    if raw:
        return raw.split()

    # 回退: 尝试匹配 lan_dev
    raw = uci.query("get network.lan_dev.ports")
    if raw:
        return raw.split()

    # 最终回退
    print("    ⚠️  无法自动获取 LAN 端口，使用默认值")
    return ["eth1", "eth2"]


def _detect_swconfig(uci: UciExecutor) -> HardwareInfo:
    """Swconfig 模式下探测硬件"""
    print(">>> [硬件探测] 检测到 Swconfig 模式")

    # 获取 switch 名称
    switch_name = uci.query("get network.@switch[0].name") or "switch0"

    # WAN 接口
    wan = uci.query("get network.wan.ifname") or "eth0"

    # CPU 端口: 从 VLAN 1 的端口配置中提取带 't' 标记的端口
    cpu_port = 0
    cpu_interface = "eth0"
    lan_ports: list[int] = []
    wan_port = 5

    # 解析 switch_vlan 配置以确定 CPU/WAN/LAN
    # 扫描所有 switch_vlan section 收集端口信息
    all_vlan_ports = []
    # 获取所有 vlan 配置的 ports 字段 (多行输出)
    vlan_configs = uci.query("show network | grep 'switch_vlan.*ports='")
    if vlan_configs:
        for line in vlan_configs.splitlines():
            # network.@switch_vlan[0].ports='1 5t' -> 提取 '1 5t'
            if "=" in line:
                val = line.split("=", 1)[1].strip("'")
                all_vlan_ports.append(val)

    # 分析端口角色
    for ports_str in all_vlan_ports:
        for token in ports_str.split():
            if token.endswith("t"):
                cpu_port = int(token[:-1])
            else:
                try:
                    p = int(token)
                    # 假定 VLAN 2 (通常是 WAN) 的非 tag 端口为 WAN 口
                    if p not in lan_ports:
                        lan_ports.append(p)
                except ValueError:
                    pass

    # 尝试更精准的 WAN 口识别 (通常在 @switch_vlan[1] 或名为 wan 的 vlan 中)
    # 获取 vlan 2 的端口
    vlan2_ports = uci.query("get network.@switch_vlan[1].ports")
    if vlan2_ports:
        for token in vlan2_ports.split():
            if not token.endswith("t"):
                try:
                    wan_port = int(token)
                    # 从 lan_ports 中移除 wan_port
                    if wan_port in lan_ports:
                        lan_ports.remove(wan_port)
                except ValueError:
                    pass

    # 尝试 CLI 探测硬件所有端口 (解决"只配置了1个口导致只探测到1个口"的问题)
    # 修复: 如果 UCI 已经配置了多个端口 (>=2)，则信任 UCI，不再使用 CLI 探测覆盖
    # 避免 CLI 探测出 ghost ports (物理不存在但 switch 芯片支持的端口)
    if len(lan_ports) <= 1:
        hw_ports = _detect_swconfig_ports_from_cli(uci, switch_name)
        if hw_ports:
            print(f"    [CLI] 硬件端口列表: {hw_ports}")
            # 如果 CLI 探测成功，使用 (Hardware - CPU - WAN) 作为 LAN 列表
            potential_lan = []
            for p in hw_ports:
                if p != cpu_port and p != wan_port:
                    potential_lan.append(p)
            
            if potential_lan:
                lan_ports = potential_lan
    else:
        print(f"    [UCI] 已配置 {len(lan_ports)} 个 LAN 端口，跳过 CLI 探测 (避免 ghost ports)")
    
    # 默认值兜底
    if not lan_ports:
        print("    ⚠️  未探测到 LAN 端口，使用默认值 [1, 2, 3, 4]")
        lan_ports = [1, 2, 3, 4]

    # CPU 接口: 通常跟 WAN 接口相关
    cpu_interface = uci.query("get network.lan.ifname") or wan
    # 提取基础接口名 (去掉 .VID 后缀)
    if "." in cpu_interface:
        cpu_interface = cpu_interface.split(".")[0]

    lan_ports.sort()

    switch_info = SwitchInfo(
        name=switch_name,
        cpu_port=cpu_port,
        cpu_interface=cpu_interface,
        lan_ports=lan_ports,
        wan_port=wan_port,
    )

    print(f"    Switch: {switch_name}, CPU: {cpu_port}, "
          f"WAN: {wan_port}, LAN: {lan_ports}")

    return HardwareInfo(
        mode="swconfig",
        wan_interface=wan,
        lan_ports=[],  # swconfig 不使用 DSA 端口
        switch=switch_info,
    )


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
