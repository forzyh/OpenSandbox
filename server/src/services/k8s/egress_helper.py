# Copyright 2026 Alibaba Group Holding Ltd.
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
Kubernetes 工作负载的 Egress 侧车容器辅助函数模块。

本模块提供了用于构建 Egress 侧车容器和相关配置的共享工具函数，
可被不同的工作负载提供者（WorkloadProvider）复用。

Egress 侧车用于：
- 实现网络策略（NetworkPolicy）
- 控制沙箱容器的出站流量
- 通过 iptables 规则限制访问目标

当提供 network_policy 时，会自动添加 egress 侧车容器到 Pod 中。
侧车容器需要 NET_ADMIN 权限来管理 iptables 规则。

使用示例：
    >>> pod_spec = {"containers": [main_container], "volumes": [...]}
    >>> containers = [main_container_dict]
    >>> apply_egress_to_spec(
    ...     pod_spec=pod_spec,
    ...     containers=containers,
    ...     network_policy=network_policy,
    ...     egress_image="opensandbox/egress:v1.0.3"
    ... )
"""

import json
from typing import Dict, Any, List, Optional

from src.api.schema import NetworkPolicy

# 传递给 egress 侧车的网络策略环境变量名
EGRESS_RULES_ENV = "OPENSANDBOX_EGRESS_RULES"


def build_egress_sidecar_container(
    egress_image: str,
    network_policy: NetworkPolicy,
) -> Dict[str, Any]:
    """
    为 Kubernetes Pod 构建 egress 侧车容器规格。

    本函数创建一个容器规格，可以添加到 Pod 的 containers 列表中。
    侧车容器将：
    - 运行 egress 镜像
    - 通过 OPENSANDBOX_EGRESS_RULES 环境变量接收网络策略
    - 具有 NET_ADMIN 权限以管理 iptables

    注意：在 Kubernetes 中，同一 Pod 中的容器共享网络命名空间，
    因此主容器可以通过 localhost 访问侧车的端口（44772 用于 execd，8080 用于 HTTP），
    无需显式声明端口。

    重要：IPv6 应该在 Pod 级别（而非容器级别）使用 build_ipv6_disable_sysctls()
    禁用，并将结果添加到 Pod 的 securityContext.sysctls 中。

    Args:
        egress_image: Egress 侧车的容器镜像
        network_policy: 要执行的网络策略配置

    Returns:
        Dict: 包含与 Kubernetes Pod 规格兼容的容器规格
              该字典可以直接添加到 Pod 的 containers 列表中

    Examples:
        >>> sidecar = build_egress_sidecar_container(
        ...     egress_image="opensandbox/egress:v1.0.3",
        ...     network_policy=NetworkPolicy(
        ...         default_action="deny",
        ...         egress=[NetworkRule(action="allow", target="pypi.org")]
        ...     )
        ... )
        >>> pod_spec["containers"].append(sidecar)
        >>>
        >>> # 在 Pod 级别禁用 IPv6（扩展现有 sysctls）
        >>> if "securityContext" not in pod_spec:
        ...     pod_spec["securityContext"] = {}
        >>> existing_sysctls = pod_spec["securityContext"].get("sysctls")
        >>> new_sysctls = build_ipv6_disable_sysctls()
        >>> pod_spec["securityContext"]["sysctls"] = _merge_sysctls(
        ...     existing_sysctls, new_sysctls
        ... )
    """
    # 将网络策略序列化为 JSON，用于环境变量
    policy_payload = json.dumps(
        network_policy.model_dump(by_alias=True, exclude_none=True)
    )

    # 构建容器规格
    container_spec: Dict[str, Any] = {
        "name": "egress",
        "image": egress_image,
        "env": [
            {
                "name": EGRESS_RULES_ENV,
                "value": policy_payload,
            }
        ],
        "securityContext": _build_security_context_for_egress(),
    }

    return container_spec


def _build_security_context_for_egress() -> Dict[str, Any]:
    """
    为 egress 侧车容器构建安全上下文。

    Egress 侧车需要 NET_ADMIN 权限来管理 iptables 规则，
    以执行网络策略。

    这是 build_egress_sidecar_container() 使用的内部辅助函数。

    Returns:
        Dict: 包含 NET_ADMIN 权限的安全上下文配置
    """
    return {
        "capabilities": {
            "add": ["NET_ADMIN"],  # 添加 NET_ADMIN 权限
        },
    }


def build_security_context_for_sandbox_container(
    has_network_policy: bool,
) -> Dict[str, Any]:
    """
    为主沙箱容器构建安全上下文。

    当启用网络策略时，主容器应该丢弃 NET_ADMIN 权限，
    以防止其修改网络配置。只有 egress 侧车应该具有 NET_ADMIN。

    Args:
        has_network_policy: 此 sandbox 是否启用了网络策略

    Returns:
        Dict: 安全上下文配置。如果 has_network_policy 为 True，
              包含 NET_ADMIN 在 drop 列表中；否则返回空字典
    """
    if not has_network_policy:
        return {}

    return {
        "capabilities": {
            "drop": ["NET_ADMIN"],  # 丢弃 NET_ADMIN 权限
        },
    }


def _merge_sysctls(
    existing_sysctls: Optional[List[Dict[str, str]]],
    new_sysctls: List[Dict[str, str]],
) -> List[Dict[str, str]]:
    """
    将新的 sysctls 合并到现有的 sysctls 中，避免重复。

    如果已存在同名的 sysctl，新值将覆盖现有值（最后写入优先）。

    Args:
        existing_sysctls: 现有的 sysctls 列表或 None
        new_sysctls: 要合并的新 sysctls

    Returns:
        List[Dict[str, str]]: 合并后的 sysctls 列表，无重复名称

    Examples:
        >>> existing = [{"name": "net.ipv4.ip_forward", "value": "0"}]
        >>> new = build_ipv6_disable_sysctls()
        >>> merged = _merge_sysctls(existing, new)
    """
    if not existing_sysctls:
        return new_sysctls.copy()

    # 创建字典以按名称跟踪 sysctls（用于去重）
    sysctls_dict: Dict[str, str] = {}

    # 首先添加现有的 sysctls
    for sysctl in existing_sysctls:
        if isinstance(sysctl, dict) and "name" in sysctl:
            sysctls_dict[sysctl["name"]] = sysctl.get("value", "")

    # 然后添加/覆盖新的 sysctls
    for sysctl in new_sysctls:
        if isinstance(sysctl, dict) and "name" in sysctl:
            sysctls_dict[sysctl["name"]] = sysctl.get("value", "")

    # 转换回列表格式
    return [{"name": name, "value": value} for name, value in sysctls_dict.items()]


def apply_egress_to_spec(
    pod_spec: Dict[str, Any],
    containers: List[Dict[str, Any]],
    network_policy: Optional[NetworkPolicy],
    egress_image: Optional[str],
) -> None:
    """
    将 egress 侧车配置应用到 Pod 规格。

    本函数将 egress 侧车容器添加到 containers 列表中，
    并在提供网络策略时在 Pod 级别配置 IPv6 禁用 sysctls。
    现有的 sysctls 会被保留并与新的 sysctls 合并。

    Args:
        pod_spec: Pod 规格字典（原地修改）
        containers: 容器字典列表（原地修改）
        network_policy: 可选的网络策略配置
        egress_image: 可选的 egress 侧车镜像

    Examples:
        >>> containers = [main_container_dict]
        >>> pod_spec = {"containers": containers, ...}
        >>>
        >>> apply_egress_to_spec(
        ...     pod_spec=pod_spec,
        ...     containers=containers,
        ...     network_policy=network_policy,
        ...     egress_image=egress_image,
        ... )

    注意:
        本函数扩展现有的 sysctls 而不是覆盖它们。
        如果已存在同名的 sysctl，egress 相关的 sysctls 将覆盖它（最后写入优先）。
    """
    if not network_policy or not egress_image:
        return

    # 构建并添加 egress 侧车容器
    sidecar_container = build_egress_sidecar_container(
        egress_image=egress_image,
        network_policy=network_policy,
    )
    containers.append(sidecar_container)

    # 在 Pod 级别禁用 IPv6，与现有的 sysctls 合并
    if "securityContext" not in pod_spec:
        pod_spec["securityContext"] = {}

    existing_sysctls = pod_spec["securityContext"].get("sysctls")
    new_sysctls = build_ipv6_disable_sysctls()
    pod_spec["securityContext"]["sysctls"] = _merge_sysctls(
        existing_sysctls, new_sysctls
    )


def build_security_context_from_dict(
    security_context_dict: Dict[str, Any],
) -> Optional[Any]:
    """
    将安全上下文字典转换为 V1SecurityContext 对象。

    这是辅助函数，用于将 build_security_context_for_sandbox_container()
    返回的字典转换为 Kubernetes V1SecurityContext 对象，
    可以在 V1Container 中使用。

    Args:
        security_context_dict: 安全上下文配置字典

    Returns:
        V1SecurityContext: Kubernetes 安全上下文对象，如果字典为空则返回 None

    Examples:
        >>> from kubernetes.client import V1Container
        >>>
        >>> security_context_dict = build_security_context_for_sandbox_container(True)
        >>> security_context = build_security_context_from_dict(security_context_dict)
        >>>
        >>> container = V1Container(
        ...     name="sandbox",
        ...     security_context=security_context,
        ... )
    """
    if not security_context_dict:
        return None

    from kubernetes.client import V1SecurityContext, V1Capabilities

    capabilities = None
    if "capabilities" in security_context_dict:
        caps_dict = security_context_dict["capabilities"]
        add_caps = caps_dict.get("add", [])
        drop_caps = caps_dict.get("drop", [])
        capabilities = V1Capabilities(
            add=add_caps if add_caps else None,
            drop=drop_caps if drop_caps else None,
        )

    return V1SecurityContext(capabilities=capabilities)


def serialize_security_context_to_dict(
    security_context: Optional[Any],
) -> Optional[Dict[str, Any]]:
    """
    将 V1SecurityContext 序列化为字典格式（用于 CRD）。

    本函数将 V1SecurityContext 对象（来自 V1Container）
    转换为字典格式，可用于 Kubernetes CRD 规格中。

    Args:
        security_context: V1SecurityContext 对象或 None

    Returns:
        Dict[str, Any]: 安全上下文的字典表示或 None

    Examples:
        >>> container_dict = {
        ...     "name": container.name,
        ...     "image": container.image,
        ... }
        >>>
        >>> if container.security_context:
        ...     container_dict["securityContext"] = serialize_security_context_to_dict(
        ...         container.security_context
        ...     )
    """
    if not security_context:
        return None

    result: Dict[str, Any] = {}

    if security_context.capabilities:
        caps: Dict[str, Any] = {}
        if security_context.capabilities.add:
            caps["add"] = security_context.capabilities.add
        if security_context.capabilities.drop:
            caps["drop"] = security_context.capabilities.drop
        if caps:
            result["capabilities"] = caps

    return result if result else None


def build_ipv6_disable_sysctls() -> list[Dict[str, str]]:
    """
    构建禁用 Pod 中 IPv6 的 sysctls 配置。

    当使用 egress 侧车时，应该在共享的网络命名空间中禁用 IPv6，
    以保持策略执行的一致性。这与 Docker 实现的行为相匹配。

    Returns:
        List[Dict[str, str]]: 在 Pod 级别禁用 IPv6 的 sysctl 配置列表

    注意:
        这些 sysctls 需要在 Pod 的 securityContext 级别设置，而不是
        容器级别。调用代码应该将此合并到 Pod 规格的 securityContext.sysctls 字段中。

    示例返回：
        [
            {"name": "net.ipv6.conf.all.disable_ipv6", "value": "1"},
            {"name": "net.ipv6.conf.default.disable_ipv6", "value": "1"},
            {"name": "net.ipv6.conf.lo.disable_ipv6", "value": "1"}
        ]
    """
    return [
        {"name": "net.ipv6.conf.all.disable_ipv6", "value": "1"},
        {"name": "net.ipv6.conf.default.disable_ipv6", "value": "1"},
        {"name": "net.ipv6.conf.lo.disable_ipv6", "value": "1"},
    ]
