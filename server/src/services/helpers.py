# Copyright 2025 Alibaba Group Holding Ltd.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Sandbox 服务的共享工具函数模块。

本模块提供了一系列通用工具函数，用于：
- 内存限制解析：将内存字符串（如 "512Mi"）转换为字节数
- CPU 限制解析：将 CPU 字符串（如 "500m"、"2"）转换为 nano_cpus
- 时间戳解析：解析 RFC3339 格式的时间戳
- URL 标准化：将主机名或 URL 标准化为完整 URL
- 过滤器匹配：应用状态/元数据过滤器到 sandbox 实例
- Ingress 端点格式化：构建基于 ingress 的端点字符串

这些工具函数被 Docker 和 Kubernetes 运行时共享使用，确保了行为的一致性。
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Dict, Optional

from src.api.schema import Endpoint, Sandbox, SandboxFilter
from src.services.constants import OPEN_SANDBOX_INGRESS_HEADER
from src.config import (
    GATEWAY_ROUTE_MODE_HEADER,
    GATEWAY_ROUTE_MODE_URI,
    GATEWAY_ROUTE_MODE_WILDCARD,
    INGRESS_MODE_GATEWAY,
    IngressConfig,
)

logger = logging.getLogger(__name__)

# ==================== 内存解析相关 ====================

# 内存限制解析正则表达式
# 匹配格式：数字 + 可选单位（如 "512Mi", "1Gi", "1024KB", "1000000"）
# 支持二进制单位（Ki, Mi, Gi, Ti）和十进制单位（K, M, G, T）
MEMORY_PATTERN = re.compile(r"^\s*(\d+)([kmgti]i?|[kmgti]?b)?\s*$", re.IGNORECASE)

# 内存单位乘数映射表
# 空字符串和 "b" 表示字节，乘数为 1
# "k"/"kb" 表示千字节（1000），"ki" 表示 kibibyte（1024）
# "m"/"mb" 表示兆字节（1000000），"mi" 表示 mebibyte（1024^2）
# 以此类推...
MEMORY_MULTIPLIERS: Dict[str, int] = {
    "": 1,
    "b": 1,
    "k": 1_000,
    "kb": 1_000,
    "ki": 1024,
    "m": 1_000_000,
    "mb": 1_000_000,
    "mi": 1024**2,
    "g": 1_000_000_000,
    "gb": 1_000_000_000,
    "gi": 1024**3,
    "t": 1_000_000_000_000,
    "tb": 1_000_000_000_000,
    "ti": 1024**4,
}


def parse_memory_limit(value: Optional[str]) -> Optional[int]:
    """
    将内存字符串转换为字节数。

    支持以下格式：
    - 纯数字：直接作为字节数（如 "1000000"）
    - 十进制单位：K/KB, M/MB, G/GB, T/TB（如 "512MB" = 512000000 字节）
    - 二进制单位：Ki, Mi, Gi, Ti（如 "512Mi" = 536870912 字节）

    Args:
        value: 内存限制字符串，如 "512Mi", "1Gi", "1024KB" 等

    Returns:
        int: 以字节为单位的内存限制值
        None: 如果输入为 None、空字符串或格式无效

    Examples:
        >>> parse_memory_limit("512Mi")
        536870912
        >>> parse_memory_limit("1Gi")
        1073741824
        >>> parse_memory_limit("1024KB")
        1024000
        >>> parse_memory_limit("invalid")
        None
    """
    if not value:
        return None
    match = MEMORY_PATTERN.match(value)
    if not match:
        logger.warning("内存限制格式无效 '%s'，将忽略此限制。", value)
        return None
    amount = int(match.group(1))
    unit = (match.group(2) or "").lower()
    multiplier = MEMORY_MULTIPLIERS.get(unit)
    if not multiplier:
        logger.warning("不支持的内存单位 '%s'，将忽略此限制。", unit)
        return None
    return amount * multiplier


def parse_nano_cpus(value: Optional[str]) -> Optional[int]:
    """
    将 CPU 字符串转换为 nano_cpus（十亿分之一 CPU）。

    支持以下格式：
    - 小数形式：如 "2" 表示 2 个 CPU，"0.5" 表示半个 CPU
    - 毫核形式：如 "500m" 表示 500 毫核 = 0.5 个 CPU
    - nano_cpus = CPU 数 * 1,000,000,000

    Args:
        value: CPU 限制字符串，如 "500m", "2", "0.5" 等

    Returns:
        int: nano_cpus 值（十亿分之一 CPU 为单位）
        None: 如果输入为 None、空字符串或格式无效

    Examples:
        >>> parse_nano_cpus("500m")
        500000000
        >>> parse_nano_cpus("2")
        2000000000
        >>> parse_nano_cpus("0.5")
        500000000
        >>> parse_nano_cpus("invalid")
        None
    """
    if not value:
        return None
    cpu_str = value.strip().lower()
    try:
        if cpu_str.endswith("m"):
            # 毫核形式：500m = 0.5 CPU
            cpus = float(cpu_str[:-1]) / 1000
        else:
            # 小数形式：2 = 2 CPU
            cpus = float(cpu_str)
    except ValueError:
        logger.warning("CPU 限制格式无效 '%s'，将忽略此限制。", value)
        return None
    if cpus <= 0:
        logger.warning("CPU 限制必须为正数。输入值为 '%s'，将忽略此限制。", value)
        return None
    return int(cpus * 1_000_000_000)


def parse_timestamp(timestamp: Optional[str]) -> datetime:
    """
    将 RFC3339 格式的时间戳解析为时区感知的 datetime 对象。

    Docker 通常返回 RFC3339Nano 格式（最多 9 位小数），而 Python 的
    datetime.fromisoformat 只支持微秒精度（6 位小数），因此需要截断
    小数部分到 6 位精度。

    Args:
        timestamp: RFC3339 格式的时间戳字符串，如 "2024-01-01T12:00:00Z"
                  或 "2024-01-01T12:00:00.123456789+08:00"

    Returns:
        datetime: 时区感知的 datetime 对象（UTC 时区）
                  如果输入为 None、空字符串或格式无效，返回当前时间

    Examples:
        >>> parse_timestamp("2024-01-01T12:00:00Z")
        datetime.datetime(2024, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)
        >>> parse_timestamp(None)
        datetime.datetime.now(timezone.utc)
    """
    if not timestamp or timestamp == "0001-01-01T00:00:00Z":
        return datetime.now(timezone.utc)

    normalized = timestamp
    # 将 Z 后缀转换为 +00:00 格式
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"

    # 处理小数部分（截断到 6 位微秒精度）
    if "." in normalized:
        main, rest = normalized.split(".", 1)
        tz_sep = None
        # 查找时区分隔符位置
        for sep in ("+", "-"):
            pos = rest.find(sep)
            if pos != -1:
                tz_sep = pos
                break
        if tz_sep is None:
            frac = rest
            tz = ""
        else:
            frac = rest[:tz_sep]
            tz = rest[tz_sep:]
        frac = frac[:6]  # 截断到微秒精度
        normalized = f"{main}.{frac}{tz}" if frac else f"{main}{tz}"

    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        logger.warning("时间戳格式无效 '%s'，将使用当前时间。", timestamp)
        return datetime.now(timezone.utc)


def normalize_external_endpoint_url(endpoint: str, default_scheme: str = "https") -> str:
    """
    将主机名或 URL 标准化为带有明确 scheme 的完整 URL。

    Args:
        endpoint: 端点字符串，可以是主机名（如 "example.com"）或完整 URL
        default_scheme: 默认 scheme，默认为 "https"

    Returns:
        str: 标准化的完整 URL

    Examples:
        >>> normalize_external_endpoint_url("https://example.com")
        'https://example.com'
        >>> normalize_external_endpoint_url("example.com")
        'https://example.com'
        >>> normalize_external_endpoint_url("http://example.com", "http")
        'http://example.com'
    """
    endpoint = endpoint.strip()
    if endpoint.startswith("http://") or endpoint.startswith("https://"):
        return endpoint
    return f"{default_scheme}://{endpoint}"


def matches_filter(sandbox: Sandbox, filter_: SandboxFilter) -> bool:
    """
    将状态/元数据过滤器应用到 sandbox 实例。

    Args:
        sandbox: Sandbox 对象
        filter_: 过滤器规范，包含状态和元数据过滤条件

    Returns:
        bool: 如果 sandbox 匹配所有过滤条件返回 True，否则返回 False

    过滤逻辑：
        - 如果不提供过滤器，返回 True（匹配所有）
        - 如果提供状态过滤，sandbox 状态必须在期望状态列表中
        - 如果提供元数据过滤，sandbox 元数据必须包含所有指定的键值对
    """
    if not filter_:
        return True
    if filter_.state:
        # 将期望状态转换为小写集合进行比较
        desired = {state.lower() for state in filter_.state}
        current_state = (sandbox.status.state or "").lower()
        if current_state not in desired:
            return False
    if filter_.metadata:
        # 检查所有元数据键值对是否匹配
        metadata = sandbox.metadata or {}
        for key, value in filter_.metadata.items():
            if metadata.get(key) != value:
                return False
    return True


# ============================================================================
# Ingress 端点格式化相关工具函数
# ============================================================================

def format_ingress_endpoint(
    ingress_config: Optional[IngressConfig],
    sandbox_id: str,
    port: int,
) -> Optional[Endpoint]:
    """
    为 sandbox 构建基于 ingress 的端点字符串。

    根据 ingress 配置的路由模式，返回不同类型的端点：
    - 通配符模式（WILDCARD）：返回 {sandbox_id}-{port}.{base_domain}
    - URI 模式（URI）：返回 {gateway_address}/{sandbox_id}/{port}
    - 请求头模式（HEADER）：返回 gateway_address，并在 headers 中包含 OpenSandbox-Ingress-To

    Args:
        ingress_config: Ingress 配置对象
        sandbox_id: Sandbox 唯一标识符
        port: 端口号

    Returns:
        Endpoint: 端点对象，包含 endpoint 和可选的 headers
        None: 如果 ingress 未配置或不是 gateway 模式

    Examples:
        通配符模式：sandbox-123-8080.example.com
        URI 模式：gateway.example.com/sandbox-123/8080
        请求头模式：gateway.example.com + {"OpenSandbox-Ingress-To": "sandbox-123-8080"}
    """
    if not ingress_config or ingress_config.mode != INGRESS_MODE_GATEWAY:
        return None
    gateway_cfg = ingress_config.gateway
    if gateway_cfg is None:
        return None

    address = gateway_cfg.address
    route_mode = gateway_cfg.route.mode

    if route_mode == GATEWAY_ROUTE_MODE_WILDCARD:
        # 通配符模式：移除 *.前缀，构造子域名
        base = address[2:] if address.startswith("*.") else address
        return Endpoint(endpoint=f"{sandbox_id}-{port}.{base}")

    if route_mode == GATEWAY_ROUTE_MODE_URI:
        # URI 模式：使用路径参数路由
        return Endpoint(endpoint=f"{address}/{sandbox_id}/{port}")

    if route_mode == GATEWAY_ROUTE_MODE_HEADER:
        # 请求头模式：使用自定义请求头传递目标信息
        header_value = f"{sandbox_id}-{port}"
        return Endpoint(
            endpoint=address,
            headers={OPEN_SANDBOX_INGRESS_HEADER: header_value},
        )

    raise RuntimeError(f"不支持的路由模式：{route_mode}")


__all__ = [
    "parse_memory_limit",
    "parse_nano_cpus",
    "parse_timestamp",
    "normalize_external_endpoint_url",
    "format_ingress_endpoint",
    "matches_filter",
]
