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
基于 kubernetes-sigs/agent-sandbox Sandbox CRD 的工作负载提供者实现。

本模块提供了 AgentSandboxProvider 类，用于通过 Agent-sandbox CRD 管理
sandbox 工作负载。Agent-sandbox 是 Kubernetes 上的一个 CRD，专门用于
管理 Agent 沙箱环境。

主要功能：
- 创建 Sandbox CRD 工作负载
- 获取/删除/列出 Sandbox 资源
- 更新过期时间
- 获取 sandbox 状态和端点信息
- 支持 DNS1035 标签名称转换
- 支持安全运行时（RuntimeClass）
- 支持 egress 侧车（网络策略）
- 支持 ingress 端点格式化

使用示例：
    >>> provider = AgentSandboxProvider(k8s_client, app_config)
    >>> workload_info = provider.create_workload(
    ...     sandbox_id="sandbox-123",
    ...     namespace="default",
    ...     image_spec=image_spec,
    ...     entrypoint=["python", "app.py"],
    ...     ...
    ... )
"""

import hashlib
import logging
import re
from datetime import datetime
from typing import Dict, List, Any, Optional

from kubernetes.client import (
    V1Container,
    V1EnvVar,
    V1ResourceRequirements,
    V1VolumeMount,
)

from src.config import AppConfig
from src.services.helpers import format_ingress_endpoint
from src.api.schema import Endpoint, ImageSpec, NetworkPolicy, Volume
from src.services.k8s.agent_sandbox_template import AgentSandboxTemplateManager
from src.services.k8s.client import K8sClient
from src.services.k8s.egress_helper import (
    apply_egress_to_spec,
    build_security_context_for_sandbox_container,
    build_security_context_from_dict,
    serialize_security_context_to_dict,
)
from src.services.k8s.volume_helper import apply_volumes_to_pod_spec
from src.services.k8s.workload_provider import WorkloadProvider
from src.services.runtime_resolver import SecureRuntimeResolver

logger = logging.getLogger(__name__)

# DNS1035 标签最大长度（Kubernetes 名称限制）
DNS1035_LABEL_MAX_LENGTH = 63
# DNS1035 无效字符模式（替换为连字符）
DNS1035_INVALID_CHARS = re.compile(r"[^a-z0-9-]+")
# DNS1035 重复连字符模式（压缩为单个连字符）
DNS1035_DUPLICATE_HYPHENS = re.compile(r"-+")


def _to_dns1035_label(value: str, prefix: str = "sandbox") -> str:
    """
    将任意字符串转换为有效的 DNS1035 标签。

    DNS1035 标签规则：
    - 只包含小写字母、数字和连字符
    - 必须以字母开头
    - 最大长度 63 字符

    转换逻辑：
    1. 替换无效字符为连字符
    2. 压缩重复连字符
    3. 确保以字母开头（必要时添加前缀）
    4. 如果超过最大长度，截断并添加哈希后缀

    Args:
        value: 要转换的字符串
        prefix: 当前缀需要添加时使用的字符串，默认 "sandbox"

    Returns:
        str: 有效的 DNS1035 标签

    Examples:
        >>> _to_dns1035_label("my-sandbox-123")
        'my-sandbox-123'
        >>> _to_dns1035_label("My_Sandbox@123")
        'my-sandbox-123-<hash>'
        >>> _to_dns1035_label("123-start")  # 以数字开头
        'sandbox-123-start-<hash>'
    """
    # 替换无效字符为连字符
    normalized = DNS1035_INVALID_CHARS.sub("-", value.strip().lower())
    # 压缩重复连字符
    normalized = DNS1035_DUPLICATE_HYPHENS.sub("-", normalized).strip("-")

    # 生成哈希后缀（用于保证唯一性和长度控制）
    hash_suffix = hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]

    if not normalized:
        # 空字符串，使用前缀和哈希
        normalized = f"{prefix}-{hash_suffix}"
    elif not normalized[0].isalpha():
        # 不以字母开头，添加前缀
        normalized = f"{prefix}-{normalized}"

    # 检查长度，必要时截断
    if len(normalized) > DNS1035_LABEL_MAX_LENGTH:
        max_base = DNS1035_LABEL_MAX_LENGTH - len(hash_suffix) - 1
        base = normalized[:max_base].rstrip("-")
        if not base or not base[0].isalpha():
            base = prefix
        normalized = f"{base}-{hash_suffix}"

    return normalized.strip("-")


class AgentSandboxProvider(WorkloadProvider):
    """
    使用 kubernetes-sigs/agent-sandbox Sandbox CRD 的工作负载提供者。

    该类实现了 WorkloadProvider 接口，专门用于管理 Agent-sandbox CRD 资源。

    特性：
    - 使用 Sandbox CRD 管理 sandbox 生命周期
    - 支持模板配置（通过 AgentSandboxTemplateManager）
    - 支持安全运行时（RuntimeClass）
    - 支持 egress 侧车（网络策略）
    - 支持 ingress 端点格式化
    - 自动处理 execd 初始化和引导

    Attributes:
        k8s_client: Kubernetes 客户端
        group/version/plural: CRD API 路径组件
        shutdown_policy: 关闭策略（默认 "Delete"）
        service_account: 服务账户（可选）
        template_manager: Sandbox 模板管理器
        ingress_config: Ingress 配置
        execd_init_resources: execd 初始化容器的资源限制
        resolver: 安全运行时解析器
        runtime_class: RuntimeClass 名称

    Examples:
        >>> provider = AgentSandboxProvider(k8s_client, app_config)
        >>> workload = provider.create_workload(...)
    """

    def __init__(
        self,
        k8s_client: K8sClient,
        app_config: Optional[AppConfig] = None,
    ):
        """
        初始化 AgentSandboxProvider。

        Args:
            k8s_client: Kubernetes 客户端包装器
            app_config: 应用配置；kubernetes/agent_sandbox/ingress 子配置
                       直接从该对象读取
        """
        self.k8s_client = k8s_client

        # CRD 路径组件
        self.group = "agents.x-k8s.io"
        self.version = "v1alpha1"
        self.plural = "sandboxes"

        k8s_config = app_config.kubernetes if app_config else None
        agent_config = app_config.agent_sandbox if app_config else None

        # 关闭策略（控制 Sandbox 删除时的行为）
        self.shutdown_policy = agent_config.shutdown_policy if agent_config else "Delete"
        # 服务账户（用于 Pod 身份）
        self.service_account = k8s_config.service_account if k8s_config else None
        # 模板管理器
        self.template_manager = AgentSandboxTemplateManager(
            agent_config.template_file if agent_config else None
        )
        # Ingress 配置（用于端点格式化）
        self.ingress_config = app_config.ingress if app_config else None
        # execd 初始化容器资源限制
        self.execd_init_resources = k8s_config.execd_init_resources if k8s_config else None

        # 初始化安全运行时解析器
        self.resolver = SecureRuntimeResolver(app_config) if app_config else None
        self.runtime_class = (
            self.resolver.get_k8s_runtime_class() if self.resolver else None
        )

    def _resource_name(self, sandbox_id: str) -> str:
        """
        将 sandbox_id 转换为资源名称（DNS1035 标签）。

        Args:
            sandbox_id: Sandbox 唯一标识符

        Returns:
            str: DNS1035 格式的资源名称
        """
        return _to_dns1035_label(sandbox_id, prefix="sandbox")

    def _resource_name_candidates(self, sandbox_id: str) -> List[str]:
        """
        生成用于查找 sandbox 的候选资源名称列表。

        为了向后兼容，会尝试多个名称格式：
        1. 转换后的 DNS1035 名称（主要）
        2. 原始 sandbox_id（如果不同）
        3. 遗留格式（sandbox-<id>）

        Args:
            sandbox_id: Sandbox 唯一标识符

        Returns:
            List[str]: 候选名称列表
        """
        candidates = []
        primary = self._resource_name(sandbox_id)
        candidates.append(primary)
        if sandbox_id not in candidates:
            candidates.append(sandbox_id)
        legacy = self.legacy_resource_name(sandbox_id)
        if legacy not in candidates:
            candidates.append(legacy)
        return candidates

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
        创建 Agent-sandbox Sandbox CRD 工作负载。

        Args:
            sandbox_id: Sandbox 唯一标识符
            namespace: Kubernetes 命名空间
            image_spec: 容器镜像规格
            entrypoint: 容器入口点命令
            env: 环境变量
            resource_limits: 资源限制
            labels: 要应用的标签
            expires_at: 过期时间
            execd_image: execd 守护进程镜像
            extensions: 扩展配置（可选）
            network_policy: 网络策略（可选）
            egress_image: Egress 侧车镜像（可选）
            volumes: 卷挂载列表（可选）

        Returns:
            Dict[str, Any]: 包含 'name' 和 'uid' 的字典

        Raises:
            ApiException: 如果创建失败
        """
        if self.runtime_class:
            logger.info(
                "为 sandbox %s 使用 Kubernetes RuntimeClass '%s'",
                sandbox_id,
                self.runtime_class,
            )

        # 构建 Pod 规格
        pod_spec = self._build_pod_spec(
            image_spec=image_spec,
            entrypoint=entrypoint,
            env=env,
            resource_limits=resource_limits,
            execd_image=execd_image,
            network_policy=network_policy,
            egress_image=egress_image,
        )

        # 添加用户指定的卷
        if volumes:
            apply_volumes_to_pod_spec(pod_spec, volumes)

        if self.service_account:
            pod_spec["serviceAccountName"] = self.service_account

        # 生成资源名称
        resource_name = self._resource_name(sandbox_id)

        # 构建运行时 manifest
        runtime_manifest = {
            "apiVersion": f"{self.group}/{self.version}",
            "kind": "Sandbox",
            "metadata": {
                "name": resource_name,
                "namespace": namespace,
                "labels": labels,
            },
            "spec": {
                "replicas": 1,
                "shutdownTime": expires_at.isoformat(),
                "shutdownPolicy": self.shutdown_policy,
                "podTemplate": {
                    "metadata": {
                        "labels": labels,
                    },
                    "spec": pod_spec,
                },
            },
        }

        # 与模板合并
        sandbox = self.template_manager.merge_with_runtime_values(runtime_manifest)

        # 创建 CRD 资源
        created = self.k8s_client.create_custom_object(
            group=self.group,
            version=self.version,
            namespace=namespace,
            plural=self.plural,
            body=sandbox,
        )

        return {
            "name": created["metadata"]["name"],
            "uid": created["metadata"]["uid"],
        }

    def _build_pod_spec(
        self,
        image_spec: ImageSpec,
        entrypoint: List[str],
        env: Dict[str, str],
        resource_limits: Dict[str, str],
        execd_image: str,
        network_policy: Optional[NetworkPolicy] = None,
        egress_image: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        为 Sandbox CRD 构建 Pod 规格字典。

        构建的 Pod 规格包含：
        - initContainer：用于安装 execd
        - main container：运行 sandbox 业务逻辑
        - volumes：共享卷（opensandbox-bin）
        - 可选的 egress 侧车（网络策略）
        - 可选的 runtimeClassName（安全运行时）

        Args:
            image_spec: 容器镜像规格
            entrypoint: 入口点命令
            env: 环境变量
            resource_limits: 资源限制
            execd_image: execd 镜像
            network_policy: 网络策略（可选）
            egress_image: Egress 镜像（可选）

        Returns:
            Dict[str, Any]: Pod 规格字典
        """
        init_container = self._build_execd_init_container(execd_image)
        main_container = self._build_main_container(
            image_spec=image_spec,
            entrypoint=entrypoint,
            env=env,
            resource_limits=resource_limits,
            include_execd_volume=True,
            has_network_policy=network_policy is not None,
        )

        containers = [self._container_to_dict(main_container)]

        # 构建基础 Pod 规格
        pod_spec: Dict[str, Any] = {
            "initContainers": [self._container_to_dict(init_container)],
            "containers": containers,
            "volumes": [
                {
                    "name": "opensandbox-bin",
                    "emptyDir": {},
                }
            ],
        }

        # 如果配置了安全运行时，注入 runtimeClassName
        if self.runtime_class:
            pod_spec["runtimeClassName"] = self.runtime_class

        # 如果提供了网络策略，添加 egress 侧车
        apply_egress_to_spec(
            pod_spec=pod_spec,
            containers=containers,
            network_policy=network_policy,
            egress_image=egress_image,
        )

        return pod_spec

    def _build_execd_init_container(self, execd_image: str) -> V1Container:
        """
        构建 execd 安装 init 容器。

        该 init 容器从 execd 镜像复制 execd 二进制和 bootstrap.sh 脚本
        到共享卷（opensandbox-bin），供主容器使用。

        Args:
            execd_image: execd 容器镜像

        Returns:
            V1Container: Init 容器规格
        """
        script = (
            "cp ./execd /opt/opensandbox/bin/execd && "
            "cp ./bootstrap.sh /opt/opensandbox/bin/bootstrap.sh && "
            "chmod +x /opt/opensandbox/bin/execd && "
            "chmod +x /opt/opensandbox/bin/bootstrap.sh"
        )

        resources = None
        if self.execd_init_resources:
            resources = V1ResourceRequirements(
                limits=self.execd_init_resources.limits,
                requests=self.execd_init_resources.requests,
            )

        return V1Container(
            name="execd-installer",
            image=execd_image,
            command=["/bin/sh", "-c"],
            args=[script],
            volume_mounts=[
                V1VolumeMount(
                    name="opensandbox-bin",
                    mount_path="/opt/opensandbox/bin",
                )
            ],
            resources=resources,
        )

    def _build_main_container(
        self,
        image_spec: ImageSpec,
        entrypoint: List[str],
        env: Dict[str, str],
        resource_limits: Dict[str, str],
        include_execd_volume: bool,
        has_network_policy: bool = False,
    ) -> V1Container:
        """
        构建主容器规格（带 execd 支持）。

        主容器使用 bootstrap.sh 脚本启动 execd 后台进程，然后执行用户命令。

        Args:
            image_spec: 容器镜像规格
            entrypoint: 入口点命令
            env: 环境变量
            resource_limits: 资源限制
            include_execd_volume: 是否包含 execd 卷挂载
            has_network_policy: 是否启用了网络策略

        Returns:
            V1Container: 主容器规格
        """
        # 转换环境变量
        env_vars = [V1EnvVar(name=k, value=v) for k, v in env.items()]
        # 注入 EXECD 环境变量，指定 execd 二进制路径
        env_vars.append(V1EnvVar(name="EXECD", value="/opt/opensandbox/bin/execd"))

        # 构建资源需求
        resources = None
        if resource_limits:
            resources = V1ResourceRequirements(
                limits=resource_limits,
                requests=resource_limits,  # requests=limits 保证 QoS
            )

        # 使用 bootstrap.sh 包装入口点
        wrapped_command = ["/opt/opensandbox/bin/bootstrap.sh"] + entrypoint

        # 构建卷挂载
        volume_mounts = None
        if include_execd_volume:
            volume_mounts = [
                V1VolumeMount(
                    name="opensandbox-bin",
                    mount_path="/opt/opensandbox/bin",
                )
            ]

        # 如果启用了网络策略，应用安全上下文
        security_context = None
        if has_network_policy:
            security_context_dict = build_security_context_for_sandbox_container(True)
            security_context = build_security_context_from_dict(security_context_dict)

        return V1Container(
            name="sandbox",
            image=image_spec.uri,
            command=wrapped_command,
            env=env_vars if env_vars else None,
            resources=resources,
            volume_mounts=volume_mounts,
            security_context=security_context,
        )

    def _container_to_dict(self, container: V1Container) -> Dict[str, Any]:
        """
        将 V1Container 对象转换为普通字典（用于 CRD body）。

        Args:
            container: V1Container 对象

        Returns:
            Dict[str, Any]: 容器字典表示
        """
        result: Dict[str, Any] = {
            "name": container.name,
            "image": container.image,
        }

        if container.command:
            result["command"] = container.command
        if container.args:
            result["args"] = container.args
        if container.env:
            result["env"] = [{"name": e.name, "value": e.value} for e in container.env]
        if container.resources:
            result["resources"] = {}
            if container.resources.limits:
                result["resources"]["limits"] = container.resources.limits
            if container.resources.requests:
                result["resources"]["requests"] = container.resources.requests
        if container.volume_mounts:
            result["volumeMounts"] = [
                {"name": vm.name, "mountPath": vm.mount_path}
                for vm in container.volume_mounts
            ]
        if container.security_context:
            security_context_dict = serialize_security_context_to_dict(container.security_context)
            if security_context_dict:
                result["securityContext"] = security_context_dict

        return result

    def get_workload(self, sandbox_id: str, namespace: str) -> Optional[Dict[str, Any]]:
        """
        按 sandbox ID 获取 Sandbox CRD，尝试所有候选资源名称。

        Args:
            sandbox_id: Sandbox 唯一标识符
            namespace: Kubernetes 命名空间

        Returns:
            Dict[str, Any]: Sandbox 资源对象
            None: 如果未找到
        """
        candidates = self._resource_name_candidates(sandbox_id)

        for name in candidates:
            workload = self.k8s_client.get_custom_object(
                group=self.group,
                version=self.version,
                namespace=namespace,
                plural=self.plural,
                name=name,
            )
            if workload:
                return workload

        return None

    def delete_workload(self, sandbox_id: str, namespace: str) -> None:
        """
        删除给定 sandbox ID 的 Sandbox CRD。

        Args:
            sandbox_id: Sandbox 唯一标识符
            namespace: Kubernetes 命名空间

        Raises:
            Exception: 如果 sandbox 未找到
        """
        sandbox = self.get_workload(sandbox_id, namespace)
        if not sandbox:
            raise Exception(f"sandbox {sandbox_id} 未找到")

        self.k8s_client.delete_custom_object(
            group=self.group,
            version=self.version,
            namespace=namespace,
            plural=self.plural,
            name=sandbox["metadata"]["name"],
            grace_period_seconds=0,
        )

    def list_workloads(self, namespace: str, label_selector: str) -> List[Dict[str, Any]]:
        """
        列出匹配标签选择器的 Sandbox CRD。

        Args:
            namespace: Kubernetes 命名空间
            label_selector: 标签选择器

        Returns:
            List[Dict[str, Any]]: Sandbox 资源列表
        """
        return self.k8s_client.list_custom_objects(
            group=self.group,
            version=self.version,
            namespace=namespace,
            plural=self.plural,
            label_selector=label_selector,
        )

    def update_expiration(self, sandbox_id: str, namespace: str, expires_at: datetime) -> None:
        """
        补丁 Sandbox CRD 的 shutdownTime 字段。

        Args:
            sandbox_id: Sandbox 唯一标识符
            namespace: Kubernetes 命名空间
            expires_at: 新的过期时间

        Raises:
            Exception: 如果 sandbox 未找到
        """
        sandbox = self.get_workload(sandbox_id, namespace)
        if not sandbox:
            raise Exception(f"sandbox {sandbox_id} 未找到")

        body = {
            "spec": {
                "shutdownTime": expires_at.isoformat(),
            }
        }

        self.k8s_client.patch_custom_object(
            group=self.group,
            version=self.version,
            namespace=namespace,
            plural=self.plural,
            name=sandbox["metadata"]["name"],
            body=body,
        )

    def get_expiration(self, workload: Dict[str, Any]) -> Optional[datetime]:
        """
        从 Sandbox CRD spec 解析 shutdownTime。

        Args:
            workload: Sandbox CRD 字典

        Returns:
            datetime: 过期时间
            None: 如果未设置或格式无效
        """
        spec = workload.get("spec", {})
        shutdown_time_str = spec.get("shutdownTime")

        if not shutdown_time_str:
            return None

        try:
            return datetime.fromisoformat(shutdown_time_str.replace("Z", "+00:00"))
        except (ValueError, TypeError) as e:
            logger.warning("shutdownTime 格式无效：%s，错误：%s", shutdown_time_str, e)
            return None

    def get_status(self, workload: Dict[str, Any]) -> Dict[str, Any]:
        """
        从 Sandbox CRD 状态条件派生 sandbox 状态。

        状态派生逻辑：
        - 检查 Ready 条件
        - 如果没有 Ready 条件，尝试从 Pod 列表解析状态
        - 根据条件状态和原因确定最终状态

        Args:
            workload: Sandbox CRD 字典

        Returns:
            Dict[str, Any]: 包含 state、reason、message、last_transition_at 的字典
        """
        status = workload.get("status", {})
        conditions = status.get("conditions", [])

        ready_condition = None
        for condition in conditions:
            if condition.get("type") == "Ready":
                ready_condition = condition
                break

        creation_timestamp = workload.get("metadata", {}).get("creationTimestamp")

        if not ready_condition:
            # 没有 Ready 条件，尝试从 Pod 解析状态
            pod_state = self._pod_state_from_selector(workload)
            if pod_state:
                state, reason, message = pod_state
                return {
                    "state": state,
                    "reason": reason,
                    "message": message,
                    "last_transition_at": creation_timestamp,
                }
            return {
                "state": "Pending",
                "reason": "SANDBOX_PENDING",
                "message": "Sandbox 正在等待调度",
                "last_transition_at": creation_timestamp,
            }

        cond_status = ready_condition.get("status")
        reason = ready_condition.get("reason")
        message = ready_condition.get("message")
        last_transition_at = ready_condition.get("lastTransitionTime") or creation_timestamp

        if cond_status == "True":
            state = "Running"
        elif reason == "SandboxExpired":
            state = "Terminated"
        elif cond_status == "False":
            state = "Pending"
        else:
            state = "Pending"

        return {
            "state": state,
            "reason": reason,
            "message": message,
            "last_transition_at": last_transition_at,
        }

    def _pod_state_from_selector(self, workload: Dict[str, Any]) -> Optional[tuple[str, str, str]]:
        """
        从标签选择器的 Pod 列表解析状态。

        返回三元素元组 (state, reason, message)：
        - Running: Pod 相位为 Running 且有 IP
        - Allocated: Pod 有 IP 但还未 Running
        - Pending: Pod 已调度但还没有 IP

        Args:
            workload: Sandbox CRD 字典

        Returns:
            tuple[str, str, str]: (状态，原因，消息)
            None: 如果选择器/命名空间缺失或 API 调用失败
        """
        status = workload.get("status", {})
        selector = status.get("selector")
        namespace = workload.get("metadata", {}).get("namespace")
        if not selector or not namespace:
            return None

        try:
            pods = self.k8s_client.list_pods(
                namespace=namespace,
                label_selector=selector,
            )
        except Exception:
            return None

        for pod in pods:
            if pod.status:
                if pod.status.pod_ip and pod.status.phase == "Running":
                    return (
                        "Running",
                        "POD_READY",
                        "Pod 正在运行且已分配 IP",
                    )
                if pod.status.pod_ip:
                    return (
                        "Allocated",
                        "IP_ASSIGNED",
                        "Pod 已分配 IP 但还未运行",
                    )
                return (
                    "Pending",
                    "POD_SCHEDULED",
                    "Pod 已调度但等待 IP 分配",
                )

        if pods:
            return ("Pending", "POD_PENDING", "Pod 正在等待")

        return None

    def get_endpoint_info(self, workload: Dict[str, Any], port: int, sandbox_id: str) -> Optional[Endpoint]:
        """
        从工作负载获取端点信息。
        - gateway 模式：使用 ingress 配置格式化端点
        - 直接/默认：从注解解析 Pod IP

        Args:
            workload: Sandbox CRD 字典
            port: 端口号
            sandbox_id: Sandbox 标识符

        Returns:
            Endpoint: 端点对象
            None: 如果端点不可用
        """
        # 如果配置了 gateway 模式，使用 ingress 端点
        ingress_endpoint = format_ingress_endpoint(self.ingress_config, sandbox_id, port)
        if ingress_endpoint:
            return ingress_endpoint

        # 尝试从 Pod 列表解析 IP
        status = workload.get("status", {})
        selector = status.get("selector")
        namespace = workload.get("metadata", {}).get("namespace")
        if selector and namespace:
            try:
                pods = self.k8s_client.list_pods(
                    namespace=namespace,
                    label_selector=selector,
                )
                for pod in pods:
                    if pod.status and pod.status.pod_ip and pod.status.phase == "Running":
                        return Endpoint(endpoint=f"{pod.status.pod_ip}:{port}")
            except Exception as e:
                logger.warning("解析 Pod 端点失败：%s", e)

        # 尝试从 serviceFQDN 获取
        service_fqdn = status.get("serviceFQDN")
        if service_fqdn:
            return Endpoint(endpoint=f"{service_fqdn}:{port}")

        return None
