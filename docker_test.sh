#!/usr/bin/env bash
# =============================================================
# OpenWrt Docker 测试脚本
# 拉取 OpenWrt Docker 镜像，运行 auto_vlan 配置，并映射 LuCI 端口
# 用法: bash docker_test.sh [--config FILE] [--port PORT]
# =============================================================

set -euo pipefail

# -----------------------------------------------
# 配置参数
# -----------------------------------------------
# 可选镜像: x86-64-24.10.5 | x86-64-23.05.6 | armvirt-64-19.07.8
# 注: armsr-armv8 镜像在 M1 Mac 上无法拉取 (非标准 Docker 平台标签)
OPENWRT_IMAGE="openwrt/rootfs:x86-64-23.05.6"
CONTAINER_NAME="auto_vlan_test"
LUCI_PORT="${LUCI_PORT:-8080}"        # 本地映射端口，默认 8080
CONFIG_FILE="network_plan.yaml"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# -----------------------------------------------
# 解析参数
# -----------------------------------------------
EXPORT_FILE=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --config)  CONFIG_FILE="$2"; shift 2 ;;
        --port)    LUCI_PORT="$2"; shift 2 ;;
        --image)   OPENWRT_IMAGE="$2"; shift 2 ;;
        --export)  EXPORT_FILE="$2"; shift 2 ;;
        -h|--help)
            echo "用法: $0 [选项]"
            echo ""
            echo "选项:"
            echo "  --config FILE              YAML 配置文件 (默认: network_plan.yaml)"
            echo "  --port PORT                LuCI 映射端口 (默认: 8080)"
            echo "  --image IMAGE              Docker 镜像 (默认: $OPENWRT_IMAGE)"
            echo "  --export FILE              导出部署脚本到宿主机 (例如: deploy.sh)"
            echo "  -h, --help                 显示帮助"
            exit 0
            ;;
        *) echo "未知参数: $1"; exit 1 ;;
    esac
done

# -----------------------------------------------
# 前置检查
# -----------------------------------------------
if ! command -v docker &>/dev/null; then
    echo "❌ 错误: 未找到 docker 命令，请先安装 Docker"
    exit 1
fi

if ! docker info &>/dev/null; then
    echo "❌ 错误: Docker 未运行或当前用户无权限"
    exit 1
fi

if [[ ! -f "${SCRIPT_DIR}/${CONFIG_FILE}" ]]; then
    echo "❌ 错误: 配置文件不存在: ${SCRIPT_DIR}/${CONFIG_FILE}"
    exit 1
fi

# -----------------------------------------------
# 清理旧容器
# -----------------------------------------------
if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    echo ">>> 清理旧容器: ${CONTAINER_NAME}"
    docker rm -f "${CONTAINER_NAME}" &>/dev/null || true
fi

# -----------------------------------------------
# 拉取镜像
# -----------------------------------------------
echo ">>> 拉取 OpenWrt 镜像: ${OPENWRT_IMAGE}"
docker pull --platform linux/amd64 "${OPENWRT_IMAGE}"

# -----------------------------------------------
# 启动容器
# -----------------------------------------------
echo ">>> 启动 OpenWrt 容器..."
docker run -d \
    --platform linux/amd64 \
    --name "${CONTAINER_NAME}" \
    -p "${LUCI_PORT}:80" \
    "${OPENWRT_IMAGE}" \
    /sbin/init

# 等待容器启动
echo ">>> 等待 OpenWrt 初始化..."
sleep 5

# 验证容器运行状态
if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    echo "❌ 容器启动失败，查看日志:"
    docker logs "${CONTAINER_NAME}"
    exit 1
fi

# -----------------------------------------------
# 安装 Python 和依赖
# -----------------------------------------------
echo ">>> 在容器中安装 Python 环境..."
docker exec "${CONTAINER_NAME}" sh -c "
    opkg update && \
    opkg install python3 python3-yaml
" 2>&1 | tail -5

# -----------------------------------------------
# 复制项目文件到容器
# -----------------------------------------------
echo ">>> 复制项目文件到容器..."
DEST_DIR="/tmp/auto_vlan"
docker exec "${CONTAINER_NAME}" mkdir -p "${DEST_DIR}"

for f in setup_network.py orchestrator.py configurators.py models.py roles.py uci.py bridge_modes.py hw_detect.py "${CONFIG_FILE}"; do
    docker cp "${SCRIPT_DIR}/${f}" "${CONTAINER_NAME}:${DEST_DIR}/${f}"
done

# -----------------------------------------------
# Export 模式分支
# -----------------------------------------------
if [[ -n "${EXPORT_FILE}" ]]; then
    echo ""
    echo "======================================================="
    echo " 执行 Export 导出脚本"
    echo "======================================================="
    echo ""

    # 在容器内生成脚本
    docker exec -w "${DEST_DIR}" "${CONTAINER_NAME}" \
        python3 setup_network.py --config "${CONFIG_FILE}" --export "deploy.sh"

    # 复制回宿主机
    echo ">>> 从容器复制脚本到宿主机: ${EXPORT_FILE}"
    docker cp "${CONTAINER_NAME}:${DEST_DIR}/deploy.sh" "${EXPORT_FILE}"
    chmod +x "${EXPORT_FILE}"

    echo ""
    echo "✅ 脚本已导出: ${EXPORT_FILE}"
    echo "   使用方法: 拷贝到路由器并执行 (sh ${EXPORT_FILE})"
    echo ""

    # 清理并退出
    docker rm -f "${CONTAINER_NAME}" &>/dev/null || true
    echo ">>> 容器已清理"
    exit 0
fi

# -----------------------------------------------
# 执行配置 (正常模式)
# -----------------------------------------------
echo ""
echo "======================================================="
echo " 执行 auto_vlan 配置 (硬件自动探测)"
echo "======================================================="
echo ""

docker exec -w "${DEST_DIR}" "${CONTAINER_NAME}" \
    python3 setup_network.py --config "${CONFIG_FILE}"

# -----------------------------------------------
# 重启网络服务
# -----------------------------------------------
echo ""
echo ">>> 重启网络服务..."
docker exec "${CONTAINER_NAME}" /etc/init.d/network restart 2>/dev/null || true

# -----------------------------------------------
# 安装 LuCI (如果尚未安装)
# -----------------------------------------------
echo ">>> 确保 LuCI 已安装..."
docker exec "${CONTAINER_NAME}" sh -c "
    if ! opkg list-installed | grep -q luci; then
        opkg install luci
    fi
" 2>&1 | tail -3

# 启动 uhttpd
docker exec "${CONTAINER_NAME}" /etc/init.d/uhttpd restart 2>/dev/null || true

# -----------------------------------------------
# 输出访问信息
# -----------------------------------------------
echo ""
echo "======================================================="
echo " ✅ OpenWrt 容器已就绪"
echo "======================================================="
echo ""
echo " 🌐 LuCI 访问地址:  http://localhost:${LUCI_PORT}"
echo " 🔑 默认密码:        无 (直接登录)"
echo ""
echo " 📋 有用的命令:"
echo "   进入容器:         docker exec -it ${CONTAINER_NAME} sh"
echo "   查看网络配置:     docker exec ${CONTAINER_NAME} uci show network"
echo "   查看 DHCP 配置:   docker exec ${CONTAINER_NAME} uci show dhcp"
echo "   查看防火墙配置:   docker exec ${CONTAINER_NAME} uci show firewall"
echo "   查看无线配置:     docker exec ${CONTAINER_NAME} uci show wireless"
echo "   停止容器:         docker rm -f ${CONTAINER_NAME}"
echo ""
echo "======================================================="

