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

    dry-run 模式下返回 DSA 默认值;
    运行时通过 uci 命令探测实际配置。
    """
    if uci.is_dry_run:
        print(">>> [硬件探测] dry-run 模式，使用默认值 (DSA)")
        return DSA_DEFAULTS

    # 1. 判断桥接模式
    is_swconfig = _detect_is_swconfig(uci)

    if is_swconfig:
        return _detect_swconfig(uci)
    else:
        return _detect_dsa(uci)


def _detect_is_swconfig(uci: UciExecutor) -> bool:
    """检测是否为 swconfig 模式"""
    result = uci.query("show network | grep '@switch\\[0\\]'")
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

    # 解析 switch_vlan 配置
    vlan1_ports = uci.query("get network.@switch_vlan[0].ports")
    if vlan1_ports:
        for token in vlan1_ports.split():
            if token.endswith("t"):
                cpu_port = int(token[:-1])
            else:
                try:
                    lan_ports.append(int(token))
                except ValueError:
                    pass

    # WAN VLAN 端口
    vlan2_ports = uci.query("get network.@switch_vlan[1].ports")
    if vlan2_ports:
        for token in vlan2_ports.split():
            if not token.endswith("t"):
                try:
                    wan_port = int(token)
                except ValueError:
                    pass

    # CPU 接口: 通常跟 WAN 接口相关
    cpu_interface = uci.query("get network.lan.ifname") or wan
    # 提取基础接口名 (去掉 .VID 后缀)
    if "." in cpu_interface:
        cpu_interface = cpu_interface.split(".")[0]

    if not lan_ports:
        lan_ports = [1, 2, 3, 4]

    switch_info = SwitchInfo(
        name=switch_name,
        cpu_port=cpu_port,
        cpu_interface=cpu_interface,
        lan_ports=lan_ports,
        wan_port=wan_port,
    )

    print(f"    Switch: {switch_name}, CPU 端口: {cpu_port}, "
          f"LAN 端口: {lan_ports}, WAN 端口: {wan_port}")

    return HardwareInfo(
        mode="swconfig",
        wan_interface=wan,
        lan_ports=[],  # swconfig 不使用 DSA 端口
        switch=switch_info,
    )
