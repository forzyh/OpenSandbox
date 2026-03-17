#
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
#
"""
指标监控服务适配器模块 - Metrics Adapter

本模块提供了 MetricsAdapter 类，是指标监控服务的实现。

设计目的：
    - 实现 Metrics 服务接口，提供沙箱资源监控功能
    - 适配 openapi-python-client 自动生成的 MetricApi
    - 收集沙箱的 CPU、内存等资源使用指标

核心功能：
    - 获取指标：收集沙箱的 CPU 使用率、内存消耗等性能指标
    - 资源监控：监控沙箱的资源使用情况，帮助优化资源分配

架构说明：
    MetricsAdapter 是 Metrics 服务接口的具体实现，它：
    1. 使用 openapi-python-client 生成的 Client 进行 API 调用
    2. 使用自定义的 httpx.AsyncClient 进行底层 HTTP 通信
    3. 使用 MetricsModelConverter 转换 API 模型为领域模型
    4. Execd API 不需要认证（认证在沙箱层面完成）

使用示例：
    ```python
    from opensandbox.config import ConnectionConfig
    from opensandbox.adapters.metrics_adapter import MetricsAdapter

    config = ConnectionConfig(api_key="key", domain="api.opensandbox.io")
    adapter = MetricsAdapter(config, endpoint)

    # 获取沙箱资源指标
    metrics = await adapter.get_metrics(sandbox_id)
    print(f"CPU: {metrics.cpu_used_percent}%")
    print(f"Memory: {metrics.memory_used_in_mib}MB")
    ```
"""

import logging

import httpx

from opensandbox.adapters.converter.exception_converter import (
    ExceptionConverter,
)
from opensandbox.adapters.converter.metrics_model_converter import (
    MetricsModelConverter,
)
from opensandbox.adapters.converter.response_handler import (
    handle_api_error,
    require_parsed,
)
from opensandbox.config import ConnectionConfig
from opensandbox.models.sandboxes import SandboxEndpoint, SandboxMetrics
from opensandbox.services.metrics import Metrics

# 配置模块日志记录器
logger = logging.getLogger(__name__)


class MetricsAdapter(Metrics):
    """
    指标监控服务适配器 - Metrics 接口的实现

    本类提供了沙箱资源监控的完整实现，用于收集和分析沙箱的性能指标。

    继承关系：
        MetricsAdapter 实现了 Metrics Protocol 接口，提供：
        - get_metrics: 获取沙箱的当前资源使用指标

    技术实现：
        - 基于 openapi-python-client 生成的功能型 API
        - 使用 httpx 进行底层 HTTP 通信
        - 使用 MetricsModelConverter 转换 API 模型为领域模型
        - Execd API 不需要认证（认证在沙箱层面完成）

    HTTP 客户端架构：
        _client (Client): 标准 API 客户端
            - 由 openapi-python-client 生成
            - 注入 _httpx_client 进行底层通信

        _httpx_client (httpx.AsyncClient): 底层 HTTP 客户端
            - 用于标准 API 调用
            - 使用正常超时设置
            - 共享 connection_config 的 transport

    属性：
        connection_config (ConnectionConfig): 连接配置
        execd_endpoint (SandboxEndpoint): Execd 服务端点

    使用示例：
        ```python
        adapter = MetricsAdapter(config, endpoint)

        # 获取沙箱资源指标
        metrics = await adapter.get_metrics(sandbox_id)
        print(f"CPU usage: {metrics.cpu_used_percent}%")
        print(f"Memory usage: {metrics.memory_used_in_mib}MB")
        ```
    """

    def __init__(
        self,
        connection_config: ConnectionConfig,
        execd_endpoint: SandboxEndpoint,
    ) -> None:
        """
        初始化指标监控服务适配器

        构造函数负责创建和配置 HTTP 客户端，用于指标监控 API 调用。

        参数：
            connection_config (ConnectionConfig): 连接配置对象
                - 包含共享的 transport、超时设置、请求头等
            execd_endpoint (SandboxEndpoint): Execd 服务端点
                - 包含沙箱的网络访问地址
                - 包含访问该端点所需的请求头

        客户端配置说明：
            1. _client (标准 API 客户端):
               - 使用正常超时
               - 不需要认证（Execd API 无需认证）

            2. _httpx_client (底层 HTTP 客户端):
               - 使用正常超时
               - 包含 User-Agent 和自定义请求头
               - 共享 connection_config 的 transport

        示例：
            ```python
            config = ConnectionConfig(
                api_key="your-api-key",
                domain="api.opensandbox.io"
            )
            endpoint = await sandbox.get_endpoint(DEFAULT_EXECD_PORT)
            adapter = MetricsAdapter(config, endpoint)
            ```
        """
        # 保存配置和端点，后续方法使用
        self.connection_config = connection_config
        self.execd_endpoint = execd_endpoint

        # 导入 Execd API 客户端
        # 这个客户端由 openapi-python-client 生成，用于执行指标监控相关 API
        from opensandbox.api.execd import Client

        # 构建基础 URL（协议 + 端点）
        protocol = self.connection_config.protocol
        base_url = f"{protocol}://{self.execd_endpoint.endpoint}"

        # 获取超时时间（秒）
        timeout_seconds = self.connection_config.request_timeout.total_seconds()
        timeout = httpx.Timeout(timeout_seconds)

        # 构建请求头
        # 包含 User-Agent、connection_config 的自定义头、端点自定义头
        headers = {
            "User-Agent": self.connection_config.user_agent,
            **self.connection_config.headers,
            **self.execd_endpoint.headers,
        }

        # 创建标准 API 客户端
        # Execd API 不需要认证（认证在沙箱层面完成）
        self._client = Client(
            base_url=base_url,
            timeout=timeout,
        )

        # 创建底层 httpx 客户端
        # 这个客户端由适配器拥有和管理，注入到 _client 中使用
        # 配置说明：
        #   - base_url: API 基础 URL
        #   - headers: 请求头
        #   - timeout: 请求超时
        #   - transport: 共享的传输层，用于连接池管理
        self._httpx_client = httpx.AsyncClient(
            base_url=base_url,
            headers=headers,
            timeout=timeout,
            transport=self.connection_config.transport,
        )

        # 将 httpx 客户端注入到 API 客户端
        # 这样生成的 API 函数就会使用这个客户端进行 HTTP 调用
        self._client.set_async_httpx_client(self._httpx_client)

    async def _get_client(self):
        """
        获取 API 客户端

        内部方法，返回用于调用 Execd API 的客户端。
        Execd API 不需要认证。

        返回：
            Client: 配置好的 API 客户端实例
        """
        return self._client

    async def get_metrics(self, sandbox_id: str) -> SandboxMetrics:
        """
        获取沙箱的当前资源使用指标

        收集沙箱的性能指标，包括 CPU 使用率、内存消耗等信息。
        这些指标可用于监控沙箱的资源使用情况，帮助优化资源分配。

        参数：
            sandbox_id (str): 沙箱的唯一标识符
                - 用于标识要获取指标的沙箱
                - 注意：当前实现中此参数主要用于日志记录

        返回：
            SandboxMetrics: 沙箱资源指标对象，包含：
                - cpu_used_percent: CPU 使用率百分比
                - memory_used_in_mib: 内存使用量（MiB）
                - memory_total_in_mib: 总内存量（MiB）
                - timestamp: 指标采集时间戳

        异常：
            SandboxException: 如果指标获取失败
            SandboxApiException: 如果 API 调用失败

        使用示例：
            ```python
            adapter = MetricsAdapter(config, endpoint)

            # 获取沙箱资源指标
            metrics = await adapter.get_metrics(sandbox_id)
            print(f"CPU usage: {metrics.cpu_used_percent}%")
            print(f"Memory usage: {metrics.memory_used_in_mib}/{metrics.memory_total_in_mib} MB")
            ```

        注意事项：
            - 指标是实时采集的，反映调用时刻的资源状态
            - 适合用于监控面板、资源告警等场景
            - 频繁调用可能增加系统开销，建议合理设置采集频率
        """
        # 记录调试日志
        logger.debug(f"Retrieving sandbox metrics for {sandbox_id}")

        try:
            # 导入获取指标的 API 函数
            from opensandbox.api.execd.api.metric import get_metrics

            # 获取 API 客户端
            client = await self._get_client()

            # 调用 API 获取指标
            # asyncio_detailed 版本返回完整的响应对象，包含状态码和头信息
            response_obj = await get_metrics.asyncio_detailed(client=client)

            # 处理 API 错误
            # 如果响应状态码不是 200，会抛出异常
            handle_api_error(response_obj, "Get metrics")

            # 导入 API 模型
            from opensandbox.api.execd.models import Metrics

            # 解析响应并转换为领域模型
            # require_parsed 确保响应已成功解析
            parsed = require_parsed(response_obj, Metrics, "Get metrics")

            # 使用转换器将 API 模型转换为 SDK 模型
            # MetricsModelConverter 负责字段映射和类型转换
            return MetricsModelConverter.to_sandbox_metrics(parsed)

        except Exception as e:
            # 记录错误日志
            logger.error(f"Failed to get metrics for sandbox {sandbox_id}", exc_info=e)
            # 转换为 SDK 标准异常
            raise ExceptionConverter.to_sandbox_exception(e) from e
