from dataclasses import dataclass, field
from typing import Optional

# Mock WifiConfig
@dataclass(frozen=True)
class WifiConfig:
    ssid: str
    password: str

# Mock NetworkConfig
@dataclass(frozen=True)
class NetworkConfig:
    name: str
    vlan_id: int
    ports: list[str] = field(default_factory=list)
    wifi: Optional[WifiConfig] = None

# Mock HardwareInfo
@dataclass
class HardwareInfo:
    lan_ports: list[int]  # 物理端口号列表 (e.g., [2, 3, 4])

# Mock Orchestrator logic
class NetworkOrchestrator:
    def _auto_allocate_ports(self, networks: list[NetworkConfig], hw: HardwareInfo) -> None:
        """
        自动分配物理端口给各个网络 (简单策略: 1对1分配)。
        优先满足前面的网络，剩余端口归属 VLAN 1。
        """
        # 使用实际探测到的 LAN 端口列表 (已排除 WAN 口)
        available_ports = list(hw.lan_ports)
        total_ports = len(available_ports)
        
        if total_ports == 0:
            print(">>> [Auto Alloc] 无可用物理端口，跳过自动分配")
            return

        print(f">>> [Auto Alloc] 开始自动端口分配 (可用: {total_ports} 个, 端口: {available_ports})")

        # 识别需要分配的网络 (未手动指定 ports 的)
        targets = [net for net in networks if not net.ports]
        
        # 逐个分配
        for net in targets:
            if not available_ports:
                print(f"    - {net.name}: 无可用端口 (WiFi only)")
                continue
            
            # 分配一个端口
            port_num = available_ports.pop(0)
            port_name = f"lan{port_num}" # e.g. lan2
            net.ports.append(port_name) 
            print(f"    - {net.name}: 分配 {port_name}")

        # 剩余端口归属 VLAN 1 (lan)
        if available_ports:
            vlan1_net = next((n for n in networks if n.vlan_id == 1), None)
            if vlan1_net:
                extras = [f"lan{p}" for p in available_ports]
                print(f"    - {vlan1_net.name} (VLAN 1): 追加剩余端口 {extras}")
                vlan1_net.ports.extend(extras)
            else:
                extras = [f"lan{p}" for p in available_ports]
                print(f"    - 剩余端口 {extras} 未使用 (未找到 VLAN 1)")

if __name__ == "__main__":
    # Setup
    # 模拟场景: 4口路由器，wan口已占用(port 1)，剩下 port 2, 3, 4 可用
    hw = HardwareInfo(lan_ports=[2, 3, 4]) 
    
    networks = [
        NetworkConfig(name="lan", vlan_id=1, wifi=WifiConfig("MyHome_5G", "12345678")),
        NetworkConfig(name="home", vlan_id=5, wifi=WifiConfig("Guest_Wifi", "88888888")),
        NetworkConfig(name="iot", vlan_id=3, wifi=None) # IoT 无 WiFi
    ]
    
    # Run
    orc = NetworkOrchestrator()
    orc._auto_allocate_ports(networks, hw)
    
    # Check Result
    print("\nResult:")
    for net in networks:
        wifi_str = f"SSID: {net.wifi.ssid}" if net.wifi else "No WiFi"
        print(f"{net.name} (VLAN {net.vlan_id}): Ports={net.ports}, {wifi_str}")
