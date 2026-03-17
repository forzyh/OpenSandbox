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
Sandbox 服务的共享验证工具函数模块。

本模块提供了一系列验证函数，用于在容器运行时（Docker、Kubernetes）
执行请求验证，确保所有运行时在执行特定操作之前都强制执行相同的先决条件。

主要验证功能包括：
- 入口点验证：确保 sandbox 入口点有效
- 元数据标签验证：验证 metadata 键值对是否符合 Kubernetes 标签规则
- 过期时间验证：确保过期时间戳有效且在未来
- 端口验证：确保端口在有效范围内
- 超时验证：确保请求的 TTL 不超过配置的限制
- 卷验证：验证卷名称、挂载路径、子路径、主机路径、PVC 名称、OSSFS 配置等
- Egress 配置验证：确保在提供 network_policy 时配置了 egress.image
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Dict, List, Optional, Sequence

from fastapi import HTTPException, status
import re

from src.services.constants import RESERVED_LABEL_PREFIX, SandboxErrorCodes

if TYPE_CHECKING:
    from src.api.schema import NetworkPolicy, OSSFS, Volume
    from src.config import EgressConfig


def ensure_entrypoint(entrypoint: Sequence[str]) -> None:
    """
    确保 sandbox 入口点有效（至少包含一个命令）。

    Args:
        entrypoint: 入口点命令序列

    Raises:
        HTTPException: 当入口点为空时抛出 400 错误

    Examples:
        >>> ensure_entrypoint(["python", "app.py"])  # 不抛出异常
        >>> ensure_entrypoint([])  # 抛出 HTTPException
    """
    if not entrypoint:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": SandboxErrorCodes.INVALID_ENTRYPOINT,
                "message": "入口点必须至少包含一个命令。",
            },
        )


# ==================== Kubernetes 标签验证相关 ====================

# DNS 标签模式：小写字母数字开头和结尾，中间可包含连字符
DNS_LABEL_PATTERN = r"[a-z0-9]([-a-z0-9]*[a-z0-9])?"
# DNS 子域名正则：由 DNS 标签组成的点分隔字符串
DNS_SUBDOMAIN_RE = re.compile(rf"^(?:{DNS_LABEL_PATTERN}\.)*{DNS_LABEL_PATTERN}$")
# 标签名称正则：字母数字开头和结尾，可包含连字符、下划线、点
LABEL_NAME_RE = re.compile(r"^[A-Za-z0-9]([-A-Za-z0-9_.]*[A-Za-z0-9])?$")
# 标签值正则：可选的空字符串，或与标签名称相同的模式
LABEL_VALUE_RE = re.compile(r"^([A-Za-z0-9]([-A-Za-z0-9_.]*[A-Za-z0-9])?)?$")


def _is_valid_label_key(key: str) -> bool:
    """
    检查标签键是否符合 Kubernetes 标签规则。

    Kubernetes 标签键规则：
    - 可选前缀 + "/" + 名称
    - 前缀必须是有效的 DNS 子域名，最大 253 字符
    - 名称最大 63 字符，必须符合 LABEL_NAME_RE 模式

    Args:
        key: 标签键

    Returns:
        bool: 如果键有效返回 True，否则返回 False
    """
    if "/" in key:
        prefix, name = key.split("/", 1)
        if not prefix or not name:
            return False
        # Kubernetes 要求前缀是 DNS 子域名且最大 253 字符
        # 名称部分单独验证（最大 63 字符）
        if len(prefix) > 253:
            return False
        if not DNS_SUBDOMAIN_RE.match(prefix):
            return False
    else:
        name = key
    # 名称部分最大 63 字符
    if len(name) > 63 or not LABEL_NAME_RE.match(name):
        return False
    return True


def _is_valid_label_value(value: str) -> bool:
    """
    检查标签值是否符合 Kubernetes 标签规则。

    Kubernetes 标签值规则：
    - 最大 63 字符
    - 可为空字符串
    - 必须符合 LABEL_VALUE_RE 模式

    Args:
        value: 标签值

    Returns:
        bool: 如果值有效返回 True，否则返回 False
    """
    if len(value) > 63:
        return False
    return bool(LABEL_VALUE_RE.match(value))


def ensure_metadata_labels(metadata: Optional[Dict[str, str]]) -> None:
    """
    验证 metadata 键值对是否符合 Kubernetes 标签规则。

    验证逻辑：
    1. 键和值必须都是字符串
    2. 键不能使用系统保留前缀（opensandbox.io/）
    3. 键必须符合 Kubernetes 标签键规则
    4. 值必须符合 Kubernetes 标签值规则

    Args:
        metadata: 元数据字典

    Raises:
        HTTPException: 当键值对无效时抛出 400 错误
    """
    if not metadata:
        return
    for key, value in metadata.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": SandboxErrorCodes.INVALID_METADATA_LABEL,
                    "message": "元数据键和值必须是字符串。",
                },
            )
        # 检查是否使用保留前缀
        if key.startswith(RESERVED_LABEL_PREFIX):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": SandboxErrorCodes.INVALID_METADATA_LABEL,
                    "message": (
                        f"元数据键 '{key}' 使用了保留前缀 '{RESERVED_LABEL_PREFIX}'。"
                        "该前缀下的键由系统管理，不能通过 metadata 设置。"
                    ),
                },
            )
        # 验证键格式
        if not _is_valid_label_key(key):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": SandboxErrorCodes.INVALID_METADATA_LABEL,
                    "message": f"元数据键 '{key}' 不是有效的 Kubernetes 标签键。",
                },
            )
        # 验证值格式
        if not _is_valid_label_value(value):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": SandboxErrorCodes.INVALID_METADATA_LABEL,
                    "message": f"元数据值 '{value}' 不是有效的 Kubernetes 标签值。",
                },
            )


def ensure_future_expiration(expires_at: datetime) -> datetime:
    """
    验证并规范化过期时间戳为 UTC 时区。

    Args:
        expires_at: 请求的过期时间（时区感知或 naive datetime）

    Returns:
        datetime: 规范化后的 UTC 过期时间戳

    Raises:
        HTTPException: 当时间戳不是未来时间时抛出 400 错误

    处理逻辑：
        1. 如果输入是 naive datetime（无时区信息），假设为 UTC
        2. 转换为 UTC 时区
        3. 检查是否在未来，如果不是则抛出异常
    """
    if expires_at.tzinfo is None:
        # 无时区信息，假设为 UTC
        normalized = expires_at.replace(tzinfo=timezone.utc)
    else:
        # 转换为 UTC 时区
        normalized = expires_at.astimezone(timezone.utc)

    if normalized <= datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": SandboxErrorCodes.INVALID_EXPIRATION,
                "message": "新的过期时间必须是未来时间。",
            },
        )

    return normalized


def ensure_valid_port(port: int) -> None:
    """
    验证端口是否在有效范围内（1-65535）。

    Args:
        port: 端口号

    Raises:
        HTTPException: 当端口超出范围时抛出 400 错误
    """
    if port < 1 or port > 65535:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": SandboxErrorCodes.INVALID_PORT,
                "message": "端口必须在 1 到 65535 之间。",
            },
        )


def ensure_timeout_within_limit(timeout_seconds: Optional[int], max_timeout_seconds: Optional[int]) -> None:
    """
    验证请求的 sandbox TTL（存活时间）不超过配置的限制。

    Args:
        timeout_seconds: 请求的 sandbox TTL（秒），None 表示手动清理模式
        max_timeout_seconds: 配置的最大 TTL（秒），None 表示禁用限制

    Raises:
        HTTPException: 当超时超过配置的最大值时抛出 400 错误

    处理逻辑：
        1. 如果 timeout_seconds 为 None，直接返回（手动清理模式）
        2. 计算过期时间，验证是否会溢出
        3. 如果 max_timeout_seconds 为 None，不限制
        4. 检查是否超过最大限制
    """
    if timeout_seconds is None:
        return

    # 验证超时值是否会导致 datetime 溢出
    calculate_expiration_or_raise(datetime.now(timezone.utc), timeout_seconds)

    if max_timeout_seconds is None:
        return

    if timeout_seconds > max_timeout_seconds:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": SandboxErrorCodes.INVALID_PARAMETER,
                "message": (
                    f"Sandbox 超时 {timeout_seconds}秒 超过了配置的最大值 "
                    f"{max_timeout_seconds}秒。"
                ),
            },
        )


def calculate_expiration_or_raise(created_at: datetime, timeout_seconds: int) -> datetime:
    """
    计算过期时间戳，将 datetime 溢出错误转换为 400 错误。

    Args:
        created_at: 创建时间
        timeout_seconds: 超时秒数

    Returns:
        datetime: 过期时间戳

    Raises:
        HTTPException: 当超时值太大无法安全表示时抛出 400 错误

    注意：Python 的 datetime 有最大值限制，过大的超时值可能导致 OverflowError
    """
    try:
        return created_at + timedelta(seconds=timeout_seconds)
    except (OverflowError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": SandboxErrorCodes.INVALID_PARAMETER,
                "message": (
                    f"Sandbox 超时 {timeout_seconds}秒 太大，无法安全表示。"
                ),
            },
        ) from exc


# ==================== 卷验证相关 ====================

# 卷名称正则：必须是有效的 DNS 标签（小写字母数字，可包含连字符）
VOLUME_NAME_RE = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")
# Kubernetes 资源名称正则：与卷名称相同
K8S_RESOURCE_NAME_RE = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")


def ensure_valid_volume_name(name: str) -> None:
    """
    验证卷名称是否是有效的 DNS 标签。

    DNS 标签规则：
    - 只能包含小写字母、数字和连字符
    - 必须以字母或数字开头和结尾
    - 最大长度 63 字符

    Args:
        name: 卷名称

    Raises:
        HTTPException: 当名称无效时抛出 400 错误
    """
    if not name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": SandboxErrorCodes.INVALID_VOLUME_NAME,
                "message": "卷名称不能为空。",
            },
        )
    if len(name) > 63:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": SandboxErrorCodes.INVALID_VOLUME_NAME,
                "message": f"卷名称 '{name}' 超过最大长度 63 字符。",
            },
        )
    if not VOLUME_NAME_RE.match(name):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": SandboxErrorCodes.INVALID_VOLUME_NAME,
                "message": f"卷名称 '{name}' 不是有效的 DNS 标签。必须是小写字母数字，可包含连字符。",
            },
        )


def ensure_valid_mount_path(mount_path: str) -> None:
    """
    验证挂载路径是否是绝对路径。

    Args:
        mount_path: 挂载路径

    Raises:
        HTTPException: 当路径不是绝对路径时抛出 400 错误
    """
    if not mount_path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": SandboxErrorCodes.INVALID_MOUNT_PATH,
                "message": "挂载路径不能为空。",
            },
        )
    if not mount_path.startswith("/"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": SandboxErrorCodes.INVALID_MOUNT_PATH,
                "message": f"挂载路径 '{mount_path}' 必须是绝对路径，以 '/' 开头。",
            },
        )


def ensure_valid_sub_path(sub_path: Optional[str]) -> None:
    """
    验证子路径不包含路径遍历或是绝对路径。

    Args:
        sub_path: 子路径（可选）

    Raises:
        HTTPException: 当子路径无效时抛出 400 错误

    验证规则：
        - 空字符串有效（表示无子路径）
        - 不能是绝对路径（以 / 开头）
        - 不能包含路径遍历（..）
    """
    if sub_path is None:
        return

    if not sub_path:
        # 空字符串有效（表示无子路径）
        return

    # 检查是否为绝对路径
    if sub_path.startswith("/"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": SandboxErrorCodes.INVALID_SUB_PATH,
                "message": f"子路径 '{sub_path}' 必须是相对路径，不能是绝对路径。",
            },
        )

    # 检查是否包含路径遍历
    parts = sub_path.split("/")
    for part in parts:
        if part == "..":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": SandboxErrorCodes.INVALID_SUB_PATH,
                    "message": f"子路径 '{sub_path}' 包含路径遍历 '..'，这是不允许的。",
                },
            )


def ensure_valid_host_path(
    path: str,
    allowed_prefixes: Optional[List[str]] = None,
) -> None:
    """
    验证主机路径是否是绝对路径，且（可选）在允许的前缀列表中。

    Args:
        path: 主机路径
        allowed_prefixes: 允许的路径前缀列表（可选）

    Raises:
        HTTPException: 当路径无效或不被允许时抛出 400 错误

    验证规则：
        1. 路径不能为空
        2. 必须是绝对路径
        3. 不能包含路径遍历组件（..）
        4. 不能包含非规范化路径（双斜杠、尾随斜杠）
        5. 如果提供了 allowed_prefixes，路径必须在某个前缀下
    """
    if not path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": SandboxErrorCodes.INVALID_HOST_PATH,
                "message": "主机路径不能为空。",
            },
        )

    if not os.path.isabs(path):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": SandboxErrorCodes.INVALID_HOST_PATH,
                "message": f"主机路径 '{path}' 必须是绝对路径。",
            },
        )

    # 规范化分隔符为正斜杠以便进行一致的安全检查
    # 移除盘符前缀（如 "C:"），避免误检
    _drive, _tail = os.path.splitdrive(path)
    _tail_fwd = _tail.replace("\\", "/")

    # 拒绝路径遍历组件
    if "/.." in _tail_fwd or _tail_fwd == "/..":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": SandboxErrorCodes.INVALID_HOST_PATH,
                "message": f"主机路径 '{path}' 包含路径遍历组件 '..'。",
            },
        )

    # 拒绝非规范化路径（双斜杠、尾随斜杠，根目录除外）
    if "//" in _tail_fwd or (len(_tail_fwd) > 1 and _tail_fwd.endswith("/")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": SandboxErrorCodes.INVALID_HOST_PATH,
                "message": f"主机路径 '{path}' 未规范化。请移除多余的斜杠。",
            },
        )

    # 检查是否在允许的前缀列表中
    if allowed_prefixes is not None:
        norm_path = os.path.normpath(path)
        is_allowed = any(
            norm_path == os.path.normpath(prefix)
            or norm_path.startswith(os.path.normpath(prefix) + os.sep)
            for prefix in allowed_prefixes
        )
        if not is_allowed:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": SandboxErrorCodes.HOST_PATH_NOT_ALLOWED,
                    "message": f"主机路径 '{path}' 不在任何允许的前缀下。允许的前缀：{allowed_prefixes}",
                },
            )


def ensure_valid_pvc_name(claim_name: str) -> None:
    """
    验证 PVC 声明名称是否是有效的 Kubernetes 资源名称。

    Kubernetes 资源名称规则：
    - 只能包含小写字母、数字和连字符
    - 必须以字母或数字开头和结尾
    - 最大长度 253 字符

    Args:
        claim_name: PVC 声明名称

    Raises:
        HTTPException: 当名称无效时抛出 400 错误
    """
    if not claim_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": SandboxErrorCodes.INVALID_PVC_NAME,
                "message": "PVC 声明名称不能为空。",
            },
        )
    if len(claim_name) > 253:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": SandboxErrorCodes.INVALID_PVC_NAME,
                "message": f"PVC 声明名称 '{claim_name}' 超过最大长度 253 字符。",
            },
        )
    if not K8S_RESOURCE_NAME_RE.match(claim_name):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": SandboxErrorCodes.INVALID_PVC_NAME,
                "message": f"PVC 声明名称 '{claim_name}' 不是有效的 Kubernetes 资源名称。",
            },
        )


def ensure_valid_ossfs_volume(ossfs: "OSSFS") -> None:
    """
    验证 OSSFS 后端配置字段。

    验证规则：
        1. Bucket 名称不能为空
        2. Endpoint 不能为空
        3. Options 必须是有效的字符串列表（不能以 '-' 开头）
        4. 必须提供访问凭证（accessKeyId 和 accessKeySecret）

    Args:
        ossfs: OSSFS 后端模型

    Raises:
        HTTPException: 当任何 OSSFS 字段无效时抛出 400 错误
    """
    # 验证 Bucket 名称
    if not isinstance(ossfs.bucket, str) or not ossfs.bucket.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": SandboxErrorCodes.INVALID_OSSFS_BUCKET,
                "message": "OSSFS Bucket 不能为空。",
            },
        )

    # 验证 Endpoint
    if not ossfs.endpoint.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": SandboxErrorCodes.INVALID_OSSFS_ENDPOINT,
                "message": "OSSFS Endpoint 不能为空。",
            },
        )

    # 验证 Options
    if ossfs.options is not None:
        for opt in ossfs.options:
            if not isinstance(opt, str) or not opt.strip():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "code": SandboxErrorCodes.INVALID_OSSFS_OPTION,
                        "message": "OSSFS Options 必须是非空字符串。",
                    },
                )
            normalized = opt.strip()
            # Options 应该是原始配置值，不能带 '-' 前缀
            if normalized.startswith("-"):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "code": SandboxErrorCodes.INVALID_OSSFS_OPTION,
                        "message": (
                            "OSSFS Options 必须是原始配置值，不能带 '-' 前缀 "
                            "（例如：'allow_other', 'uid=1000'）。"
                        ),
                    },
                )

    # 验证凭证
    if not ossfs.access_key_id or not ossfs.access_key_secret:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": SandboxErrorCodes.INVALID_OSSFS_CREDENTIALS,
                "message": (
                    "OSSFS 需要内联凭证："
                    "必须提供 accessKeyId 和 accessKeySecret。"
                ),
            },
        )


def ensure_egress_configured(
    network_policy: Optional["NetworkPolicy"],
    egress_config: Optional["EgressConfig"],
) -> None:
    """
    验证在提供 network_policy 时是否配置了 egress.image。

    这是 Docker 和 Kubernetes 运行时共享的通用验证。

    Args:
        network_policy: 请求中的网络策略（可选）
        egress_config: 应用配置中的 egress 配置（可选）

    Raises:
        HTTPException: 当提供了 network_policy 但未配置 egress.image 时抛出 400 错误
    """
    if not network_policy:
        return

    egress_image = egress_config.image if egress_config else None
    if not egress_image:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": SandboxErrorCodes.INVALID_PARAMETER,
                "message": "提供 networkPolicy 时必须配置 egress.image。",
            },
        )


def ensure_volumes_valid(
    volumes: Optional[List["Volume"]],
    allowed_host_prefixes: Optional[List[str]] = None,
) -> None:
    """
    验证卷列表定义。

    本函数执行全面的卷验证：
    - 卷名称唯一性
    - 每个卷只能指定一个后端
    - 挂载路径有效性
    - 子路径有效性
    - 后端特定验证（主机路径、PVC 名称、OSSFS 配置）

    Args:
        volumes: 要验证的卷列表（可选）
        allowed_host_prefixes: 允许的主机路径前缀列表（可选）

    Raises:
        HTTPException: 当任何验证失败时抛出 400 错误
    """
    if volumes is None or len(volumes) == 0:
        return

    # 检查卷名称重复
    seen_names: set[str] = set()
    for volume in volumes:
        if volume.name in seen_names:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": SandboxErrorCodes.DUPLICATE_VOLUME_NAME,
                    "message": f"卷名称 '{volume.name}' 重复。每个卷必须有唯一的名称。",
                },
            )
        seen_names.add(volume.name)

        # 验证卷名称
        ensure_valid_volume_name(volume.name)

        # 验证挂载路径
        ensure_valid_mount_path(volume.mount_path)

        # 验证子路径
        ensure_valid_sub_path(volume.sub_path)

        # 计算已指定的后端数量
        backends_specified = sum([
            volume.host is not None,
            volume.pvc is not None,
            volume.ossfs is not None,
        ])

        if backends_specified == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": SandboxErrorCodes.INVALID_VOLUME_BACKEND,
                    "message": (
                        f"卷 '{volume.name}' 必须指定一个后端 "
                        "（host、pvc 或 ossfs），但未提供。"
                    ),
                },
            )

        if backends_specified > 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": SandboxErrorCodes.INVALID_VOLUME_BACKEND,
                    "message": (
                        f"卷 '{volume.name}' 只能指定一个后端 "
                        "（host、pvc 或 ossfs），但提供了多个。"
                    ),
                },
            )

        # 后端特定验证
        if volume.host is not None:
            ensure_valid_host_path(volume.host.path, allowed_host_prefixes)

        if volume.pvc is not None:
            ensure_valid_pvc_name(volume.pvc.claim_name)

        if volume.ossfs is not None:
            ensure_valid_ossfs_volume(volume.ossfs)


__all__ = [
    "ensure_entrypoint",
    "ensure_future_expiration",
    "ensure_valid_port",
    "ensure_metadata_labels",
    "ensure_egress_configured",
    "ensure_valid_volume_name",
    "ensure_valid_mount_path",
    "ensure_valid_sub_path",
    "ensure_valid_host_path",
    "ensure_valid_pvc_name",
    "ensure_valid_ossfs_volume",
    "ensure_volumes_valid",
]
