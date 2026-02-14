"""
桥接模式策略层 — DSA 与 Swconfig 的抽象。

桥接模式由 hw_detect 模块自动检测，用户无需关心。

检测逻辑（已迁移至 hw_detect.py）：
  - 有 @switch[0] 配置 → Swconfig
  - 否则 → DSA
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from hw_detect import HardwareInfo, SwitchInfo
from models import NetworkConfig
from uci import UciExecutor


# ================================================================
# 抽象基类
# ================================================================
class BridgeMode(ABC):
    """桥接模式策略接口"""

    @property
    @abstractmethod
    def mode_name(self) -> str:
        """返回模式名称，用于日志输出"""

    @abstractmethod
    def configure_base(self, uci: UciExecutor, hw: HardwareInfo) -> None:
        """配置网桥基础设施 (DSA: br-lan / Swconfig: switch0)"""

    @abstractmethod
    def configure_vlan(
        self, uci: UciExecutor, net: NetworkConfig, hw: HardwareInfo
    ) -> None:
        """为单个网络创建 VLAN 条目"""

    @abstractmethod
    def configure_interface(
        self, uci: UciExecutor, net: NetworkConfig
    ) -> None:
        """配置 L3 接口的设备绑定 (DSA: device / Swconfig: ifname)"""


# ================================================================
# DSA 模式
# ================================================================
class DsaBridgeMode(BridgeMode):
    """
    DSA 模式 — 适用于较新版本的 OpenWrt。

    使用 br-lan 网桥 + VLAN 过滤 + bridge-vlan 条目。
    接口通过 `device` 字段绑定到 `br-lan.VID`。
    """

    @property
    def mode_name(self) -> str:
        return "DSA"

    def configure_base(self, uci: UciExecutor, hw: HardwareInfo) -> None:
        print(f"\n>>> [Bridge/DSA] 创建 br-lan，端口: {hw.lan_ports}")
        uci.set("network.lan_dev", "device")
        uci.set("network.lan_dev.name", "br-lan")
        uci.set("network.lan_dev.type", "bridge")
        for port in hw.lan_ports:
            uci.add_list("network.lan_dev.ports", port)
        uci.set("network.lan_dev.vlan_filtering", "1")

    def configure_vlan(
        self, uci: UciExecutor, net: NetworkConfig, hw: HardwareInfo
    ) -> None:
        vid = net.vlan_id
        print(f"  [Bridge-VLAN/DSA] VLAN {vid}")
        uci.add("network", "bridge-vlan")
        uci.set("network.@bridge-vlan[-1].device", "br-lan")
        uci.set("network.@bridge-vlan[-1].vlan", str(vid))

        # VLAN 1 (默认 LAN)：物理口作为 Untagged 成员
        # 其他 VLAN 作为纯虚拟接口，等待 WiFi 绑定
        if vid == 1:
            for port in hw.lan_ports:
                uci.add_list("network.@bridge-vlan[-1].ports", port)

    def configure_interface(
        self, uci: UciExecutor, net: NetworkConfig
    ) -> None:
        name = net.name
        device = f"br-lan.{net.vlan_id}"
        print(f"  [Interface/DSA] {name} -> {device} ({net.subnet}/{net.netmask})")
        uci.set(f"network.{name}", "interface")
        uci.set(f"network.{name}.device", device)
        uci.set(f"network.{name}.proto", "static")
        uci.set(f"network.{name}.ipaddr", net.subnet)
        uci.set(f"network.{name}.netmask", net.netmask)


# ================================================================
# Swconfig 模式
# ================================================================
class SwconfigBridgeMode(BridgeMode):
    """
    Swconfig 模式 — 适用于传统交换芯片的 OpenWrt。

    使用 switch + switch_vlan 条目。
    接口通过 `ifname` 字段绑定到 `ethX.VID`，并设置 type='bridge'。
    """

    def __init__(self, switch: SwitchInfo) -> None:
        self._switch = switch

    @property
    def mode_name(self) -> str:
        return "Swconfig"

    def configure_base(self, uci: UciExecutor, hw: HardwareInfo) -> None:
        sw = self._switch
        print(f"\n>>> [Switch/Swconfig] 配置交换芯片: {sw.name}, "
              f"CPU 端口: {sw.cpu_port}, LAN 端口: {sw.lan_ports}")
        uci.set(f"network.{sw.name}", "switch")
        uci.set(f"network.{sw.name}.name", sw.name)
        uci.set(f"network.{sw.name}.reset", "1")
        uci.set(f"network.{sw.name}.enable_vlan", "1")

    def configure_vlan(
        self, uci: UciExecutor, net: NetworkConfig, hw: HardwareInfo
    ) -> None:
        sw = self._switch
        vid = net.vlan_id

        # 构建端口列表：CPU 端口始终为 Tagged，LAN 端口视 VLAN 决定
        cpu_port_str = f"{sw.cpu_port}t"

        if vid == 1:
            # 默认 LAN VLAN：LAN 物理口为 Untagged 成员
            lan_ports_str = " ".join(str(p) for p in sw.lan_ports)
            ports = f"{lan_ports_str} {cpu_port_str}"
        else:
            # 其他 VLAN：仅 CPU 端口（Tagged），等待 WiFi 绑定
            ports = cpu_port_str

        print(f"  [Switch-VLAN/Swconfig] VLAN {vid}, 端口: {ports}")
        uci.add("network", "switch_vlan")
        uci.set("network.@switch_vlan[-1].device", sw.name)
        uci.set("network.@switch_vlan[-1].vlan", str(vid))
        uci.set("network.@switch_vlan[-1].ports", ports)

    def configure_interface(
        self, uci: UciExecutor, net: NetworkConfig
    ) -> None:
        sw = self._switch
        name = net.name
        ifname = f"{sw.cpu_interface}.{net.vlan_id}"
        print(f"  [Interface/Swconfig] {name} -> {ifname} ({net.subnet}/{net.netmask})")
        uci.set(f"network.{name}", "interface")
        uci.set(f"network.{name}.type", "bridge")
        uci.set(f"network.{name}.ifname", ifname)
        uci.set(f"network.{name}.proto", "static")
        uci.set(f"network.{name}.ipaddr", net.subnet)
        uci.set(f"network.{name}.netmask", net.netmask)


# ================================================================
# 模式工厂
# ================================================================
def create_bridge_mode(hw: HardwareInfo) -> BridgeMode:
    """
    根据探测结果创建对应的桥接模式策略。

    参数:
        hw: 由 hw_detect.detect_hardware() 探测到的硬件信息

    返回:
        BridgeMode 实例
    """
    if hw.mode == "swconfig" and hw.switch is not None:
        print(f">>> 桥接模式: Swconfig (自动探测)")
        return SwconfigBridgeMode(hw.switch)
    else:
        print(f">>> 桥接模式: DSA (自动探测)")
        return DsaBridgeMode()
