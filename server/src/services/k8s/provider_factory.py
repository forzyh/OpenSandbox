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
WorkloadProvider 实例的工厂模块。

本模块提供了用于创建 WorkloadProvider 实例的工厂函数，支持：
- 根据配置的类型创建相应的提供者实例
- 注册自定义的提供者实现
- 列出所有可用的提供者类型

当前支持的提供者类型：
- batchsandbox：使用 BatchSandbox CRD 管理工作负载
- agent-sandbox：使用 Agent-sandbox CRD 管理工作负载

使用示例：
    >>> # 创建提供者实例
    >>> provider = create_workload_provider("batchsandbox", k8s_client, app_config)
    >>>
    >>> # 注册自定义提供者
    >>> register_provider("custom", CustomProvider)
    >>>
    >>> # 列出所有可用的提供者
    >>> providers = list_available_providers()
"""

import logging
from typing import Dict, Type, Optional

from src.config import AppConfig
from src.services.k8s.workload_provider import WorkloadProvider
from src.services.k8s.batchsandbox_provider import BatchSandboxProvider
from src.services.k8s.agent_sandbox_provider import AgentSandboxProvider
from src.services.k8s.client import K8sClient

logger = logging.getLogger(__name__)

# 提供者类型常量
PROVIDER_TYPE_BATCHSANDBOX = "batchsandbox"
PROVIDER_TYPE_AGENT_SANDBOX = "agent-sandbox"

# 已注册的提供者注册表
_PROVIDER_REGISTRY: Dict[str, Type[WorkloadProvider]] = {
    PROVIDER_TYPE_BATCHSANDBOX: BatchSandboxProvider,
    PROVIDER_TYPE_AGENT_SANDBOX: AgentSandboxProvider,
    # 未来的提供者可以在此注册：
    # "pod": PodProvider
}


def create_workload_provider(
    provider_type: str | None,
    k8s_client: K8sClient,
    app_config: Optional[AppConfig] = None,
) -> WorkloadProvider:
    """
    根据提供者类型创建 WorkloadProvider 实例。

    Args:
        provider_type: 提供者类型（如 'batchsandbox'、'pod'、'job'）
                      如果为 None，使用第一个注册的提供者
        k8s_client: Kubernetes 客户端实例
        app_config: 应用配置；kubernetes/agent_sandbox/ingress 子配置
                   直接从该对象读取

    Returns:
        WorkloadProvider: WorkloadProvider 实例

    Raises:
        ValueError: 如果 provider_type 不支持或没有注册任何提供者

    Examples:
        >>> # 指定类型创建
        >>> provider = create_workload_provider("batchsandbox", k8s_client, app_config)
        >>>
        >>> # 使用默认提供者（第一个注册的）
        >>> provider = create_workload_provider(None, k8s_client, app_config)
    """
    # 如果未指定，使用第一个注册的提供者
    if provider_type is None:
        if not _PROVIDER_REGISTRY:
            raise ValueError(
                "没有注册任何工作负载提供者。"
                "无法创建默认提供者。"
            )
        provider_type = next(iter(_PROVIDER_REGISTRY.keys()))
        logger.info(f"未指定提供者，使用默认：{provider_type}")

    provider_type_lower = provider_type.lower()

    if provider_type_lower not in _PROVIDER_REGISTRY:
        available = ", ".join(_PROVIDER_REGISTRY.keys())
        raise ValueError(
            f"不支持的工作负载提供者类型 '{provider_type}'。"
            f"可用的提供者：{available}"
        )

    provider_class = _PROVIDER_REGISTRY[provider_type_lower]
    logger.info(f"创建工作负载提供者：{provider_class.__name__}")

    # BatchSandboxProvider 和 AgentSandboxProvider 从 app_config 读取所有子配置
    if provider_type_lower in (PROVIDER_TYPE_BATCHSANDBOX, PROVIDER_TYPE_AGENT_SANDBOX):
        return provider_class(k8s_client, app_config=app_config)

    # 不接受 app_config 的提供者
    return provider_class(k8s_client)


def register_provider(name: str, provider_class: Type[WorkloadProvider]) -> None:
    """
    注册自定义的 WorkloadProvider 实现。

    这允许扩展系统以支持自定义的提供者实现，
    而无需修改核心代码。

    Args:
        name: 提供者名称（用于配置）
        provider_class: 实现 WorkloadProvider 接口的提供者类

    Raises:
        TypeError: 如果提供者类没有继承自 WorkloadProvider

    Examples:
        >>> from my_module import CustomProvider
        >>> register_provider("custom", CustomProvider)
        >>> # 现在可以使用 "custom" 类型创建提供者
        >>> provider = create_workload_provider("custom", k8s_client)
    """
    if not issubclass(provider_class, WorkloadProvider):
        raise TypeError(
            f"提供者类必须继承自 WorkloadProvider，"
            f"但得到了 {provider_class.__name__}"
        )

    name_lower = name.lower()
    if name_lower in _PROVIDER_REGISTRY:
        logger.warning(
            f"覆盖现有的提供者注册：{name_lower}"
        )

    _PROVIDER_REGISTRY[name_lower] = provider_class
    logger.info(f"注册了工作负载提供者：{name_lower} -> {provider_class.__name__}")


def list_available_providers() -> list[str]:
    """
    列出所有已注册的提供者类型。

    Returns:
        list[str]: 提供者类型名称的排序列表

    Examples:
        >>> providers = list_available_providers()
        >>> print(providers)
        ['agent-sandbox', 'batchsandbox']
    """
    return sorted(_PROVIDER_REGISTRY.keys())
