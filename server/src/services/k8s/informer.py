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
Kubernetes 命名空间自定义资源的轻量级 Informer 风格缓存模块。

本模块提供了 WorkloadInformer 类，用于：
- 通过 watch API 监听自定义资源的变化
- 在本地维护资源的缓存副本
- 提供高效的读取操作（优先从缓存读取）

Informer 是 Kubernetes 客户端与 API 服务器之间的高效同步机制：
1. 初始全量列表（List）：获取当前所有资源
2. 增量监听（Watch）：监听后续的变化事件（ADD、MODIFIED、DELETED）
3. 自动重连：当 watch 连接断开时自动重新建立

使用示例：
    >>> def list_fn(**kwargs):
    ...     return custom_api.list_namespaced_custom_object(...)
    >>> informer = WorkloadInformer(list_fn=list_fn)
    >>> informer.start()  # 启动后台监听线程
    >>> # 从缓存读取
    >>> obj = informer.get("my-resource")
"""

import logging
import threading
from typing import Any, Callable, Dict, Optional

from kubernetes import watch
from kubernetes.client import ApiException

logger = logging.getLogger(__name__)


class WorkloadInformer:
    """
    通过 watch API 维护命名空间自定义资源的内存缓存。

    该类实现了 Kubernetes Informer 模式的核心功能：
    - 初始全量同步（List）
    - 增量监听更新（Watch）
    - 线程安全的缓存访问
    - 自动重连和退避重试

    线程模型：
    - 后台监听线程：持续监听资源变化
    - 主线程：读取和更新缓存

    Attributes:
        list_fn: 列出资源的回调函数
        resync_period_seconds: 全量同步间隔（当 watch 禁用时）
        watch_timeout_seconds: 每次 watch 流的超时时间
        enable_watch: 是否启用 watch 监听
        has_synced: 是否已完成初始同步

    Examples:
        >>> informer = WorkloadInformer(
        ...     list_fn=list_fn,
        ...     resync_period_seconds=300,
        ...     watch_timeout_seconds=60
        ... )
        >>> informer.start()
        >>> obj = informer.get("resource-name")
    """

    def __init__(
        self,
        list_fn: Callable[..., Any],
        resync_period_seconds: int = 300,
        watch_timeout_seconds: int = 60,
        enable_watch: bool = True,
        thread_name: str = "workload-informer",
    ):
        """
        初始化 WorkloadInformer。

        Args:
            list_fn: 列出自定义资源的回调函数
                     签名：``list_fn(**kwargs) -> dict``
                     通常是 ``custom_api.list_namespaced_custom_object`` 的绑定方法
            resync_period_seconds: 全量同步间隔（秒），当 watch 禁用时使用
            watch_timeout_seconds: 每次 watch 流的超时时间（秒）
            enable_watch: 是否启用 watch 监听，False 时只执行初始列表
            thread_name: 后台线程名称，用于调试和日志

        注意：
            - list_fn 应该返回包含 "items" 和 "metadata" 字段的字典
            - metadata.resourceVersion 用于 watch 的断点续传
        """
        self.list_fn = list_fn
        self.resync_period_seconds = resync_period_seconds
        self.watch_timeout_seconds = watch_timeout_seconds
        self.enable_watch = enable_watch
        self._thread_name = thread_name

        # 缓存：name -> resource
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.RLock()
        # 当前 resourceVersion，用于 watch 的断点续传
        self._resource_version: Optional[str] = None
        self._has_synced = False
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    @property
    def has_synced(self) -> bool:
        """
        检查是否已完成初始同步。

        Returns:
            bool: 如果已完成初始列表操作返回 True
        """
        return self._has_synced

    def start(self) -> None:
        """
        启动后台监听线程（如果尚未运行）。

        该方法会创建一个守护线程，在后台持续监听资源变化。
        如果线程已经在运行，该方法不执行任何操作。
        """
        if self._thread and self._thread.is_alive():
            return

        self._thread = threading.Thread(
            target=self._run,
            name=self._thread_name,
            daemon=True,  # 守护线程，主程序退出时自动退出
        )
        self._thread.start()

    def stop(self) -> None:
        """
        停止后台监听线程。

        该方法设置停止事件，当前 watch 循环会在下次检查时退出。
        """
        self._stop_event.set()

    def get(self, name: str) -> Optional[Dict[str, Any]]:
        """
        从缓存中按名称获取资源对象。

        Args:
            name: 资源名称

        Returns:
            Dict[str, Any]: 资源对象
            None: 如果资源不在缓存中

        注意：该方法是线程安全的。
        """
        with self._lock:
            return self._cache.get(name)

    def update_cache(self, obj: Dict[str, Any]) -> None:
        """
        将单个对象插入/更新到缓存中。

        只有当传入的 resourceVersion 严格更新时才会推进 ``_resource_version``，
        防止过时的 API 响应回滚 watch 游标。

        Args:
            obj: 要缓存的资源对象
        """
        metadata = obj.get("metadata", {})
        name = metadata.get("name")
        if not name:
            return

        with self._lock:
            self._cache[name] = obj
            self._advance_resource_version(metadata.get("resourceVersion"))

    def _advance_resource_version(self, rv: Optional[str]) -> None:
        """
        仅当 rv 严格更新时才推进 ``_resource_version``。

        K8s 的 resourceVersion 是不透明的字符串，但 etcd 将其编码为
        单调递增的整数。如果转换失败，我们跳过更新（保守策略：保持当前较新的游标）。

        必须在已持有 ``self._lock`` 的情况下调用。

        Args:
            rv: 新的 resourceVersion
        """
        if not rv:
            return
        if self._resource_version is None:
            self._resource_version = rv
            return
        try:
            # 尝试将 resourceVersion 转换为整数进行比较
            if int(rv) > int(self._resource_version):
                self._resource_version = rv
        except ValueError:
            # 非整数的 resourceVersion，跳过以避免降级
            pass

    def _run(self) -> None:
        """
        Informer 主循环。

        执行逻辑：
        1. 执行初始全量同步（如果尚未同步）
        2. 如果启用 watch，执行监听循环
        3. 如果 watch 禁用，等待下一个 resync 周期
        4. 错误处理和指数退避重试

        错误处理：
        - 410 Gone：resourceVersion 过期，强制全量刷新
        - 其他错误：指数退避重试（最大 30 秒）
        """
        backoff = 1.0  # 退避时间（秒）
        while not self._stop_event.is_set():
            try:
                if not self._has_synced:
                    # 执行初始全量同步
                    self._full_resync()
                    backoff = 1.0

                if not self.enable_watch:
                    # 禁用 watch，等待下一个 resync 周期
                    self._stop_event.wait(self.resync_period_seconds)
                    self._has_synced = False  # 下次循环触发全量刷新
                    continue

                # 执行 watch 监听循环
                self._run_watch_loop()
                backoff = 1.0
            except ApiException as exc:
                if exc.status == 410:
                    # Resource version 过期，强制全量刷新
                    self._resource_version = None
                    self._has_synced = False
                else:
                    logger.warning("Informer watch 错误：%s", exc, exc_info=True)
                    self._has_synced = False
                    self._stop_event.wait(min(backoff, 30.0))
                    backoff = min(backoff * 2, 30.0)
            except Exception as exc:  # pragma: no cover - 防御性代码
                logger.warning("Informer 意外错误：%s", exc, exc_info=True)
                self._has_synced = False
                self._stop_event.wait(min(backoff, 30.0))
                backoff = min(backoff * 2, 30.0)

    def _full_resync(self) -> None:
        """
        执行全量列表操作以刷新缓存。

        该方法会：
        1. 调用 list_fn 获取当前所有资源
        2. 构建新的缓存字典
        3. 更新 resourceVersion
        4. 标记已同步状态
        """
        resp = self.list_fn()

        # list 响应是字典格式（CustomObjectsApi）
        items = resp.get("items", []) if isinstance(resp, dict) else []
        metadata = resp.get("metadata", {}) if isinstance(resp, dict) else {}
        resource_version = metadata.get("resourceVersion")

        # 在锁外构建新缓存，避免阻塞读取者
        new_cache: Dict[str, Dict[str, Any]] = {}
        for item in items:
            name = item.get("metadata", {}).get("name")
            if name:
                new_cache[name] = item

        with self._lock:
            self._cache = new_cache
            self._advance_resource_version(resource_version)
            self._has_synced = True

    def _run_watch_loop(self) -> None:
        """
        流式监听事件以保持缓存新鲜。

        该方法会：
        1. 创建 Watch 对象
        2. 从上次 resourceVersion 开始监听
        3. 处理每个事件（ADD、MODIFIED、DELETED）
        4. 超时后正常退出（由调用者重新建立连接）
        """
        w = watch.Watch()
        try:
            for event in w.stream(
                self.list_fn,
                resource_version=self._resource_version,
                timeout_seconds=self.watch_timeout_seconds,
            ):
                if self._stop_event.is_set():
                    break
                self._handle_event(event)
        finally:
            w.stop()

    def _handle_event(self, event: Dict[str, Any]) -> None:
        """
        处理单个 watch 事件。

        事件类型：
        - ADDED：添加资源到缓存
        - MODIFIED：更新缓存中的资源
        - DELETED：从缓存中移除资源
        - ERROR：错误事件（通常抛出异常）

        Args:
            event: Watch 事件字典，包含 "type" 和 "object" 字段
        """
        obj = event.get("object")
        if obj is None:
            return

        # 将 Kubernetes 模型对象转换为字典
        if not isinstance(obj, dict):
            try:
                obj = obj.to_dict()
            except Exception:
                return

        metadata = obj.get("metadata", {})
        name = metadata.get("name")
        if not name:
            return

        event_type = event.get("type")
        with self._lock:
            if event_type == "DELETED":
                # 删除事件：从缓存中移除
                self._cache.pop(name, None)
            else:
                # ADDED 或 MODIFIED：更新缓存
                self._cache[name] = obj
            self._advance_resource_version(metadata.get("resourceVersion"))
