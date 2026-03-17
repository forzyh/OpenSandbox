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
健康检查服务适配器模块 - Health Adapter

本模块提供了 HealthAdapter 类，是健康检查服务的实现。

设计目的：
    - 实现 Health 服务接口，提供沙箱健康检查功能
    - 适配 openapi-python-client 自动生成的 HealthApi
    - 验证沙箱的可用性和响应性

核心功能：
    - 健康检查：通过 ping 端点验证沙箱是否存活
    - 响应性检测：确认沙箱能够正常响应请求

架构说明：
    HealthAdapter 是 Health 服务接口的具体实现，它：
    1. 使用 openapi-python-client 生成的 Client 进行 API 调用
    2. 使用自定义的 httpx.AsyncClient 进行底层 HTTP 通信
    3. Execd API 不需要认证（认证在沙箱层面完成）

使用示例：
    ```python
    from opensandbox.config import ConnectionConfig
    from opensandbox.adapters.health_adapter import HealthAdapter

    config = ConnectionConfig(api_key="key", domain="api.opensandbox.io")
    adapter = HealthAdapter(config, endpoint)

    # 检查沙箱健康状态
    is_healthy = await adapter.ping(sandbox_id)
    if is_healthy:
        print("Sandbox is healthy")
    else:
        print("Sandbox is not responding")
    ```
"""

import logging

import httpx

from opensandbox.config import ConnectionConfig
from opensandbox.models.sandboxes import SandboxEndpoint
from opensandbox.services.health import Health

# 配置模块日志记录器
logger = logging.getLogger(__name__)


class HealthAdapter(Health):
    """
    健康检查服务适配器 - Health 接口的实现

    本类提供了沙箱健康检查的完整实现，用于验证沙箱的可用性和响应性。

    继承关系：
        HealthAdapter 实现了 Health Protocol 接口，提供：
        - ping: 检查沙箱是否存活且能够响应

    技术实现：
        - 基于 openapi-python-client 生成的功能型 API
        - 使用 httpx 进行底层 HTTP 通信
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
        adapter = HealthAdapter(config, endpoint)

        # 检查沙箱健康状态
        is_healthy = await adapter.ping(sandbox_id)
        print(f"Sandbox health status: {is_healthy}")
        ```
    """

    def __init__(
        self,
        connection_config: ConnectionConfig,
        execd_endpoint: SandboxEndpoint,
    ) -> None:
        """
        初始化健康检查服务适配器

        构造函数负责创建和配置 HTTP 客户端，用于健康检查 API 调用。

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
            adapter = HealthAdapter(config, endpoint)
            ```
        """
        # 保存配置和端点，后续方法使用
        self.connection_config = connection_config
        self.execd_endpoint = execd_endpoint

        # 导入 Execd API 客户端
        # 这个客户端由 openapi-python-client 生成，用于执行健康检查相关 API
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

    async def ping(self, sandbox_id: str) -> bool:
        """
        检查沙箱是否存活且能够响应

        通过调用 Execd API 的 ping 端点来验证沙箱的健康状态。
        如果沙箱能够正常响应 ping 请求，则认为沙箱是健康的。

        参数：
            sandbox_id (str): 要检查的沙箱唯一标识符
                - 用于日志记录，帮助追踪问题

        返回：
            bool: 沙箱健康状态
                - True: 沙箱存活且能够响应
                - False: 沙箱不健康或无法响应

        异常：
            不会抛出异常，所有错误都会被捕获并返回 False

        使用示例：
            ```python
            adapter = HealthAdapter(config, endpoint)

            # 检查沙箱健康状态
            is_healthy = await adapter.ping(sandbox_id)
            if is_healthy:
                print("Sandbox is healthy and responsive")
            else:
                print("Sandbox is not responding or unhealthy")
            ```

        注意事项：
            - 此方法会捕获所有异常并返回 False
            - 适合用于健康检查循环或监控场景
            - 失败时会记录调试日志，便于排查问题
        """
        try:
            # 导入响应处理器
            from opensandbox.adapters.converter.response_handler import (
                handle_api_error,
            )
            # 导入 ping 的 API 函数
            from opensandbox.api.execd.api.health import ping

            # 获取 API 客户端
            client = await self._get_client()

            # 调用 API 进行健康检查
            # asyncio_detailed 版本返回完整的响应对象，包含状态码和头信息
            response_obj = await ping.asyncio_detailed(client=client)

            # 处理 API 错误
            # 如果响应状态码不是 200，会抛出异常
            handle_api_error(response_obj, "Ping")

            # 如果 API 调用成功，返回 True
            return True

        except Exception as e:
            # 记录调试日志
            # 健康检查失败是常见情况（如沙箱已停止），使用 debug 级别
            logger.debug(f"Health check failed for sandbox {sandbox_id}: {e}")
            # 返回 False 表示沙箱不健康
            return False
