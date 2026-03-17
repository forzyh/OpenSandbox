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
Kubernetes 工作负载提供者的抽象接口模块。

本模块定义了 WorkloadProvider 抽象基类，为管理 Kubernetes 工作负载资源
提供了统一的接口。

设计目的：
- 支持不同的 K8s 资源类型（Pod、Job、StatefulSet、BatchSandbox 等）
- 通过统一接口隐藏底层资源类型的差异
- 便于扩展新的工作负载类型

实现该接口的提供者：
- BatchSandboxProvider：使用 BatchSandbox CRD
- AgentSandboxProvider：使用 Agent-sandbox CRD

使用示例：
    >>> provider = BatchSandboxProvider(k8s_client, app_config)
    >>> workload_info = provider.create_workload(...)
    >>> workload = provider.get_workload(sandbox_id, namespace)
    >>> status = provider.get_status(workload)
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Dict, List, Any, Optional

from src.api.schema import Endpoint, ImageSpec, NetworkPolicy, Volume


class WorkloadProvider(ABC):
    """
    管理 Kubernetes 工作负载资源的抽象接口。

    该抽象类允许系统支持不同的 K8s 资源类型
    （Pod、Job、StatefulSet 等），并使用统一的接口进行管理。

    实现类需要实现以下抽象方法：
    - create_workload: 创建工作负载
    - get_workload: 获取工作负载
    - delete_workload: 删除工作负载
    - list_workloads: 列出工作负载
    - update_expiration: 更新过期时间
    - get_expiration: 获取过期时间
    - get_status: 获取状态
    - get_endpoint_info: 获取端点信息

    可选重写的方法：
    - supports_image_auth: 是否支持镜像拉取认证
    - supports_manual_cleanup: 是否支持手动清理模式
    - legacy_resource_name: 遗留资源名称转换

    Examples:
        >>> class MyProvider(WorkloadProvider):
        ...     def create_workload(self, ...):
        ...         # 实现创建工作负载逻辑
        ...         pass
        ...     # 实现其他抽象方法
    """

    @abstractmethod
    def create_workload(
        self,
        sandbox_id: str,
        namespace: str,
        image_spec: ImageSpec,
        entrypoint: List[str],
        env: Dict[str, str],
        resource_limits: Dict[str, str],
        labels: Dict[str, str],
        expires_at: datetime,
        execd_image: str,
        extensions: Optional[Dict[str, str]] = None,
        network_policy: Optional[NetworkPolicy] = None,
        egress_image: Optional[str] = None,
        volumes: Optional[List[Volume]] = None,
    ) -> Dict[str, Any]:
        """
        创建新的工作负载资源。

        Args:
            sandbox_id: Sandbox 唯一标识符
            namespace: Kubernetes 命名空间
            image_spec: 容器镜像规格
            entrypoint: 容器入口点命令
            env: 环境变量
            resource_limits: 资源限制（cpu、memory）
            labels: 要应用到工作负载的标签
            expires_at: 过期时间
            execd_image: execd 守护进程镜像
            extensions: 用于传递额外配置的扩展字段
                       这是一个灵活字段，用于各种用例（如 ``poolRef`` 用于基于池的创建）
            network_policy: 用于出站流量控制的可选网络策略
                          提供时，会在 Pod 中添加 egress 侧车容器
            egress_image: 可选的 egress 侧车镜像。提供 network_policy 时需要
            volumes: 可选的 sandbox 卷挂载列表

        Returns:
            Dict[str, Any]: 包含工作负载元数据的字典（name、uid 等）

        Raises:
            ApiException: 如果创建失败
        """
        pass

    @abstractmethod
    def get_workload(self, sandbox_id: str, namespace: str) -> Optional[Any]:
        """
        按 sandbox ID 获取工作负载。

        Args:
            sandbox_id: Sandbox 唯一标识符
            namespace: Kubernetes 命名空间

        Returns:
            Any: 工作负载对象，如果未找到返回 None
        """
        pass

    @abstractmethod
    def delete_workload(self, sandbox_id: str, namespace: str) -> None:
        """
        删除工作负载资源。

        Args:
            sandbox_id: Sandbox 唯一标识符
            namespace: Kubernetes 命名空间

        Raises:
            ApiException: 如果删除失败
        """
        pass

    @abstractmethod
    def list_workloads(self, namespace: str, label_selector: str) -> List[Any]:
        """
        列出匹配标签选择器的工作负载。

        Args:
            namespace: Kubernetes 命名空间
            label_selector: 标签选择器查询

        Returns:
            List[Any]: 工作负载对象列表
        """
        pass

    @abstractmethod
    def update_expiration(self, sandbox_id: str, namespace: str, expires_at: datetime) -> None:
        """
        更新工作负载过期时间。

        Args:
            sandbox_id: Sandbox 唯一标识符
            namespace: Kubernetes 命名空间
            expires_at: 新的过期时间

        Raises:
            Exception: 如果更新失败
        """
        pass

    @abstractmethod
    def get_expiration(self, workload: Any) -> Optional[datetime]:
        """
        从工作负载获取过期时间。

        Args:
            workload: 工作负载对象

        Returns:
            datetime: 过期时间，如果未设置返回 None
        """
        pass

    @abstractmethod
    def get_status(self, workload: Any) -> Dict[str, Any]:
        """
        从工作负载对象获取状态。

        Args:
            workload: 工作负载对象

        Returns:
            Dict[str, Any]: 包含 state、reason、message、last_transition_at 的字典
        """
        pass

    @abstractmethod
    def get_endpoint_info(self, workload: Any, port: int, sandbox_id: str) -> Optional[Endpoint]:
        """
        从工作负载获取端点信息。

        Args:
            workload: 工作负载对象
            port: 端口号
            sandbox_id: Sandbox 标识符（用于基于 ingress 的端点）

        Returns:
            Endpoint: 端点对象（包含可选的 headers），如果不可用返回 None
        """
        pass

    def supports_image_auth(self) -> bool:
        """
        检查此提供者是否支持按请求的镜像拉取认证。

        实现了 imagePullSecrets 注入的提供者应该重写此方法返回 True。

        Returns:
            bool: 默认返回 False，支持镜像认证的提供者应返回 True
        """
        return False

    def supports_manual_cleanup(self) -> bool:
        """
        检查此提供者是否可以表示非过期的 sandbox。

        只有在验证了后端 CRD 语义安全支持省略过期字段后，
        提供者才应该重写此方法。

        Returns:
            bool: 默认返回 False，支持手动清理的提供者应返回 True
        """
        return False

    def legacy_resource_name(self, sandbox_id: str) -> str:
        """
        将 sandbox_id 转换为带前缀的遗留资源名称。

        升级前的 sandbox 命名为 ``sandbox-<id>``。此辅助函数在允许新
        sandbox 使用纯 ID 的同时，保留了对这些资源的访问。

        Args:
            sandbox_id: Sandbox 唯一标识符

        Returns:
            str: 如果 sandbox_id 已经以 "sandbox-" 开头，返回原值；
                否则返回 "sandbox-{sandbox_id}"

        Examples:
            >>> provider.legacy_resource_name("123")
            'sandbox-123'
            >>> provider.legacy_resource_name("sandbox-123")
            'sandbox-123'
        """
        if sandbox_id.startswith("sandbox-"):
            return sandbox_id
        return f"sandbox-{sandbox_id}"
