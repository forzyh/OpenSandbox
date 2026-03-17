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
Kubernetes 客户端包装器模块。

本模块提供了一个统一的 Kubernetes API 客户端包装器 K8sClient，
封装了所有 K8s 资源操作。所有对 Kubernetes API 的访问都通过这个类进行。

主要功能：
- 统一的 Kubernetes 配置加载（支持 kubeconfig 文件和集群内配置）
- CustomObject（自定义资源）操作：create、get、list、delete、patch
- Secret 操作：create
- Pod 操作：list
- RuntimeClass 操作：read
- Informer 支持：通过 WorkloadInformer 实现缓存和监听
- 速率限制：支持读写速率限制（QPS/Burst）

使用示例：
    >>> k8s_client = K8sClient(kubernetes_config)
    >>> # 创建自定义资源
    >>> obj = k8s_client.create_custom_object(...)
    >>> # 获取资源（优先从 informer 缓存读取）
    >>> obj = k8s_client.get_custom_object(...)
"""

import logging
import threading
from functools import partial
from typing import Any, Dict, List, Optional, Tuple

from kubernetes import client, config
from kubernetes.client import ApiException, CoreV1Api, CustomObjectsApi, NodeV1Api

from src.config import KubernetesRuntimeConfig
from src.services.k8s.informer import WorkloadInformer
from src.services.k8s.rate_limiter import TokenBucketRateLimiter

logger = logging.getLogger(__name__)

# 类型别名：informer 缓存键
# 格式：(group, version, plural, namespace)
_InformerKey = Tuple[str, str, str, str]  # (group, version, plural, namespace)


class K8sClient:
    """
    统一的 Kubernetes API 客户端。

    封装了所有集群资源操作（CustomObject、Secret、Pod、RuntimeClass）。
    调用者不会直接持有原始 API 句柄。

    特性：
    - 配置加载：支持 kubeconfig 文件和集群内服务账户配置
    - Informer 缓存：可选的本地缓存，通过 watch 机制保持同步
    - 速率限制：保护 Kubernetes API 服务器免受过载

    Attributes:
        config: Kubernetes 运行时配置
        _core_v1_api: CoreV1Api 实例（Pod、Secret 等操作）
        _custom_objects_api: CustomObjectsApi 实例（CRD 操作）
        _node_v1_api: NodeV1Api 实例（RuntimeClass 等操作）
        _informers: Informer 池，key -> WorkloadInformer
        _read_limiter: 读操作速率限制器
        _write_limiter: 写操作速率限制器

    Examples:
        >>> k8s_client = K8sClient(kubernetes_config)
        >>> # 获取自定义资源
        >>> obj = k8s_client.get_custom_object(
        ...     group="sandbox.opensandbox.io",
        ...     version="v1alpha1",
        ...     namespace="default",
        ...     plural="batchsandboxes",
        ...     name="my-sandbox"
        ... )
    """

    def __init__(self, k8s_config: KubernetesRuntimeConfig):
        """
        初始化 Kubernetes 客户端。

        Args:
            k8s_config: Kubernetes 运行时配置，包含：
                       - kubeconfig_path: kubeconfig 文件路径（可选，集群内部署时为空）
                       - informer_enabled: 是否启用 informer 缓存
                       - read_qps/read_burst: 读速率限制
                       - write_qps/write_burst: 写速率限制

        Raises:
            Exception: 如果 Kubernetes 配置加载失败
        """
        self.config = k8s_config
        self._load_config()
        self._core_v1_api: Optional[CoreV1Api] = None
        self._custom_objects_api: Optional[CustomObjectsApi] = None
        self._node_v1_api: Optional[NodeV1Api] = None
        # Informer 池：key -> WorkloadInformer
        self._informers: Dict[_InformerKey, WorkloadInformer] = {}
        self._informers_lock = threading.Lock()
        # 速率限制器（None = 无限制）
        self._read_limiter: Optional[TokenBucketRateLimiter] = (
            TokenBucketRateLimiter(qps=k8s_config.read_qps, burst=k8s_config.read_burst)
            if k8s_config.read_qps > 0
            else None
        )
        self._write_limiter: Optional[TokenBucketRateLimiter] = (
            TokenBucketRateLimiter(qps=k8s_config.write_qps, burst=k8s_config.write_burst)
            if k8s_config.write_qps > 0
            else None
        )

    # ------------------------------------------------------------------
    # 内部 API 句柄访问器（惰性单例）
    # ------------------------------------------------------------------

    def _load_config(self) -> None:
        """
        从 kubeconfig 文件或集群内服务账户加载 Kubernetes 配置。

        加载逻辑：
        - 如果指定了 kubeconfig_path，从文件加载
        - 否则，尝试从集群内服务账户加载（用于 Pod 内运行）

        Raises:
            Exception: 如果配置加载失败
        """
        try:
            if self.config.kubeconfig_path:
                # 从文件加载 kubeconfig
                config.load_kube_config(config_file=self.config.kubeconfig_path)
            else:
                # 从集群内服务账户加载
                config.load_incluster_config()
        except Exception as e:
            raise Exception(f"加载 Kubernetes 配置失败：{e}") from e

    def get_core_v1_api(self) -> CoreV1Api:
        """
        获取 CoreV1Api 实例（惰性初始化）。

        CoreV1Api 用于操作核心资源，如 Pod、Secret、ConfigMap 等。

        Returns:
            CoreV1Api: CoreV1 API 客户端实例
        """
        if self._core_v1_api is None:
            self._core_v1_api = client.CoreV1Api()
        return self._core_v1_api

    def get_custom_objects_api(self) -> CustomObjectsApi:
        """
        获取 CustomObjectsApi 实例（惰性初始化）。

        CustomObjectsApi 用于操作自定义资源（CRD）。

        Returns:
            CustomObjectsApi: CustomObjects API 客户端实例
        """
        if self._custom_objects_api is None:
            self._custom_objects_api = client.CustomObjectsApi()
        return self._custom_objects_api

    def get_node_v1_api(self) -> NodeV1Api:
        """
        获取 NodeV1Api 实例（惰性初始化）。

        NodeV1Api 用于操作节点相关资源，如 RuntimeClass。

        Returns:
            NodeV1Api: NodeV1 API 客户端实例
        """
        if self._node_v1_api is None:
            self._node_v1_api = client.NodeV1Api()
        return self._node_v1_api

    # ------------------------------------------------------------------
    # Informer 池管理
    # ------------------------------------------------------------------

    def _get_informer(self, group: str, version: str, plural: str, namespace: str) -> Optional[WorkloadInformer]:
        """
        获取指定资源 + 命名空间的 informer，惰性启动。

        Informer 是 Kubernetes 的本地缓存机制，通过 watch API 保持与集群状态同步。
        使用 informer 可以减少对 API 服务器的直接调用，提高性能。

        Args:
            group: API 组（如 "sandbox.opensandbox.io"）
            version: API 版本（如 "v1alpha1"）
            plural: 资源复数形式（如 "batchsandboxes"）
            namespace: 命名空间

        Returns:
            WorkloadInformer: Informer 实例
            None: 如果 informer 被禁用或启动失败
        """
        if not self.config.informer_enabled:
            return None

        key: _InformerKey = (group, version, plural, namespace)
        with self._informers_lock:
            informer = self._informers.get(key)
            if informer is None:
                # 创建 list 函数绑定
                list_fn = partial(
                    self.get_custom_objects_api().list_namespaced_custom_object,
                    group=group,
                    version=version,
                    namespace=namespace,
                    plural=plural,
                )
                # 创建 informer 实例
                informer = WorkloadInformer(
                    list_fn=list_fn,
                    resync_period_seconds=self.config.informer_resync_seconds,
                    watch_timeout_seconds=self.config.informer_watch_timeout_seconds,
                    thread_name=f"workload-informer-{plural}-{namespace}",
                )
                self._informers[key] = informer
                try:
                    # 启动 informer
                    informer.start()
                except Exception as exc:  # pragma: no cover - 防御性代码
                    logger.warning("启动 %s/%s 的 informer 失败：%s", plural, namespace, exc)
                    self._informers.pop(key, None)
                    return None
        return informer

    # ------------------------------------------------------------------
    # CustomObject 操作
    # ------------------------------------------------------------------

    def create_custom_object(
        self,
        group: str,
        version: str,
        namespace: str,
        plural: str,
        body: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        创建命名空间内的自定义资源。

        Args:
            group: API 组（如 "sandbox.opensandbox.io"）
            version: API 版本（如 "v1alpha1"）
            namespace: 命名空间
            plural: 资源复数形式（如 "batchsandboxes"）
            body: 资源定义（YAML/JSON 结构）

        Returns:
            Dict[str, Any]: 创建的资源对象

        Raises:
            ApiException: 如果创建失败
        """
        if self._write_limiter:
            self._write_limiter.acquire()
        return self.get_custom_objects_api().create_namespaced_custom_object(
            group=group,
            version=version,
            namespace=namespace,
            plural=plural,
            body=body,
        )

    def get_custom_object(
        self,
        group: str,
        version: str,
        namespace: str,
        plural: str,
        name: str,
    ) -> Optional[Dict[str, Any]]:
        """
        按名称获取命名空间内的自定义资源。

        优先尝试从 informer 缓存读取（如果可用且已同步）。
        如果资源不存在（404）则返回 None。

        Args:
            group: API 组
            version: API 版本
            namespace: 命名空间
            plural: 资源复数形式
            name: 资源名称

        Returns:
            Dict[str, Any]: 资源对象
            None: 如果资源不存在

        Raises:
            ApiException: 如果获取失败（404 除外）
        """
        # 优先从 informer 缓存读取
        informer = self._get_informer(group, version, plural, namespace)
        if informer and informer.has_synced:
            cached = informer.get(name)
            if cached is not None:
                return cached

        # 缓存未命中，调用 API
        if self._read_limiter:
            self._read_limiter.acquire()
        try:
            obj = self.get_custom_objects_api().get_namespaced_custom_object(
                group=group,
                version=version,
                namespace=namespace,
                plural=plural,
                name=name,
            )
            # 更新 informer 缓存
            if informer:
                informer.update_cache(obj)
            return obj
        except ApiException as e:
            if e.status == 404:
                return None
            raise

    def list_custom_objects(
        self,
        group: str,
        version: str,
        namespace: str,
        plural: str,
        label_selector: str = "",
    ) -> List[Dict[str, Any]]:
        """
        列出命名空间内的自定义资源，返回 items 列表。

        Args:
            group: API 组
            version: API 版本
            namespace: 命名空间
            plural: 资源复数形式
            label_selector: 标签选择器（可选）

        Returns:
            List[Dict[str, Any]]: 资源对象列表

        Raises:
            ApiException: 如果列表失败
        """
        if self._read_limiter:
            self._read_limiter.acquire()
        try:
            resp = self.get_custom_objects_api().list_namespaced_custom_object(
                group=group,
                version=version,
                namespace=namespace,
                plural=plural,
                label_selector=label_selector,
            )
            return resp.get("items", [])
        except ApiException as e:
            if e.status == 404:
                return []
            raise

    def delete_custom_object(
        self,
        group: str,
        version: str,
        namespace: str,
        plural: str,
        name: str,
        grace_period_seconds: int = 0,
    ) -> None:
        """
        删除命名空间内的自定义资源。

        Args:
            group: API 组
            version: API 版本
            namespace: 命名空间
            plural: 资源复数形式
            name: 资源名称
            grace_period_seconds: 宽限期（秒），0 表示立即删除

        Raises:
            ApiException: 如果删除失败
        """
        if self._write_limiter:
            self._write_limiter.acquire()
        self.get_custom_objects_api().delete_namespaced_custom_object(
            group=group,
            version=version,
            namespace=namespace,
            plural=plural,
            name=name,
            grace_period_seconds=grace_period_seconds,
        )

    def patch_custom_object(
        self,
        group: str,
        version: str,
        namespace: str,
        plural: str,
        name: str,
        body: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        补丁（部分更新）命名空间内的自定义资源。

        Args:
            group: API 组
            version: API 版本
            namespace: 命名空间
            plural: 资源复数形式
            name: 资源名称
            body: 补丁内容（合并补丁）

        Returns:
            Dict[str, Any]: 更新后的资源对象

        Raises:
            ApiException: 如果补丁失败
        """
        if self._write_limiter:
            self._write_limiter.acquire()
        return self.get_custom_objects_api().patch_namespaced_custom_object(
            group=group,
            version=version,
            namespace=namespace,
            plural=plural,
            name=name,
            body=body,
        )

    # ------------------------------------------------------------------
    # Secret 操作
    # ------------------------------------------------------------------

    def create_secret(self, namespace: str, body: Any) -> Any:
        """
        创建命名空间内的 Secret。

        Args:
            namespace: 命名空间
            body: Secret 定义（V1Secret 对象）

        Returns:
            Any: 创建的 Secret 对象

        Raises:
            ApiException: 如果创建失败
        """
        if self._write_limiter:
            self._write_limiter.acquire()
        return self.get_core_v1_api().create_namespaced_secret(
            namespace=namespace,
            body=body,
        )

    # ------------------------------------------------------------------
    # Pod 操作
    # ------------------------------------------------------------------

    def list_pods(
        self,
        namespace: str,
        label_selector: str = "",
    ) -> List[Any]:
        """
        列出命名空间内的 Pod，返回 items 列表。

        Args:
            namespace: 命名空间
            label_selector: 标签选择器（可选）

        Returns:
            List[Any]: Pod 对象列表

        Raises:
            ApiException: 如果列表失败
        """
        if self._read_limiter:
            self._read_limiter.acquire()
        resp = self.get_core_v1_api().list_namespaced_pod(
            namespace=namespace,
            label_selector=label_selector,
        )
        return resp.items

    # ------------------------------------------------------------------
    # RuntimeClass 操作
    # ------------------------------------------------------------------

    def read_runtime_class(self, name: str) -> Any:
        """
        从集群读取 RuntimeClass。

        RuntimeClass 是 Kubernetes 中用于配置容器运行时的资源。
        安全运行时（如 gVisor、Kata Containers）需要配置 RuntimeClass。

        Args:
            name: RuntimeClass 名称

        Returns:
            Any: RuntimeClass 对象

        Raises:
            ApiException: 如果读取失败
        """
        if self._read_limiter:
            self._read_limiter.acquire()
        return self.get_node_v1_api().read_runtime_class(name)
