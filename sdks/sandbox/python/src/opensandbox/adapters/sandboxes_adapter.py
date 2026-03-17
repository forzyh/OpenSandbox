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
沙箱服务适配器模块 - Sandboxes Adapter

本模块提供了 SandboxesAdapter 类，是沙箱管理服务的实现。

设计目的：
    - 实现 Sandboxes 服务接口，提供沙箱生命周期管理功能
    - 适配 openapi-python-client 自动生成的 API 客户端
    - 处理模型转换和错误映射，提供统一的异常处理

核心功能：
    - 创建沙箱：通过指定镜像、资源配置等创建新的沙箱实例
    - 获取信息：查询沙箱的详细信息和状态
    - 列出沙箱：分页查询所有沙箱列表
    - 获取端点：获取沙箱服务的网络访问地址
    - 暂停/恢复：暂停沙箱执行或恢复已暂停的沙箱
    - 续期：延长沙箱的过期时间
    - 终止：永久销毁沙箱并清理资源

架构说明：
    SandboxesAdapter 是 Sandboxes 服务接口的具体实现，它：
    1. 使用 openapi-python-client 生成的 AuthenticatedClient 进行 API 调用
    2. 使用自定义的 httpx.AsyncClient 进行底层 HTTP 通信
    3. 两个客户端共享同一个 transport 实例，确保连接池一致

    认证机制：
    - 使用 OPEN-SANDBOX-API-KEY 请求头进行身份验证
    - API 密钥从 ConnectionConfig 中获取

使用示例：
    ```python
    from opensandbox.config import ConnectionConfig
    from opensandbox.adapters.sandboxes_adapter import SandboxesAdapter

    config = ConnectionConfig(api_key="your-api-key", domain="api.opensandbox.io")
    adapter = SandboxesAdapter(config)

    # 创建沙箱
    response = await adapter.create_sandbox(
        spec=SandboxImageSpec("python:3.11"),
        entrypoint=["/bin/bash"],
        env={"KEY": "value"},
        metadata={"owner": "user123"},
        timeout=timedelta(minutes=30),
        resource={"cpu": "1", "memory": "2Gi"},
        network_policy=NetworkPolicy.ISOLATED,
        extensions={},
        volumes=None
    )

    # 获取沙箱信息
    info = await adapter.get_sandbox_info(sandbox_id)

    # 终止沙箱
    await adapter.kill_sandbox(sandbox_id)
    ```
"""

import logging
from datetime import datetime, timedelta

import httpx  # type: ignore[reportMissingImports]

# 导入异常转换器，用于将 API 异常转换为 SDK 标准异常
from opensandbox.adapters.converter.exception_converter import (
    ExceptionConverter,
)
# 导入响应处理器，用于处理 API 响应和错误
from opensandbox.adapters.converter.response_handler import (
    handle_api_error,
    require_parsed,
)
# 导入沙箱模型转换器，用于在领域模型和 API 模型之间转换
from opensandbox.adapters.converter.sandbox_model_converter import (
    SandboxModelConverter,
)
# 导入 UNSET 常量，用于处理可选参数
from opensandbox.api.lifecycle.types import UNSET
# 导入连接配置类
from opensandbox.config import ConnectionConfig
# 导入沙箱相关的模型类
from opensandbox.models.sandboxes import (
    NetworkPolicy,       # 网络策略：控制沙箱的网络访问权限
    PagedSandboxInfos,   # 分页的沙箱信息列表
    SandboxCreateResponse,  # 创建沙箱的响应
    SandboxEndpoint,     # 沙箱端点信息
    SandboxFilter,       # 沙箱查询过滤条件
    SandboxImageSpec,    # 沙箱镜像规格
    SandboxInfo,         # 沙箱详细信息
    SandboxRenewResponse,  # 续期沙箱的响应
    Volume,              # 卷挂载配置
)
# 导入沙箱服务接口定义
from opensandbox.services.sandbox import Sandboxes

# 配置模块日志记录器
logger = logging.getLogger(__name__)


class SandboxesAdapter(Sandboxes):
    """
    沙箱管理服务适配器 - Sandboxes 接口的实现

    本类提供了沙箱生命周期管理的完整实现，是业务逻辑与自动生成 API 客户端
    之间的适配层，负责所有模型转换和错误映射。

    继承关系：
        SandboxesAdapter 实现了 Sandboxes Protocol 接口，提供：
        - create_sandbox: 创建沙箱
        - get_sandbox_info: 获取沙箱信息
        - list_sandboxes: 列出沙箱
        - get_sandbox_endpoint: 获取沙箱端点
        - pause_sandbox: 暂停沙箱
        - resume_sandbox: 恢复沙箱
        - renew_sandbox_expiration: 续期沙箱
        - kill_sandbox: 终止沙箱

    技术实现：
        - 基于 openapi-python-client 生成的功能型 API
        - 支持自定义 httpx.AsyncClient 注入，实现细粒度的 HTTP 行为控制
        - 使用共享的 transport 实例，确保连接池一致性

    属性：
        connection_config (ConnectionConfig): 连接配置对象
            - 包含 API 密钥、域名、超时设置等
            - 包含共享的 transport 实例

    内部组件：
        _client (AuthenticatedClient): 认证客户端，用于调用生命周期 API
            - 自动处理 OPEN-SANDBOX-API-KEY 认证头
            - 由 openapi-python-client 生成
        _httpx_client (httpx.AsyncClient): 底层 HTTP 客户端
            - 由适配器拥有和管理
            - 注入到 _client 中使用

    使用示例：
        ```python
        config = ConnectionConfig(api_key="key", domain="api.opensandbox.io")
        adapter = SandboxesAdapter(config)

        # 创建沙箱
        response = await adapter.create_sandbox(
            spec=SandboxImageSpec("python:3.11"),
            ...
        )

        # 获取信息
        info = await adapter.get_sandbox_info(response.id)
        ```
    """

    def __init__(self, connection_config: ConnectionConfig) -> None:
        """
        初始化沙箱服务适配器

        构造函数负责创建和配置 HTTP 客户端，包括：
        1. 创建 AuthenticatedClient 用于 API 调用
        2. 创建 httpx.AsyncClient 用于底层 HTTP 通信
        3. 将 httpx 客户端注入到 AuthenticatedClient 中

        认证配置：
            - 使用 OPEN-SANDBOX-API-KEY 请求头进行认证
            - 不使用传统的 Bearer Token 前缀

        参数：
            connection_config (ConnectionConfig): 连接配置对象
                - base_url: API 基础 URL
                - api_key: 认证密钥（可选）
                - request_timeout: 请求超时时间
                - headers: 自定义请求头
                - transport: 共享的传输层实例

        内部实现细节：
            1. 从 connection_config 获取 API 密钥
            2. 配置超时时间（秒）
            3. 构建请求头，包括 User-Agent 和 API 密钥
            4. 创建 AuthenticatedClient，配置自定义认证头
            5. 创建 httpx.AsyncClient，共享 transport
            6. 将 httpx 客户端注入到 AuthenticatedClient

        示例：
            ```python
            config = ConnectionConfig(
                api_key="your-api-key",
                domain="api.opensandbox.io",
                request_timeout=timedelta(seconds=30)
            )
            adapter = SandboxesAdapter(config)
            ```
        """
        # 保存连接配置，后续创建其他客户端时使用
        self.connection_config = connection_config

        # 导入生命周期 API 的认证客户端
        # 这个客户端由 openapi-python-client 生成，专门用于沙箱生命周期管理 API
        from opensandbox.api.lifecycle import AuthenticatedClient

        # 获取 API 密钥（可能为 None）
        api_key = self.connection_config.get_api_key()

        # 将超时时间转换为秒（httpx 需要浮点数秒）
        timeout_seconds = self.connection_config.request_timeout.total_seconds()
        timeout = httpx.Timeout(timeout_seconds)

        # 构建请求头
        # 包含 User-Agent、自定义头，以及可选的 API 密钥
        headers = {
            "User-Agent": self.connection_config.user_agent,
            **self.connection_config.headers,
        }
        # 如果有 API 密钥，添加到请求头中
        if api_key:
            headers["OPEN-SANDBOX-API-KEY"] = api_key

        # 创建认证客户端
        # AuthenticatedClient 是 openapi-python-client 生成的客户端类
        # 配置说明：
        #   - base_url: API 的基础 URL
        #   - token: 认证令牌（这里使用 API 密钥）
        #   - prefix: 认证头前缀（空字符串表示不使用 Bearer 等前缀）
        #   - auth_header_name: 自定义认证头名称
        #   - timeout: 请求超时
        self._client = AuthenticatedClient(
            base_url=self.connection_config.get_base_url(),
            token=api_key or "",  # 如果没有密钥则使用空字符串
            prefix="",  # 不使用前缀，直接使用 API 密钥
            auth_header_name="OPEN-SANDBOX-API-KEY",  # 使用 OpenSandbox 自定义的认证头
            timeout=timeout,
        )

        # 创建 httpx 异步客户端
        # 这个客户端由适配器拥有和管理，用于底层 HTTP 通信
        # 配置说明：
        #   - base_url: API 基础 URL
        #   - headers: 请求头（包含认证信息）
        #   - timeout: 请求超时
        #   - transport: 共享的传输层，用于连接池管理
        self._httpx_client = httpx.AsyncClient(
            base_url=self.connection_config.get_base_url(),
            headers=headers,
            timeout=timeout,
            transport=self.connection_config.transport,  # 共享 transport
        )

        # 将 httpx 客户端注入到 AuthenticatedClient 中
        # 这样生成的 API 函数就会使用这个客户端进行 HTTP 调用
        self._client.set_async_httpx_client(self._httpx_client)

    async def _get_client(self):
        """
        获取认证客户端

        内部方法，返回用于调用生命周期 API 的认证客户端。

        返回：
            AuthenticatedClient: 配置好的认证客户端实例

        使用场景：
            每个 API 方法都会调用此方法获取客户端，然后使用生成的
            API 函数进行实际的 HTTP 请求。
        """
        return self._client

    async def create_sandbox(
        self,
        spec: SandboxImageSpec,
        entrypoint: list[str],
        env: dict[str, str],
        metadata: dict[str, str],
        timeout: timedelta | None,
        resource: dict[str, str],
        network_policy: NetworkPolicy | None,
        extensions: dict[str, str],
        volumes: list[Volume] | None,
    ) -> SandboxCreateResponse:
        """
        创建一个新的沙箱实例

        这是沙箱生命周期管理的入口方法，负责向 API 发送创建请求。

        参数说明：
            spec (SandboxImageSpec): 沙箱镜像规格
                - image: Docker 镜像名称（如 "python:3.11"）
                - auth: 可选的镜像认证信息（用于私有仓库）

            entrypoint (list[str]): 容器入口点命令
                - 指定容器启动时执行的命令
                - 例如：["/bin/bash", "-c", "echo hello"]

            env (dict[str, str]): 环境变量
                - 键值对形式的环境变量
                - 例如：{"PYTHONPATH": "/workspace", "DEBUG": "1"}

            metadata (dict[str, str]): 元数据标签
                - 用于标识和分类沙箱的自定义标签
                - 例如：{"owner": "user123", "project": "ml-training"}

            timeout (timedelta | None): 沙箱超时时间
                - 沙箱在无活动后自动销毁的时间
                - None 表示使用默认超时

            resource (dict[str, str]): 资源配置
                - cpu: CPU 核心数（如 "1", "0.5"）
                - memory: 内存大小（如 "2Gi", "512Mi"）

            network_policy (NetworkPolicy | None): 网络策略
                - 控制沙箱的网络访问权限
                - ISOLATED: 完全隔离
                - LIMITED: 有限访问
                - UNRESTRICTED: 无限制

            extensions (dict[str, str]): 扩展配置
                - 额外的配置选项
                - 例如：{"gpu": "nvidia-tesla-v100"}

            volumes (list[Volume] | None): 卷挂载配置
                - 指定要挂载到沙箱的存储卷
                - 例如：[Volume(name="data", mount_path="/data")]

        返回：
            SandboxCreateResponse: 创建响应
                - id: 新创建的沙箱 ID
                - state: 沙箱初始状态
                - created_at: 创建时间

        异常：
            SandboxException: 如果创建失败（如镜像不存在、资源不足）
            InvalidArgumentException: 如果参数无效

        示例：
            ```python
            response = await adapter.create_sandbox(
                spec=SandboxImageSpec("python:3.11"),
                entrypoint=["/bin/bash"],
                env={"PYTHONPATH": "/workspace"},
                metadata={"owner": "user123"},
                timeout=timedelta(minutes=30),
                resource={"cpu": "1", "memory": "2Gi"},
                network_policy=NetworkPolicy.ISOLATED,
                extensions={},
                volumes=None
            )
            print(f"Created sandbox: {response.id}")
            ```
        """
        # 记录创建日志
        logger.info(f"Creating sandbox with image: {spec.image}")

        try:
            # 导入创建沙箱的 API 函数
            # 这个函数由 openapi-python-client 生成
            from opensandbox.api.lifecycle.api.sandboxes import post_sandboxes

            # 将领域模型转换为 API 模型
            # SandboxModelConverter 负责模型转换，处理字段映射和类型转换
            create_request = SandboxModelConverter.to_api_create_sandbox_request(
                spec=spec,
                entrypoint=entrypoint,
                env=env,
                metadata=metadata,
                timeout=timeout,
                resource=resource,
                network_policy=network_policy,
                extensions=extensions,
                volumes=volumes,
            )

            # 获取认证客户端
            client = await self._get_client()

            # 调用生成的 API 函数创建沙箱
            # _detailed 版本返回完整的响应对象，包含状态码、响应头等
            response_obj = await post_sandboxes.asyncio_detailed(
                client=client,
                body=create_request,
            )

            # 处理 API 错误
            # 如果响应状态码表示错误，抛出适当的异常
            handle_api_error(response_obj, "Create sandbox")

            # 导入响应模型
            from opensandbox.api.lifecycle.models import CreateSandboxResponse

            # 解析响应体并转换为领域模型
            # require_parsed 确保响应已成功解析
            parsed = require_parsed(response_obj, CreateSandboxResponse, "Create sandbox")

            # 将 API 响应模型转换为 SDK 领域模型
            response = SandboxModelConverter.to_sandbox_create_response(parsed)

            # 记录成功日志
            logger.info(f"Successfully created sandbox: {response.id}")
            return response

        except Exception as e:
            # 记录错误日志
            logger.error(
                f"Failed to create sandbox with image: {spec.image}", exc_info=e
            )
            # 将异常转换为 SDK 标准异常
            raise ExceptionConverter.to_sandbox_exception(e) from e

    async def get_sandbox_info(self, sandbox_id: str) -> SandboxInfo:
        """
        获取沙箱的详细信息

        查询指定沙箱的完整信息，包括状态、资源配置、元数据等。

        参数：
            sandbox_id (str): 沙箱的唯一标识符

        返回：
            SandboxInfo: 沙箱详细信息
                - id: 沙箱 ID
                - state: 当前状态（RUNNING、PAUSED、STOPPED 等）
                - image: 镜像名称
                - created_at: 创建时间
                - expires_at: 过期时间
                - resource: 资源配置
                - metadata: 元数据标签
                - endpoints: 网络端点列表

        异常：
            SandboxException: 如果沙箱不存在或查询失败

        示例：
            ```python
            info = await adapter.get_sandbox_info("sandbox-123")
            print(f"State: {info.state}")
            print(f"Image: {info.image}")
            print(f"CPU: {info.resource.get('cpu')}")
            ```
        """
        # 记录调试日志
        logger.debug(f"Retrieving sandbox information: {sandbox_id}")

        try:
            # 导入获取沙箱详情的 API 函数
            from opensandbox.api.lifecycle.api.sandboxes import get_sandboxes_sandbox_id

            # 获取认证客户端
            client = await self._get_client()

            # 调用 API 获取沙箱信息
            response_obj = await get_sandboxes_sandbox_id.asyncio_detailed(
                client=client,
                sandbox_id=sandbox_id,
            )

            # 处理 API 错误
            handle_api_error(response_obj, f"Get sandbox {sandbox_id}")

            # 导入响应模型
            from opensandbox.api.lifecycle.models import Sandbox

            # 解析并转换响应
            parsed = require_parsed(response_obj, Sandbox, f"Get sandbox {sandbox_id}")
            return SandboxModelConverter.to_sandbox_info(parsed)

        except Exception as e:
            # 记录错误日志
            logger.error(f"Failed to get sandbox info: {sandbox_id}", exc_info=e)
            raise ExceptionConverter.to_sandbox_exception(e) from e

    async def list_sandboxes(self, filter: SandboxFilter) -> PagedSandboxInfos:
        """
        列出沙箱（支持分页和过滤）

        查询所有沙箱的列表，支持按状态、元数据过滤，支持分页。

        参数：
            filter (SandboxFilter): 过滤条件
                - states: 按状态过滤（如 [State.RUNNING, State.PAUSED]）
                - metadata: 按元数据标签过滤（键值对）
                - page: 页码（从 1 开始）
                - page_size: 每页数量

        返回：
            PagedSandboxInfos: 分页的沙箱信息
                - items: 沙箱信息列表
                - total: 总数
                - page: 当前页码
                - page_size: 每页数量

        示例：
            ```python
            # 查询所有运行中的沙箱
            filter = SandboxFilter(states=[State.RUNNING])
            result = await adapter.list_sandboxes(filter)

            for info in result.items:
                print(f"{info.id}: {info.state}")

            # 按元数据过滤
            filter = SandboxFilter(
                metadata={"owner": "user123"},
                page=1,
                page_size=10
            )
            result = await adapter.list_sandboxes(filter)
            ```
        """
        # 记录调试日志
        logger.debug(f"Listing sandboxes with filter: {filter}")

        # 准备 metadata 参数
        # 与 Kotlin SDK 实现保持一致，将字典转换为 "key=value&key2=value2" 格式
        metadata = UNSET
        if filter.metadata:
            metadata_parts: list[str] = []
            for key, value in filter.metadata.items():
                metadata_parts.append(f"{key}={value}")
            metadata = "&".join(metadata_parts)

        try:
            # 导入列出沙箱的 API 函数
            from opensandbox.api.lifecycle.api.sandboxes import get_sandboxes
            # 导入 API 类型的 UNSET 常量
            from opensandbox.api.lifecycle.types import UNSET as API_UNSET

            # 获取认证客户端
            client = await self._get_client()

            # 调用 API 列出沙箱
            # 使用 API_UNSET 处理可选参数（与生成的 API 类型系统兼容）
            response_obj = await get_sandboxes.asyncio_detailed(
                client=client,
                state=filter.states if filter.states else API_UNSET,
                metadata=metadata,
                page=filter.page if filter.page is not None else API_UNSET,
                page_size=filter.page_size if filter.page_size is not None else API_UNSET,
            )

            # 处理 API 错误
            handle_api_error(response_obj, "List sandboxes")

            # 导入响应模型
            from opensandbox.api.lifecycle.models import ListSandboxesResponse

            # 解析并转换响应
            parsed = require_parsed(response_obj, ListSandboxesResponse, "List sandboxes")
            return SandboxModelConverter.to_paged_sandbox_infos(parsed)

        except Exception as e:
            # 记录错误日志
            logger.error("Failed to list sandboxes", exc_info=e)
            raise ExceptionConverter.to_sandbox_exception(e) from e

    async def get_sandbox_endpoint(
        self, sandbox_id: str, port: int, use_server_proxy: bool = False
    ) -> SandboxEndpoint:
        """
        获取沙箱的网络端点信息

        获取指定端口的网络访问地址，用于访问沙箱内运行的服务。

        参数：
            sandbox_id (str): 沙箱 ID
            port (int): 端口号（如 8080、443 等）
            use_server_proxy (bool): 是否使用服务器代理
                - True: 返回代理端点（通过 API 网关访问）
                - False: 返回直接端点（直接访问沙箱 IP）
                默认为 False，返回直接访问地址

        返回：
            SandboxEndpoint: 端点信息
                - endpoint: 访问地址（host:port 格式）
                - headers: 访问该端点所需的请求头

        示例：
            ```python
            # 获取沙箱的 HTTP 服务端点
            endpoint = await adapter.get_sandbox_endpoint(
                "sandbox-123",
                port=8080
            )
            print(f"Access URL: http://{endpoint.endpoint}")

            # 使用服务器代理（适用于私有网络中的沙箱）
            endpoint = await adapter.get_sandbox_endpoint(
                "sandbox-123",
                port=8080,
                use_server_proxy=True
            )
            ```
        """
        # 记录调试日志
        logger.debug(f"Retrieving sandbox endpoint: {sandbox_id}, port {port}")

        try:
            # 导入获取端点的 API 函数
            from opensandbox.api.lifecycle.api.sandboxes import (
                get_sandboxes_sandbox_id_endpoints_port,
            )

            # 获取认证客户端
            client = await self._get_client()

            # 调用 API 获取端点信息
            response_obj = (
                await get_sandboxes_sandbox_id_endpoints_port.asyncio_detailed(
                    client=client,
                    sandbox_id=sandbox_id,
                    port=port,
                    use_server_proxy=use_server_proxy,
                )
            )

            # 处理 API 错误
            handle_api_error(
                response_obj, f"Get endpoint for sandbox {sandbox_id} port {port}"
            )

            # 导入响应模型
            from opensandbox.api.lifecycle.models import Endpoint

            # 解析并转换响应
            parsed = require_parsed(response_obj, Endpoint, "Get endpoint")
            return SandboxModelConverter.to_sandbox_endpoint(parsed)

        except Exception as e:
            # 记录错误日志
            logger.error(
                f"Failed to retrieve sandbox endpoint for sandbox {sandbox_id}",
                exc_info=e,
            )
            raise ExceptionConverter.to_sandbox_exception(e) from e

    async def pause_sandbox(self, sandbox_id: str) -> None:
        """
        暂停沙箱（保留状态）

        暂停正在运行的沙箱，保存其当前状态。暂停后可以恢复。

        适用场景：
            - 临时停止计算以节省资源
            - 保存中间状态供后续继续

        参数：
            sandbox_id (str): 沙箱 ID

        异常：
            SandboxException: 如果暂停失败（如沙箱已停止）

        示例：
            ```python
            await adapter.pause_sandbox("sandbox-123")
            print("Sandbox paused")
            ```
        """
        # 记录信息日志
        logger.info(f"Pausing sandbox: {sandbox_id}")

        try:
            # 导入暂停沙箱的 API 函数
            from opensandbox.api.lifecycle.api.sandboxes import (
                post_sandboxes_sandbox_id_pause,
            )

            # 获取认证客户端
            client = await self._get_client()

            # 调用 API 暂停沙箱
            response_obj = await post_sandboxes_sandbox_id_pause.asyncio_detailed(
                client=client,
                sandbox_id=sandbox_id,
            )

            # 处理 API 错误
            handle_api_error(response_obj, f"Pause sandbox {sandbox_id}")

            # 记录成功日志
            logger.info(f"Initiated pause for sandbox: {sandbox_id}")

        except Exception as e:
            # 记录错误日志
            logger.error(f"Failed to initiate pause sandbox: {sandbox_id}", exc_info=e)
            raise ExceptionConverter.to_sandbox_exception(e) from e

    async def resume_sandbox(self, sandbox_id: str) -> None:
        """
        恢复已暂停的沙箱

        恢复之前被暂停的沙箱，继续其执行。

        适用场景：
            - 继续之前暂停的计算任务
            - 激活休眠的沙箱实例

        参数：
            sandbox_id (str): 沙箱 ID

        异常：
            SandboxException: 如果恢复失败（如沙箱未暂停）

        示例：
            ```python
            await adapter.resume_sandbox("sandbox-123")
            print("Sandbox resumed")
            ```
        """
        # 记录信息日志
        logger.info(f"Resuming sandbox: {sandbox_id}")

        try:
            # 导入恢复沙箱的 API 函数
            from opensandbox.api.lifecycle.api.sandboxes import (
                post_sandboxes_sandbox_id_resume,
            )

            # 获取认证客户端
            client = await self._get_client()

            # 调用 API 恢复沙箱
            response_obj = await post_sandboxes_sandbox_id_resume.asyncio_detailed(
                client=client,
                sandbox_id=sandbox_id,
            )

            # 处理 API 错误
            handle_api_error(response_obj, f"Resume sandbox {sandbox_id}")

            # 记录成功日志
            logger.info(f"Initiated resume for sandbox: {sandbox_id}")

        except Exception as e:
            # 记录错误日志
            logger.error(f"Failed initiate resume sandbox: {sandbox_id}", exc_info=e)
            raise ExceptionConverter.to_sandbox_exception(e) from e

    async def renew_sandbox_expiration(
        self, sandbox_id: str, new_expiration_time: datetime
    ) -> SandboxRenewResponse:
        """
        延长沙箱的过期时间

        为沙箱设置新的过期时间，防止其被自动清理。

        适用场景：
            - 长期运行的任务需要延长存活时间
            - 重要沙箱需要保留更长时间

        参数：
            sandbox_id (str): 沙箱 ID
            new_expiration_time (datetime): 新的过期时间
                - 必须是未来的时间点
                - 格式：datetime 对象

        返回：
            SandboxRenewResponse: 续期响应
                - id: 沙箱 ID
                - expires_at: 新的过期时间

        示例：
            ```python
            from datetime import datetime, timedelta

            # 延长 1 小时
            new_time = datetime.now() + timedelta(hours=1)
            response = await adapter.renew_sandbox_expiration(
                "sandbox-123",
                new_time
            )
            print(f"New expiration: {response.expires_at}")
            ```
        """
        # 记录信息日志
        logger.info(f"Renew sandbox {sandbox_id} expiration to {new_expiration_time}")

        try:
            # 导入续期 API 函数
            from opensandbox.api.lifecycle.api.sandboxes import (
                post_sandboxes_sandbox_id_renew_expiration,
            )
            # 导入续期响应模型
            from opensandbox.api.lifecycle.models.renew_sandbox_expiration_response import (
                RenewSandboxExpirationResponse,
            )

            # 将时间转换为 API 请求模型
            renew_request = SandboxModelConverter.to_api_renew_request(
                new_expiration_time
            )

            # 获取认证客户端
            client = await self._get_client()

            # 调用 API 续期沙箱
            response_obj = (
                await post_sandboxes_sandbox_id_renew_expiration.asyncio_detailed(
                    client=client,
                    sandbox_id=sandbox_id,
                    body=renew_request,
                )
            )

            # 处理 API 错误
            handle_api_error(response_obj, f"Renew sandbox {sandbox_id} expiration")

            # 解析响应
            parsed = require_parsed(
                response_obj,
                RenewSandboxExpirationResponse,
                f"Renew sandbox {sandbox_id} expiration",
            )

            # 转换为领域模型
            renew_response = SandboxModelConverter.to_sandbox_renew_response(parsed)

            # 记录成功日志
            logger.info(
                "Successfully renewed sandbox %s expiration to %s",
                sandbox_id,
                renew_response.expires_at,
            )
            return renew_response

        except Exception as e:
            # 记录错误日志
            logger.error(f"Failed to renew sandbox {sandbox_id} expiration", exc_info=e)
            raise ExceptionConverter.to_sandbox_exception(e) from e

    async def kill_sandbox(self, sandbox_id: str) -> None:
        """
        永久终止沙箱并清理资源

        彻底销毁沙箱实例，释放所有分配的资源。这是一个不可逆操作。

        重要说明：
            - 此操作不可逆，沙箱数据将永久丢失
            - 必须在不再需要沙箱时显式调用
            - 沙箱到期后也会被自动清理

        参数：
            sandbox_id (str): 沙箱 ID

        异常：
            SandboxException: 如果终止失败

        示例：
            ```python
            # 使用完毕后清理沙箱
            await adapter.kill_sandbox("sandbox-123")
            print("Sandbox terminated")
            ```

        资源管理最佳实践：
            ```python
            sandbox = await Sandbox.create("python:3.11")
            try:
                # 使用沙箱...
                pass
            finally:
                # 确保清理资源
                await sandbox.kill()
                await sandbox.close()
            ```
        """
        # 记录信息日志
        logger.info(f"Terminating sandbox: {sandbox_id}")

        try:
            # 导入删除沙箱的 API 函数
            from opensandbox.api.lifecycle.api.sandboxes import (
                delete_sandboxes_sandbox_id,
            )

            # 获取认证客户端
            client = await self._get_client()

            # 调用 API 删除沙箱
            response_obj = await delete_sandboxes_sandbox_id.asyncio_detailed(
                client=client,
                sandbox_id=sandbox_id,
            )

            # 处理 API 错误
            handle_api_error(response_obj, f"Kill sandbox {sandbox_id}")

            # 记录成功日志
            logger.info(f"Successfully terminated sandbox: {sandbox_id}")

        except Exception as e:
            # 记录错误日志
            logger.error(f"Failed to terminate sandbox: {sandbox_id}", exc_info=e)
            raise ExceptionConverter.to_sandbox_exception(e) from e
