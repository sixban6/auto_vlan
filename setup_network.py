#!/usr/bin/env python3
"""
OpenWrt 网络自动化 — CLI 入口。

用法:
    python3 setup_network.py                          # 正式执行 (自动探测硬件和模式)
    python3 setup_network.py --dry-run                # 仅打印命令，不执行
    python3 setup_network.py --config custom.yaml     # 指定配置文件
"""

from __future__ import annotations

import argparse
import sys

from orchestrator import NetworkOrchestrator
from roles import create_default_registry
from uci import UciExecutor


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="OpenWrt 网络自动化配置工具 (自动探测 DSA/Swconfig)",
    )
    parser.add_argument(
        "--config",
        default="network_plan.yaml",
        help="YAML 配置文件路径 (默认: network_plan.yaml)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="试运行模式 — 仅打印 UCI 命令，不实际执行",
    )
    parser.add_argument(
        "--export",
        metavar="FILE",
        help="导出为 Shell 脚本文件 (例如: deploy.sh)，不直接执行",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.dry_run:
        print(">>> ⚠️  DRY-RUN 模式 — 所有 UCI 命令仅打印，不执行\n")
    if args.export:
        print(f">>> 📤 EXPORT 模式 — 生成部署脚本: {args.export}\n")

    # Export 模式隐含 dry-run (不执行命令)
    is_dry_run = args.dry_run or bool(args.export)
    uci = UciExecutor(dry_run=is_dry_run, export=bool(args.export))

    registry = create_default_registry()
    orchestrator = NetworkOrchestrator(uci, registry)

    try:
        orchestrator.run(args.config)
        
        if args.export:
            uci.write_script(args.export)

    except FileNotFoundError as e:
        print(f"\n❌ 错误: {e}", file=sys.stderr)
        sys.exit(1)
    except ValueError as e:
        print(f"\n❌ 配置错误: {e}", file=sys.stderr)
        sys.exit(1)
    except RuntimeError as e:
        print(f"\n❌ 运行时错误: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
