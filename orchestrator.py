"""
编排器 — 顶层流水线，串联所有配置器完成端到端配置。

职责：加载 YAML → 解析模型 → 探测硬件 → 创建桥接模式 → 遍历网络 → 调用配置器 → 提交 → 输出摘要。
"""

from __future__ import annotations

from pathlib import Path

import yaml

from bridge_modes import BridgeMode, create_bridge_mode
from configurators import (
    DhcpConfigurator,
    FirewallConfigurator,
    WiFiConfigurator,
)
from hw_detect import HardwareInfo, detect_hardware
from models import WifiInfo, parse_config
from roles import RoleRegistry
from uci import UciExecutor


class NetworkOrchestrator:
    """
    网络配置编排器。

    使用示例：
        uci = UciExecutor(dry_run=True)
        registry = create_default_registry()
        orchestrator = NetworkOrchestrator(uci, registry)
        orchestrator.run("network_plan.yaml")
    """

    def __init__(self, uci: UciExecutor, registry: RoleRegistry) -> None:
        self._uci = uci
        self._registry = registry

        # 配置器实例
        self._dhcp = DhcpConfigurator()
        self._wifi = WiFiConfigurator()
        self._firewall = FirewallConfigurator()

    # ----------------------------------------------------------
    # 主入口
    # ----------------------------------------------------------
    def run(self, config_path: str) -> None:
        """执行完整的网络配置流程"""
        proxy_cfg, networks = self._load_config(config_path)
        wifi_table: list[WifiInfo] = []

        # 自动探测硬件
        hw = detect_hardware(self._uci)

        # 创建桥接模式
        bridge_mode = create_bridge_mode(hw)

        print("=" * 55)
        print(">>> 开始根据 YAML 配置网络")
        print(f"    桥接模式: {bridge_mode.mode_name} (自动探测)")
        
        # 自动分配物理端口
        self._auto_allocate_ports(networks, hw)

        print(f"    可用角色: {self._registry.available_roles}")
        print("=" * 55)

        # 1. 配置桥接基础设施（网桥或交换芯片）
        bridge_mode.configure_base(self._uci, hw)

        # 2. 逐网络配置
        for net in networks:
            role = self._registry.get(net.role)
            print(f"\n>>> 处理网络: {net.name} [{net.alias}] "
                  f"(VLAN {net.vlan_id}, 角色: {net.role})")

            bridge_mode.configure_vlan(self._uci, net, hw)
            bridge_mode.configure_interface(self._uci, net)
            self._dhcp.configure(self._uci, net, proxy_cfg, role)

            wifi_info = self._wifi.configure(self._uci, net)
            if wifi_info:
                wifi_table.append(wifi_info)

            self._firewall.configure(self._uci, net, role)

        # 3. 提交所有更改
        self._commit()

        # 4. 输出摘要
        self._print_summary(wifi_table)

    # ----------------------------------------------------------
    # 内部方法
    # ----------------------------------------------------------
    @staticmethod
    def _load_config(config_path: str):
        """加载并解析 YAML 配置文件"""
        path = Path(config_path)
        if not path.exists():
            raise FileNotFoundError(f"配置文件不存在: {path}")

        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)

        return parse_config(raw)

    def _commit(self) -> None:
        """提交所有 UCI 子系统（跳过不存在的子系统）"""
        print("\n>>> 正在提交 UCI 配置...")
        for subsystem in ("network", "dhcp", "firewall", "wireless"):
            # Export 模式下无法探测目标环境，默认全部生成
            if self._uci.is_export:
                self._uci.commit(subsystem)
                continue

            # 运行时探测：某些环境可能缺少子系统（如 x86 Docker 无 wireless）
            if not self._uci.is_dry_run and self._uci.query(f"show {subsystem}") is None:
                print(f"  ⚠️  跳过 {subsystem}（子系统不存在）")
                continue
            self._uci.commit(subsystem)

    @staticmethod
    def _print_summary(wifi_table: list[WifiInfo]) -> None:
        """打印 WiFi 凭据摘要表"""
        print()
        print("=" * 55)
        print(" 配置完成！请重启网络服务或重启路由器。")
        print(" WiFi 信息如下（请截图保存）:")
        print("=" * 55)
        print(f"  {'SSID':<20} | {'Password':<15} | {'Role':<10}")
        print("  " + "-" * 50)
        for info in wifi_table:
            print(f"  {info.ssid:<20} | {info.password:<15} | {info.role:<10}")
        print("=" * 55)

    def _auto_allocate_ports(self, networks: list[NetworkConfig], hw: HardwareInfo) -> None:
        """
        自动分配物理端口给各个网络 (简单策略: 1对1分配)。
        优先满足前面的网络，剩余端口归属 VLAN 1。
        """
        total_ports = len(hw.lan_ports)
        if total_ports == 0:
            print(">>> [Auto Alloc] 无可用物理端口，跳过自动分配")
            return

        # 逻辑端口索引: 1..N (对应 lan1..lanN)
        available_indices = list(range(1, total_ports + 1))
        
        print(f">>> [Auto Alloc] 开始自动端口分配 (可用: {total_ports} 个)")

        # 识别需要分配的网络 (未手动指定 ports 的)
        targets = [net for net in networks if not net.ports]
        
        # 逐个分配
        for net in targets:
            if not available_indices:
                print(f"    - {net.name}: 无可用端口 (WiFi only)")
                continue
            
            # 分配一个端口 (Index)
            idx = available_indices.pop(0)
            port_name = f"lan{idx}" # 默认 Untagged
            net.ports.append(port_name) 
            print(f"    - {net.name}: 分配 {port_name}")

        # 剩余端口归属 VLAN 1 (lan)
        if available_indices:
            vlan1_net = next((n for n in networks if n.vlan_id == 1), None)
            if vlan1_net:
                extras = [f"lan{i}" for i in available_indices]
                print(f"    - {vlan1_net.name} (VLAN 1): 追加剩余端口 {extras}")
                vlan1_net.ports.extend(extras)
            else:
                extras = [f"lan{i}" for i in available_indices]
                print(f"    - 剩余端口 {extras} 未使用 (未找到 VLAN 1)")
