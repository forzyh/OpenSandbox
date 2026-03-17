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
基于 BatchSandbox CRD 的工作负载提供者实现。

本模块提供了 BatchSandboxProvider 类，用于通过 BatchSandbox CRD 管理
sandbox 工作负载。BatchSandbox 是 OpenSandbox 系统中的自定义资源定义，
用于管理批量任务沙箱。

主要功能：
- 创建 BatchSandbox CRD 工作负载
- 支持模板模式和池模式
- 获取/删除/列出 BatchSandbox 资源
- 更新过期时间
- 获取 sandbox 状态和端点信息
- 支持镜像拉取认证（imagePullSecrets）
- 支持安全运行时（RuntimeClass）
- 支持 egress 侧车（网络策略）
- 支持卷挂载

池模式说明：
    当 extensions 中包含 'poolRef' 时，启用池模式。池模式使用预热的
    资源池，只允许自定义 entrypoint 和 env，不支持 volumes。

使用示例：
    >>> provider = BatchSandboxProvider(k8s_client, app_config)
    >>> # 模板模式
    >>> workload_info = provider.create_workload(...)
    >>> # 池模式
    >>> workload_info = provider.create_workload(
    ...     extensions={"poolRef": "my-pool"},
    ...     entrypoint=["python", "app.py"],
    ...     env={"KEY": "value"}
    ... )
"""

import logging
import json
import shlex
from datetime import datetime
from typing import Dict, List, Any, Optional

from kubernetes.client import (
    V1Container,
    V1EnvVar,
    V1ResourceRequirements,
    V1VolumeMount,
)

from src.config import AppConfig, INGRESS_MODE_GATEWAY
from src.services.helpers import format_ingress_endpoint
from src.api.schema import Endpoint, ImageSpec, NetworkPolicy, Volume
from src.services.k8s.image_pull_secret_helper import (
    build_image_pull_secret,
    build_image_pull_secret_name,
)
from src.services.k8s.batchsandbox_template import BatchSandboxTemplateManager
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


class BatchSandboxProvider(WorkloadProvider):
    """
    使用 BatchSandbox CRD 的工作负载提供者。

    BatchSandbox 是一个自定义资源，用于管理 Pod 生命周期
    并提供额外功能，如任务管理和资源池支持。

    支持两种创建模式：
    - 模板模式（默认）：使用用户指定的镜像、资源和环境变量创建工作负载
    - 池模式（当 extensions 包含 'poolRef' 时）：从预热的资源池创建工作负载，
      只允许自定义 entrypoint 和 env

    特性：
    - 支持模板配置（通过 BatchSandboxTemplateManager）
    - 支持镜像拉取认证（imagePullSecrets）
    - 支持安全运行时（RuntimeClass）
    - 支持 egress 侧车（网络策略）
    - 支持卷挂载（PVC、hostPath）
    - 自动处理 execd 初始化和引导

    Attributes:
        k8s_client: Kubernetes 客户端包装器
        ingress_config: Ingress 配置
        group/version/plural: CRD API 路径组件
        template_manager: BatchSandbox 模板管理器
        resolver: 安全运行时解析器
        runtime_class: RuntimeClass 名称

    Examples:
        >>> provider = BatchSandboxProvider(k8s_client, app_config)
        >>> workload = provider.create_workload(...)
    """

    def __init__(
        self,
        k8s_client: K8sClient,
        app_config: Optional[AppConfig] = None,
    ):
        """
        初始化 BatchSandbox 提供者。

        Args:
            k8s_client: Kubernetes 客户端包装器
            app_config: 应用配置；kubernetes/ingress 子配置直接从该对象读取
        """
        self.k8s_client = k8s_client
        self.ingress_config = app_config.ingress if app_config else None

        k8s_config = app_config.kubernetes if app_config else None
        template_file_path = k8s_config.batchsandbox_template_file if k8s_config else None
        if template_file_path:
            logger.info("使用 BatchSandbox 模板文件：%s", template_file_path)
        self.execd_init_resources = k8s_config.execd_init_resources if k8s_config else None

        # 初始化安全运行时解析器
        self.resolver = SecureRuntimeResolver(app_config) if app_config else None
        self.runtime_class = (
            self.resolver.get_k8s_runtime_class() if self.resolver else None
        )

        # CRD 常量
        self.group = "sandbox.opensandbox.io"
        self.version = "v1alpha1"
        self.plural = "batchsandboxes"

        # 模板管理器
        self.template_manager = BatchSandboxTemplateManager(template_file_path)

    def supports_image_auth(self) -> bool:
        """
        BatchSandbox 支持通过 imagePullSecrets 注入进行镜像拉取认证。

        Returns:
            bool: 始终返回 True
        """
        return True

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
        创建 BatchSandbox 工作负载。

        支持两种创建模式：
        - 模板模式（默认）：使用用户指定的镜像、资源和环境变量创建工作负载
        - 池模式（当 extensions 包含 'poolRef' 时）：从预热的资源池创建工作负载，
          只允许自定义 entrypoint 和 env

        Args:
            sandbox_id: Sandbox 唯一标识符
            namespace: Kubernetes 命名空间
            image_spec: 容器镜像规格（池模式不使用）
            entrypoint: 容器入口点命令
            env: 环境变量
            resource_limits: 资源限制（池模式不使用）
            labels: 要应用的标签
            expires_at: 过期时间
            execd_image: execd 守护进程镜像（池模式不使用）
            extensions: 用于传递额外配置的扩展字段
                       当包含 'poolRef' 时，启用池模式
            network_policy: 用于出站流量控制的可选网络策略
                          提供时，会在 Pod 中添加 egress 侧车容器
            egress_image: Egress 侧车容器镜像（提供 network_policy 时需要）
            volumes: 可选的 sandbox 卷挂载列表

        Returns:
            Dict[str, Any]: 包含 'name' 和 'uid' 的字典

        Raises:
            ValueError: 如果池模式下提供了 volumes（不支持）
        """
        extensions = extensions or {}

        # 记录 RuntimeClass 使用情况（用于调试）
        if self.runtime_class:
            logger.info(
                "为 sandbox %s 使用 Kubernetes RuntimeClass '%s'",
                self.runtime_class,
                sandbox_id,
            )

        # 如果提供了 poolRef 且不为空，从池创建工作负载
        if extensions.get("poolRef"):
            # 池模式不支持 volumes
            if volumes:
                raise ValueError(
                    "池模式不支持 volumes。"
                    "请从请求中移除 'volumes' 或使用模板模式。"
                )
            # 使用池模式时，只允许自定义 entrypoint 和 env
            return self._create_workload_from_pool(
                batchsandbox_name=sandbox_id,
                namespace=namespace,
                labels=labels,
                pool_ref=extensions["poolRef"],
                expires_at=expires_at,
                entrypoint=entrypoint,
                env=env,
            )

        # 从模板提取额外的 Pod 规格片段（仅限 volumes/volumeMounts）
        extra_volumes, extra_mounts = self._extract_template_pod_extras()

        # 构建 execd 安装 init 容器
        init_container = self._build_execd_init_container(execd_image)

        # 构建主容器（带 execd 支持）
        main_container = self._build_main_container(
            image_spec=image_spec,
            entrypoint=entrypoint,
            env=env,
            resource_limits=resource_limits,
            has_network_policy=network_policy is not None,
        )

        # 构建 containers 列表
        containers = [self._container_to_dict(main_container)]

        # 构建基础 Pod 规格
        pod_spec: Dict[str, Any] = {
            "initContainers": [self._container_to_dict(init_container)],
            "containers": containers,
            "volumes": [
                {
                    "name": "opensandbox-bin",
                    "emptyDir": {}
                }
            ],
        }

        # 如果配置了安全运行时，注入 runtimeClassName
        if self.runtime_class:
            pod_spec["runtimeClassName"] = self.runtime_class

        # 如果提供了镜像认证，注入 imagePullSecrets
        # secret_name 是确定的，所以可以在 Secret 创建之前嵌入
        if image_spec.auth:
            secret_name = build_image_pull_secret_name(sandbox_id)
            pod_spec["imagePullSecrets"] = [{"name": secret_name}]

        # 如果提供了网络策略，添加 egress 侧车
        apply_egress_to_spec(
            pod_spec=pod_spec,
            containers=containers,
            network_policy=network_policy,
            egress_image=egress_image,
        )

        # 添加用户指定的卷
        if volumes:
            apply_volumes_to_pod_spec(pod_spec, volumes)

        # 构建运行时生成的 BatchSandbox manifest
        # 这只包含基本的运行时必需字段
        runtime_manifest = {
            "apiVersion": f"{self.group}/{self.version}",
            "kind": "BatchSandbox",
            "metadata": {
                "name": sandbox_id,
                "namespace": namespace,
                "labels": labels,
            },
            "spec": {
                "replicas": 1,
                "expireTime": expires_at.isoformat(),
                "template": {
                    "spec": pod_spec,
                },
            },
        }

        # 与模板合并获取最终 manifest
        batchsandbox = self.template_manager.merge_with_runtime_values(runtime_manifest)
        self._merge_pod_spec_extras(batchsandbox, extra_volumes, extra_mounts)

        # 创建 BatchSandbox
        created = self.k8s_client.create_custom_object(
            group=self.group,
            version=self.version,
            namespace=namespace,
            plural=self.plural,
            body=batchsandbox,
        )

        # 创建 imagePullSecret，ownerReference 指向 BatchSandbox
        if image_spec.auth:
            secret = build_image_pull_secret(
                sandbox_id=sandbox_id,
                image_uri=image_spec.uri,
                auth=image_spec.auth,
                owner_uid=created["metadata"]["uid"],
                owner_api_version=f"{self.group}/{self.version}",
                owner_kind="BatchSandbox",
            )
            try:
                self.k8s_client.create_secret(namespace=namespace, body=secret)
                logger.info("为 sandbox %s 创建了 imagePullSecret", sandbox_id)
            except Exception:
                logger.warning("为 sandbox %s 创建 imagePullSecret 失败，回滚 BatchSandbox", sandbox_id)
                try:
                    self.k8s_client.delete_custom_object(
                        group=self.group,
                        version=self.version,
                        namespace=namespace,
                        plural=self.plural,
                        name=sandbox_id,
                        grace_period_seconds=0,
                    )
                except Exception as del_exc:
                    logger.warning("回滚 BatchSandbox %s 失败：%s", sandbox_id, del_exc)
                raise

        return {
            "name": created["metadata"]["name"],
            "uid": created["metadata"]["uid"],
        }

    def _create_workload_from_pool(
        self,
        batchsandbox_name: str,
        namespace: str,
        labels: Dict[str, str],
        pool_ref: str,
        expires_at: datetime,
        entrypoint: List[str],
        env: Dict[str, str],
    ) -> Dict[str, Any]:
        """
        从预热的资源池创建 BatchSandbox 工作负载。

        基于池的创建使用 poolRef 引用现有的资源池。
        池已经定义了 Pod 模板，所以不需要额外的模板。
        只允许自定义 entrypoint 和 env。

        Args:
            batchsandbox_name: BatchSandbox 资源名称
            namespace: Kubernetes 命名空间
            labels: 要应用的标签
            pool_ref: 资源池引用
            expires_at: 过期时间
            entrypoint: 容器入口点命令（可自定义）
            env: 环境变量（可自定义）

        Returns:
            Dict[str, Any]: 包含 'name' 和 'uid' 的字典
        """
        runtime_manifest = {
            "apiVersion": f"{self.group}/{self.version}",
            "kind": "BatchSandbox",
            "metadata": {
                "name": batchsandbox_name,
                "namespace": namespace,
                "labels": labels,
            },
            "spec": {
                "replicas": 1,
                "poolRef": pool_ref,
                "expireTime": expires_at.isoformat(),
                "taskTemplate": self._build_task_template(entrypoint, env),
            },
        }

        # 基于池的创建不需要模板合并
        # 直接创建 BatchSandbox
        created = self.k8s_client.create_custom_object(
            group=self.group,
            version=self.version,
            namespace=namespace,
            plural=self.plural,
            body=runtime_manifest,
        )

        return {
            "name": created["metadata"]["name"],
            "uid": created["metadata"]["uid"],
        }

    def _extract_template_pod_extras(self) -> tuple[list[Dict[str, Any]], list[Dict[str, Any]]]:
        """
        从 BatchSandbox 模板提取额外的 volumes 和 volumeMounts。

        只支持这些字段，因为运行时 manifest 必须始终注入 execd init 容器、
        主容器和 volumes。

        Returns:
            tuple[list, list]: (extra_volumes, extra_mounts) 元组
        """
        template = self.template_manager.get_base_template()
        spec = template.get("spec", {}) if isinstance(template, dict) else {}
        template_spec = spec.get("template", {}).get("spec", {})
        extra_volumes = template_spec.get("volumes", []) or []

        extra_mounts: list[Dict[str, Any]] = []
        containers = template_spec.get("containers", []) or []
        if containers:
            # 如果存在名为 "sandbox" 的容器，优先使用它；否则使用第一个容器
            target = None
            for container in containers:
                if container.get("name") == "sandbox":
                    target = container
                    break
            if target is None:
                target = containers[0]
            extra_mounts = target.get("volumeMounts", []) or []

        if not isinstance(extra_volumes, list):
            extra_volumes = []
        if not isinstance(extra_mounts, list):
            extra_mounts = []
        return extra_volumes, extra_mounts

    def _merge_pod_spec_extras(
        self,
        batchsandbox: Dict[str, Any],
        extra_volumes: list[Dict[str, Any]],
        extra_mounts: list[Dict[str, Any]],
    ) -> None:
        """
        将额外的 volumes/volumeMounts 合并到运行时生成的 Pod 规格中。

        这保持 execd 注入完整，同时允许用户模板提供
        额外的只读挂载（如共享技能目录）。

        Args:
            batchsandbox: BatchSandbox manifest 字典（原地修改）
            extra_volumes: 额外的 volumes 列表
            extra_mounts: 额外的 volumeMounts 列表
        """
        try:
            spec = batchsandbox["spec"]["template"]["spec"]
        except KeyError:
            return

        # 按名称合并 volumes（不覆盖现有的运行时 volumes）
        volumes = spec.get("volumes", []) or []
        if isinstance(volumes, list) and extra_volumes:
            existing = {v.get("name") for v in volumes if isinstance(v, dict)}
            for vol in extra_volumes:
                if not isinstance(vol, dict):
                    continue
                name = vol.get("name")
                if not name or name in existing:
                    continue
                volumes.append(vol)
                existing.add(name)
            spec["volumes"] = volumes

        # 将 volumeMounts 合并到主容器（索引 0）
        containers = spec.get("containers", []) or []
        if not containers or not isinstance(containers, list):
            return
        main_container = containers[0]
        mounts = main_container.get("volumeMounts", []) or []
        if isinstance(mounts, list) and extra_mounts:
            existing = {m.get("name") for m in mounts if isinstance(m, dict)}
            for mnt in extra_mounts:
                if not isinstance(mnt, dict):
                    continue
                name = mnt.get("name")
                if not name or name in existing:
                    continue
                mounts.append(mnt)
                existing.add(name)
            main_container["volumeMounts"] = mounts

    # TODO: 支持空 cmd 或 env
    def _build_task_template(
        self,
        entrypoint: List[str],
        env: Dict[str, str],
    ) -> Dict[str, Any]:
        """
        为基于池的 BatchSandbox 构建 taskTemplate。

        在池模式下，任务应该使用 bootstrap.sh 启动 execd 和业务进程。

        生成的命令示例：
            /bin/sh -c "/opt/opensandbox/bin/bootstrap.sh python app.py &"

        注意：所有 entrypoint 参数都使用 shlex.quote 进行正确的 shell 转义，
        以防止 shell 注入并保留带有空格或特殊字符的参数。

        Args:
            entrypoint: 容器入口点命令
            env: 环境变量

        Returns:
            Dict[str, Any]: TaskSpec 结构的 taskTemplate 规格
        """
        # 构建命令：使用 entrypoint 在后台执行 bootstrap.sh
        # 使用 shlex.quote 安全转义每个 entrypoint 参数，防止 shell 注入
        escaped_entrypoint = ' '.join(shlex.quote(arg) for arg in entrypoint)
        user_process_cmd = f"/opt/opensandbox/bin/bootstrap.sh {escaped_entrypoint} &"

        wrapped_command = ["/bin/sh", "-c", user_process_cmd]

        # 将 env 字典转换为 k8s EnvVar 格式
        env_list = [{"name": k, "value": v} for k, v in env.items()] if env else []

        # 返回 TaskTemplateSpec 结构
        return {
            "spec": {
                "process": {
                    "command": wrapped_command,
                    "env": env_list,
                }
            }
        }

    def _build_execd_init_container(self, execd_image: str) -> V1Container:
        """
        构建用于 execd 安装的 init 容器。

        该 init 容器从 execd 镜像复制 execd 二进制和 bootstrap.sh 脚本
        到共享卷，使主容器可以使用它们。

        bootstrap.sh 脚本（来自 execd 镜像）将：
        - 在后台启动 execd（日志重定向到 /tmp/execd.log）
        - 使用 exec 替换当前进程为用户的命令

        Args:
            execd_image: execd 容器镜像

        Returns:
            V1Container: Init 容器规格
        """
        # 从镜像复制 execd 二进制和 bootstrap.sh 到共享卷
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
                    mount_path="/opt/opensandbox/bin"
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
        has_network_policy: bool = False,
    ) -> V1Container:
        """
        构建带 execd 支持的主容器规格。

        容器使用 bootstrap 脚本在后台启动 execd，然后执行用户命令。

        Args:
            image_spec: 容器镜像规格
            entrypoint: 容器入口点命令
            env: 环境变量
            resource_limits: 资源限制
            has_network_policy: 此 sandbox 是否启用了网络策略

        Returns:
            V1Container: 主容器规格
        """
        # 转换 env 字典为 V1EnvVar 列表并注入 EXECD 路径
        env_vars = [V1EnvVar(name=k, value=v) for k, v in env.items()]
        # 添加 EXECD 环境变量，指定 execd 二进制路径
        env_vars.append(V1EnvVar(name="EXECD", value="/opt/opensandbox/bin/execd"))

        # 构建资源需求
        resources = None
        if resource_limits:
            resources = V1ResourceRequirements(
                limits=resource_limits,
                requests=resource_limits,  # requests=limits 保证 QoS
            )

        # 使用 bootstrap 脚本包装入口点以启动 execd
        wrapped_command = ["/opt/opensandbox/bin/bootstrap.sh"] + entrypoint

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
            volume_mounts=[
                V1VolumeMount(
                    name="opensandbox-bin",
                    mount_path="/opt/opensandbox/bin"
                )
            ],
            security_context=security_context,
        )

    def _container_to_dict(self, container: V1Container) -> Dict[str, Any]:
        """
        将 V1Container 转换为字典（用于 CRD）。

        Args:
            container: V1Container 对象

        Returns:
            Dict[str, Any]: 容器的字典表示
        """
        result = {
            "name": container.name,
            "image": container.image,
        }

        if container.command:
            result["command"] = container.command

        if container.args:
            result["args"] = container.args

        if container.env:
            result["env"] = [
                {"name": e.name, "value": e.value}
                for e in container.env
            ]

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
        按 sandbox ID 获取 BatchSandbox。

        Args:
            sandbox_id: Sandbox 唯一标识符
            namespace: Kubernetes 命名空间

        Returns:
            Dict[str, Any]: BatchSandbox 资源对象
            None: 如果未找到
        """
        workload = self.k8s_client.get_custom_object(
            group=self.group,
            version=self.version,
            namespace=namespace,
            plural=self.plural,
            name=sandbox_id,
        )
        if workload:
            return workload

        # 回退到升级前使用 "sandbox-<id>" 命名的 sandbox
        legacy_name = self.legacy_resource_name(sandbox_id)
        if legacy_name != sandbox_id:
            return self.k8s_client.get_custom_object(
                group=self.group,
                version=self.version,
                namespace=namespace,
                plural=self.plural,
                name=legacy_name,
            )

        return None

    def delete_workload(self, sandbox_id: str, namespace: str) -> None:
        """
        删除 BatchSandbox 工作负载。

        Args:
            sandbox_id: Sandbox 唯一标识符
            namespace: Kubernetes 命名空间

        Raises:
            Exception: 如果 BatchSandbox 未找到
        """
        batchsandbox = self.get_workload(sandbox_id, namespace)
        if not batchsandbox:
            raise Exception(f"BatchSandbox for sandbox {sandbox_id} 未找到")

        self.k8s_client.delete_custom_object(
            group=self.group,
            version=self.version,
            namespace=namespace,
            plural=self.plural,
            name=batchsandbox["metadata"]["name"],
            grace_period_seconds=0,
        )

    def list_workloads(self, namespace: str, label_selector: str) -> List[Dict[str, Any]]:
        """
        列出匹配标签选择器的 BatchSandbox。

        Args:
            namespace: Kubernetes 命名空间
            label_selector: 标签选择器

        Returns:
            List[Dict[str, Any]]: BatchSandbox 资源列表
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
        更新 BatchSandbox 过期时间。

        Args:
            sandbox_id: Sandbox 唯一标识符
            namespace: Kubernetes 命名空间
            expires_at: 新的过期时间

        Raises:
            Exception: 如果 BatchSandbox 未找到或更新失败
        """
        batchsandbox = self.get_workload(sandbox_id, namespace)
        if not batchsandbox:
            raise Exception(f"BatchSandbox for sandbox {sandbox_id} 未找到")

        # 补丁 BatchSandbox spec.expireTime
        body = {
            "spec": {
                "expireTime": expires_at.isoformat()
            }
        }

        self.k8s_client.patch_custom_object(
            group=self.group,
            version=self.version,
            namespace=namespace,
            plural=self.plural,
            name=batchsandbox["metadata"]["name"],
            body=body,
        )

    def get_expiration(self, workload: Dict[str, Any]) -> Optional[datetime]:
        """
        从 BatchSandbox 获取过期时间。

        Args:
            workload: BatchSandbox 字典

        Returns:
            datetime: 过期时间
            None: 如果未设置或格式无效
        """
        spec = workload.get("spec", {})
        expire_time_str = spec.get("expireTime")

        if not expire_time_str:
            return None

        try:
            # 解析 ISO 格式日期时间
            return datetime.fromisoformat(expire_time_str.replace('Z', '+00:00'))
        except (ValueError, TypeError) as e:
            logger.warning("expireTime 格式无效：%s，错误：%s", expire_time_str, e)
            return None

    def _parse_pod_ip(self, workload: Dict[str, Any]) -> Optional[str]:
        """
        从 endpoints 注解解析第一个 Pod IP。

        如果注解存在且包含非空 JSON 数组，返回 IP 字符串，否则返回 None。

        Args:
            workload: BatchSandbox 字典

        Returns:
            str: Pod IP
            None: 如果注解不存在或格式无效
        """
        annotations = workload.get("metadata", {}).get("annotations", {})
        endpoints_str = annotations.get("sandbox.opensandbox.io/endpoints")
        if not endpoints_str:
            return None
        try:
            endpoints = json.loads(endpoints_str)
            if endpoints and len(endpoints) > 0:
                return endpoints[0]
        except (json.JSONDecodeError, IndexError, TypeError):
            pass
        return None

    def get_status(self, workload: Dict[str, Any]) -> Dict[str, Any]:
        """
        从 BatchSandbox 获取状态。

        状态从 BatchSandbox 状态字段派生：
        - replicas: Pod 总数
        - allocated: 已调度的 Pod 数
        - ready: 就绪的 Pod 数

        Args:
            workload: BatchSandbox 字典

        Returns:
            Dict[str, Any]: 包含 state、reason、message、last_transition_at 的字典
        """
        status = workload.get("status", {})

        replicas = status.get("replicas", 0)
        ready = status.get("ready", 0)
        allocated = status.get("allocated", 0)

        pod_ip = self._parse_pod_ip(workload)

        # 确定状态：Pending -> Allocated (已分配 IP) -> Running (Pod 就绪)
        if ready == 1 and pod_ip:
            # Pod 就绪且有 IP
            state = "Running"
            reason = "POD_READY_WITH_IP"
            message = f"Pod 已就绪且已分配 IP ({ready}/{replicas} 就绪)"
        elif pod_ip:
            # Pod 已分配 IP 但还未就绪
            state = "Allocated"
            reason = "IP_ASSIGNED"
            message = f"Pod 已分配 IP 但还未就绪 ({allocated}/{replicas} 已分配，{ready} 就绪)"
        else:
            # Pod 还未分配或已分配但无 IP
            state = "Pending"
            reason = "POD_SCHEDULED" if allocated > 0 else "BATCHSANDBOX_PENDING"
            message = (
                f"Pod 已调度但等待 IP 分配 ({allocated}/{replicas} 已分配，{ready} 就绪)"
                if allocated > 0
                else "BatchSandbox 正在等待分配"
            )

        # 获取创建时间戳
        creation_timestamp = workload.get("metadata", {}).get("creationTimestamp")

        return {
            "state": state,
            "reason": reason,
            "message": message,
            "last_transition_at": creation_timestamp,
        }

    def get_endpoint_info(self, workload: Dict[str, Any], port: int, sandbox_id: str) -> Optional[Endpoint]:
        """
        从 BatchSandbox 获取端点信息。
        - gateway 模式：使用 ingress 配置格式化端点
        - 直接/默认：从注解解析 Pod IP

        Args:
            workload: BatchSandbox 字典
            port: 端口号
            sandbox_id: Sandbox 标识符

        Returns:
            Endpoint: 端点对象
            None: 如果端点不可用
        """
        if self.ingress_config and self.ingress_config.mode == INGRESS_MODE_GATEWAY:
            return format_ingress_endpoint(self.ingress_config, sandbox_id, port)

        pod_ip = self._parse_pod_ip(workload)
        if not pod_ip:
            return None
        return Endpoint(endpoint=f"{pod_ip}:{port}")
