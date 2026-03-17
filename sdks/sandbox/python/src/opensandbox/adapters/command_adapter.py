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
命令服务适配器模块 - Command Adapter

本模块提供了 CommandsAdapter 类，是命令执行服务的实现。

设计目的：
    - 实现 Commands 服务接口，提供沙箱内命令执行功能
    - 适配 openapi-python-client 自动生成的 CommandApi
    - 处理 SSE（Server-Sent Events）流式响应的解析
    - 提供同步和流式两种执行模式

核心功能：
    - 命令执行：在沙箱内运行 Shell 命令
    - 流式输出：实时获取命令的 stdout/stderr 输出
    - 中断命令：停止正在运行的命令
    - 状态查询：获取命令执行状态
    - 日志获取：获取后台命令的执行日志

架构说明：
    CommandsAdapter 是 Commands 服务接口的具体实现，它：
    1. 使用 openapi-python-client 生成的 Client 进行 API 调用
    2. 使用自定义的 httpx.AsyncClient 进行底层 HTTP 通信
    3. 使用专用的 SSE 客户端处理流式响应

    HTTP 客户端设计：
        - _client: 标准 API 客户端，用于简单操作（如 interrupt）
        - _httpx_client: 底层 HTTP 客户端，注入到 _client 中使用
        - _sse_client: 专用的 SSE 客户端，禁用读超时，用于命令执行的流式响应

    SSE 处理机制：
        命令执行返回 Server-Sent Events 格式的流式响应，每个事件包含：
        - 执行状态更新
        - stdout/stderr 输出
        - 错误信息
        - 执行完成信号

        适配器使用 ExecutionEventDispatcher 解析和分发这些事件。

认证说明：
    Execd API（执行守护进程）不需要认证，因为认证已在沙箱创建时完成。
    所有请求通过沙箱端点发送，该端点已经过身份验证。

使用示例：
    ```python
    from opensandbox.config import ConnectionConfig
    from opensandbox.adapters.command_adapter import CommandsAdapter
    from opensandbox.models.execd import RunCommandOpts, ExecutionHandlers

    config = ConnectionConfig(api_key="key", domain="api.opensandbox.io")
    adapter = CommandsAdapter(config, endpoint)

    # 执行命令（同步模式）
    result = await adapter.run("ls -la")
    print(result.logs.stdout)

    # 执行命令（带选项）
    result = await adapter.run(
        "python script.py",
        opts=RunCommandOpts(
            timeout=timedelta(minutes=5),
            env={"PYTHONPATH": "/workspace"}
        )
    )

    # 执行命令（带流式处理器）
    async def on_stdout(line: str):
        print(f"STDOUT: {line}")

    result = await adapter.run(
        "python long_running.py",
        handlers=ExecutionHandlers(on_stdout=on_stdout)
    )

    # 中断命令
    await adapter.interrupt(execution_id)

    # 获取命令状态
    status = await adapter.get_command_status(execution_id)
    ```
"""

import json
import logging

import httpx

# 导入命令状态转换器
from opensandbox.adapters.converter.command_model_converter import (
    to_command_status,
)
# 导入事件节点类，用于表示 SSE 事件
from opensandbox.adapters.converter.event_node import EventNode
# 导入异常转换器
from opensandbox.adapters.converter.exception_converter import (
    ExceptionConverter,
)
# 导入执行转换器，用于将领域模型转换为 API 模型
from opensandbox.adapters.converter.execution_converter import (
    ExecutionConverter,
)
# 导入执行事件分发器，用于解析和分发 SSE 事件
from opensandbox.adapters.converter.execution_event_dispatcher import (
    ExecutionEventDispatcher,
)
# 导入响应处理器
from opensandbox.adapters.converter.response_handler import (
    extract_request_id,
    handle_api_error,
)
# 导入连接配置
from opensandbox.config import ConnectionConfig
# 导入异常类
from opensandbox.exceptions import InvalidArgumentException, SandboxApiException
# 导入命令执行相关的模型
from opensandbox.models.execd import (
    CommandLogs,          # 命令日志（内容和游标）
    CommandStatus,        # 命令执行状态
    Execution,            # 执行结果（包含输出、错误等）
    ExecutionHandlers,    # 执行处理器（流式回调函数）
    RunCommandOpts,       # 命令执行选项
)
from opensandbox.models.sandboxes import SandboxEndpoint
# 导入命令服务接口定义
from opensandbox.services.command import Commands

# 配置模块日志记录器
logger = logging.getLogger(__name__)


class CommandsAdapter(Commands):
    """
    命令执行服务适配器 - Commands 接口的实现

    本类提供了在沙箱内执行 Shell 命令的完整实现，支持同步和流式两种模式。

    继承关系：
        CommandsAdapter 实现了 Commands Protocol 接口，提供：
        - run: 执行命令（支持流式输出）
        - interrupt: 中断正在运行的命令
        - get_command_status: 获取命令状态
        - get_background_command_logs: 获取后台命令日志

    技术实现：
        - 基于 openapi-python-client 生成的功能型 API
        - 使用直接 httpx 流式处理命令执行，正确处理 SSE 响应
        - 简单操作（如 interrupt）使用生成的 API 客户端

    HTTP 客户端架构：
        _client (Client): 标准 API 客户端
            - 用于简单操作（interrupt、get_command_status 等）
            - 由 openapi-python-client 生成
            - 注入 _httpx_client 进行底层通信

        _httpx_client (httpx.AsyncClient): 底层 HTTP 客户端
            - 用于标准 API 调用
            - 使用正常超时设置
            - 共享 connection_config 的 transport

        _sse_client (httpx.AsyncClient): SSE 专用客户端
            - 用于命令执行的流式响应
            - 禁用读超时（因为命令执行时间不确定）
            - 设置 Accept: text/event-stream 头

    属性：
        connection_config (ConnectionConfig): 连接配置
        execd_endpoint (SandboxEndpoint): Execd 服务端点

    使用示例：
        ```python
        adapter = CommandsAdapter(config, endpoint)

        # 执行命令
        result = await adapter.run("ls -la")
        print(f"Exit code: {result.exit_code}")
        print(f"Output: {result.logs.stdout}")

        # 带流式处理的执行
        async def on_stdout(line):
            print(line)

        result = await adapter.run(
            "python script.py",
            handlers=ExecutionHandlers(on_stdout=on_stdout)
        )
        ```
    """

    # API 路径常量
    # 命令执行端点
    RUN_COMMAND_PATH = "/command"
    # 命令中断端点（需要执行 ID）
    INTERRUPT_COMMAND_PATH = "/command/{execution_id}/interrupt"

    def __init__(
        self,
        connection_config: ConnectionConfig,
        execd_endpoint: SandboxEndpoint,
    ) -> None:
        """
        初始化命令服务适配器

        构造函数负责创建和配置三种 HTTP 客户端：
        1. _client: 标准 API 客户端（用于简单操作）
        2. _httpx_client: 底层 HTTP 客户端（注入到 _client）
        3. _sse_client: SSE 专用客户端（用于流式命令执行）

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

            3. _sse_client (SSE 专用客户端):
               - 禁用读超时（命令执行时间不确定）
               - 设置 Accept: text/event-stream
               - 设置 Cache-Control: no-cache
               - 共享 connection_config 的 transport

        示例：
            ```python
            config = ConnectionConfig(
                api_key="your-api-key",
                domain="api.opensandbox.io"
            )
            endpoint = await sandbox.get_endpoint(DEFAULT_EXECD_PORT)
            adapter = CommandsAdapter(config, endpoint)
            ```
        """
        # 保存配置和端点，后续方法使用
        self.connection_config = connection_config
        self.execd_endpoint = execd_endpoint

        # 导入 Execd API 客户端
        # 这个客户端由 openapi-python-client 生成，用于执行命令相关 API
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

        # 创建 SSE 专用客户端
        # 用于命令执行的流式响应处理
        # 配置说明：
        #   - headers: 添加 SSE 特定的请求头
        #     - Accept: text/event-stream (告诉服务器我们期望 SSE 响应)
        #     - Cache-Control: no-cache (禁用缓存，确保实时接收事件)
        #   - timeout: 特殊的超时配置
        #     - connect: 连接超时（正常）
        #     - read: None (禁用读超时，因为命令执行时间不确定)
        #     - write: 写超时（正常）
        #     - pool: 连接池超时（正常）
        #   - transport: 共享的传输层
        sse_headers = {
            **headers,
            "Accept": "text/event-stream",      # 期望 SSE 响应
            "Cache-Control": "no-cache",        # 禁用缓存
        }
        self._sse_client = httpx.AsyncClient(
            headers=sse_headers,
            timeout=httpx.Timeout(
                connect=timeout_seconds,        # 连接超时正常
                read=None,                      # 读超时禁用（重要！）
                write=timeout_seconds,          # 写超时正常
                pool=None,                      # 连接池超时正常
            ),
            transport=self.connection_config.transport,
        )

    async def _get_client(self):
        """
        获取 API 客户端

        内部方法，返回用于调用 Execd API 的客户端。
        Execd API 不需要认证。

        返回：
            Client: 配置好的 API 客户端实例
        """
        return self._client

    def _get_execd_url(self, path: str) -> str:
        """
        构建 Execd 端点的完整 URL

        辅助方法，将相对路径转换为完整的 URL。

        参数：
            path (str): 相对路径（如 "/command"）

        返回：
            str: 完整的 URL（如 "http://192.168.1.1:8080/command"）

        示例：
            ```python
            url = self._get_execd_url("/command")
            # 返回：http://192.168.1.1:8080/command
            ```
        """
        protocol = self.connection_config.protocol
        return f"{protocol}://{self.execd_endpoint.endpoint}{path}"

    async def _get_sse_client(self) -> httpx.AsyncClient:
        """
        获取 SSE 客户端

        内部方法，返回用于 SSE 流式响应的客户端。
        此客户端已禁用读超时，适合长时间运行的命令执行。

        返回：
            httpx.AsyncClient: SSE 专用客户端实例
        """
        return self._sse_client

    async def run(
        self,
        command: str,
        *,
        opts: RunCommandOpts | None = None,
        handlers: ExecutionHandlers | None = None,
    ) -> Execution:
        """
        在沙箱内执行 Shell 命令

        这是命令执行的核心方法，支持同步和流式两种模式。

        执行流程：
            1. 验证命令不为空
            2. 将命令和选项转换为 API 请求格式
            3. 使用 SSE 客户端发送 POST 请求
            4. 逐行解析 SSE 响应
            5. 使用 EventDispatcher 分发事件
            6. 收集执行结果并返回

        SSE 事件类型：
            - execution.created: 执行创建事件（包含 execution_id）
            - execution.stdout: 标准输出事件
            - execution.stderr: 标准错误事件
            - execution.completed: 执行完成事件（包含退出码）
            - execution.error: 执行错误事件

        参数：
            command (str): 要执行的 Shell 命令
                - 例如："ls -la"、"python script.py"
                - 不能为空或只包含空白字符

            opts (RunCommandOpts | None): 执行选项（可选）
                - timeout: 命令超时时间
                - env: 环境变量
                - working_dir: 工作目录
                - user: 运行用户
                - 默认为 None，使用默认选项

            handlers (ExecutionHandlers | None): 流式处理器（可选）
                - on_stdout: 标准输出回调函数
                - on_stderr: 标准错误回调函数
                - on_event: 通用事件回调函数
                - 默认为 None，不启用流式处理

        返回：
            Execution: 执行结果对象
                - id: 执行 ID
                - execution_count: 执行计数
                - result: 执行结果列表
                - error: 错误信息（如果有）
                - logs.stdout: 标准输出列表
                - logs.stderr: 标准错误列表
                - exit_code: 退出码

        异常：
            InvalidArgumentException: 如果命令为空
            SandboxException: 如果执行失败
            SandboxApiException: 如果 API 调用失败

        使用示例：
            ```python
            # 基本用法
            result = await adapter.run("ls -la")
            print(f"Exit code: {result.exit_code}")
            for line in result.logs.stdout:
                print(line.text)

            # 带选项
            from datetime import timedelta
            result = await adapter.run(
                "python script.py",
                opts=RunCommandOpts(
                    timeout=timedelta(minutes=5),
                    env={"PYTHONPATH": "/workspace"},
                    working_dir="/app"
                )
            )

            # 带流式处理
            async def on_stdout(line: str):
                print(f"STDOUT: {line}")

            async def on_stderr(line: str):
                print(f"STDERR: {line}")

            result = await adapter.run(
                "python long_running.py",
                handlers=ExecutionHandlers(
                    on_stdout=on_stdout,
                    on_stderr=on_stderr
                )
            )
            ```
        """
        # 验证命令不为空
        # 空命令或只包含空白字符的命令没有意义，直接抛出异常
        if not command.strip():
            raise InvalidArgumentException("Command cannot be empty")

        try:
            # 使用默认选项（如果未提供）
            opts = opts or RunCommandOpts()

            # 将领域模型转换为 API 请求的 JSON 格式
            # ExecutionConverter 负责：
            #   - 将 RunCommandOpts 转换为 API 请求体
            #   - 处理超时时间格式化
            #   - 处理环境变量序列化
            json_body = ExecutionConverter.to_api_run_command_json(command, opts)

            # 构建执行 URL
            url = self._get_execd_url(self.RUN_COMMAND_PATH)

            # 创建空的 Execution 对象用于收集结果
            # 随着 SSE 事件的解析，这个对象会被逐步填充
            execution = Execution(
                id=None,              # 执行 ID（从事件中获取）
                execution_count=None, # 执行计数（从事件中获取）
                result=[],            # 执行结果列表
                error=None,           # 错误信息
            )

            # 获取 SSE 客户端（已禁用读超时）
            # 使用流式客户端是因为命令执行可能持续很长时间
            client = await self._get_sse_client()

            # 发送 POST 请求，使用流式响应
            # stream=True 表示我们不立即读取整个响应，而是逐行处理
            async with client.stream("POST", url, json=json_body) as response:
                # 检查响应状态码
                if response.status_code != 200:
                    # 读取错误响应体
                    await response.aread()
                    error_body = response.text
                    logger.error(
                        f"Failed to run command. Status: {response.status_code}, Body: {error_body}"
                    )
                    # 抛出 API 异常
                    raise SandboxApiException(
                        message=f"Failed to run command. Status code: {response.status_code}",
                        status_code=response.status_code,
                        request_id=extract_request_id(response.headers),
                    )

                # 创建事件分发器
                # ExecutionEventDispatcher 负责：
                #   - 解析 SSE 事件
                #   - 调用用户提供的处理器（handlers）
                #   - 更新 execution 对象
                dispatcher = ExecutionEventDispatcher(execution, handlers)

                # 逐行读取 SSE 响应
                # aiter_lines() 异步迭代响应的每一行
                async for line in response.aiter_lines():
                    # 跳过空行
                    if not line.strip():
                        continue

                    # 处理 SSE 格式
                    # SSE 事件格式： "data: {...}"
                    # 需要移除 "data: " 前缀
                    data = line
                    if data.startswith("data:"):
                        data = data[5:].strip()  # 移除 "data: " 前缀

                    try:
                        # 解析 JSON 事件
                        event_dict = json.loads(data)

                        # 创建事件节点对象
                        # EventNode 是事件的领域模型表示
                        event_node = EventNode(**event_dict)

                        # 分发事件到处理器
                        # 根据事件类型调用相应的处理器
                        await dispatcher.dispatch(event_node)

                    except Exception as e:
                        # 记录解析错误
                        # 不中断整个执行，继续处理后续事件
                        logger.error(f"Failed to parse SSE line: {line}", exc_info=e)

            # 返回执行结果
            # 此时 execution 对象已被事件分发器填充
            return execution

        except Exception as e:
            # 记录错误日志
            # 包含命令长度信息，帮助调试
            logger.error(
                "Failed to run command (length: %s)",
                len(command),
                exc_info=e,
            )
            # 转换为 SDK 标准异常
            raise ExceptionConverter.to_sandbox_exception(e) from e

    async def interrupt(self, execution_id: str) -> None:
        """
        中断正在运行的命令执行

        安全地终止一个正在执行的命令，清理相关资源。

        中断机制：
            - 发送中断信号到执行中的进程
            - 等待进程优雅退出
            - 清理临时文件和资源
            - 更新执行状态

        参数：
            execution_id (str): 执行 ID
                - 从 run() 方法的返回结果中获取
                - 例如：execution.id

        异常：
            SandboxException: 如果中断失败（如执行已完成）

        使用示例：
            ```python
            # 启动一个长时间运行的命令
            result = await adapter.run("sleep 60")
            execution_id = result.id

            # 在另一个地方中断它
            await adapter.interrupt(execution_id)
            print("Command interrupted")
            ```

        注意事项：
            - 中断是异步的，可能需要一些时间完成
            - 某些命令可能无法被中断（如系统调用）
            - 中断后应检查执行状态确认是否成功
        """
        try:
            # 导入中断命令的 API 函数
            from opensandbox.api.execd.api.command import interrupt_command

            # 获取 API 客户端
            client = await self._get_client()

            # 调用 API 中断命令
            # async_detailed 版本返回完整的响应对象
            response_obj = await interrupt_command.asyncio_detailed(
                client=client,
                id=execution_id,
            )

            # 处理 API 错误
            handle_api_error(response_obj, "Interrupt command")

        except Exception as e:
            # 记录错误日志
            logger.error("Failed to interrupt command", exc_info=e)
            raise ExceptionConverter.to_sandbox_exception(e) from e

    async def get_command_status(self, execution_id: str) -> CommandStatus:
        """
        获取命令的当前执行状态

        查询指定执行的当前状态，包括运行状态、退出码等信息。

        参数：
            execution_id (str): 执行 ID

        返回：
            CommandStatus: 命令状态对象
                - state: 执行状态（RUNNING、COMPLETED、FAILED 等）
                - exit_code: 退出码（如果已完成）
                - started_at: 开始时间
                - completed_at: 完成时间

        异常：
            SandboxException: 如果查询失败（如执行 ID 不存在）

        使用示例：
            ```python
            # 获取执行状态
            status = await adapter.get_command_status(execution_id)

            if status.state == "RUNNING":
                print("Command is still running")
            elif status.state == "COMPLETED":
                print(f"Command completed with exit code: {status.exit_code}")
            elif status.state == "FAILED":
                print("Command failed")
            ```
        """
        try:
            # 导入响应处理器
            from opensandbox.adapters.converter.response_handler import require_parsed
            # 导入获取命令状态的 API 函数
            from opensandbox.api.execd.api.command import get_command_status
            # 导入命令状态响应模型
            from opensandbox.api.execd.models import CommandStatusResponse

            # 获取 API 客户端
            client = await self._get_client()

            # 调用 API 获取命令状态
            response_obj = await get_command_status.asyncio_detailed(
                client=client,
                id=execution_id,
            )

            # 处理 API 错误
            handle_api_error(response_obj, "Get command status")

            # 解析响应并转换为领域模型
            # require_parsed 确保响应已成功解析
            parsed = require_parsed(response_obj, CommandStatusResponse, "Get command status")

            # 使用转换器将 API 模型转换为 SDK 模型
            return to_command_status(parsed)

        except Exception as e:
            # 记录错误日志
            logger.error("Failed to get command status", exc_info=e)
            raise ExceptionConverter.to_sandbox_exception(e) from e

    async def get_background_command_logs(
        self, execution_id: str, cursor: int | None = None
    ) -> CommandLogs:
        """
        获取后台命令的日志（非流式）

        获取指定执行的日志内容，支持使用游标进行增量获取。

        参数：
            execution_id (str): 执行 ID
            cursor (int | None): 日志游标（可选）
                - 用于增量获取日志
                - None 表示从头开始获取
                - 从上次返回的 cursor 继续获取新日志

        返回：
            CommandLogs: 命令日志对象
                - content: 日志内容（字符串）
                - cursor: 下次获取的游标位置（如果有更多日志）

        日志内容格式：
            日志内容包含 stdout 和 stderr 的混合输出，
            格式由服务端决定，通常包含时间戳和输出类型标记。

        使用示例：
            ```python
            # 获取完整日志
            logs = await adapter.get_background_command_logs(execution_id)
            print(logs.content)

            # 增量获取日志
            cursor = None
            while True:
                logs = await adapter.get_background_command_logs(
                    execution_id,
                    cursor=cursor
                )
                print(logs.content)

                if logs.cursor is None:
                    break  # 没有更多日志
                cursor = logs.cursor
            ```

        注意事项：
            - 此方法适用于后台执行的命令
            - 对于实时输出，建议使用 run() 方法的流式处理器
            - 游标用于分页获取大量日志
        """
        try:
            # 导入响应处理器
            from opensandbox.adapters.converter.response_handler import require_parsed
            # 导入获取日志的 API 函数
            from opensandbox.api.execd.api.command import get_background_command_logs

            # 获取 API 客户端
            client = await self._get_client()

            # 导入 UNSET 类型
            # 用于处理可选参数，与生成的 API 类型系统兼容
            from opensandbox.api.execd.types import UNSET

            # 调用 API 获取日志
            # 如果 cursor 为 None，使用 UNSET 表示不传此参数
            response_obj = await get_background_command_logs.asyncio_detailed(
                client=client,
                id=execution_id,
                cursor=cursor if cursor is not None else UNSET,
            )

            # 处理 API 错误
            handle_api_error(response_obj, "Get command logs")

            # 获取响应内容（字符串）
            content = require_parsed(response_obj, str, "Get command logs")

            # 从响应头中提取游标信息
            # EXECD-COMMANDS-TAIL-CURSOR 头包含下次获取的游标位置
            cursor_header = response_obj.headers.get("EXECD-COMMANDS-TAIL-CURSOR")
            next_cursor = None

            # 解析游标值
            if cursor_header:
                try:
                    next_cursor = int(cursor_header)
                except ValueError:
                    # 如果解析失败，忽略游标
                    next_cursor = None

            # 返回日志对象
            return CommandLogs(content=content, cursor=next_cursor)

        except Exception as e:
            # 记录错误日志
            logger.error("Failed to get command logs", exc_info=e)
            raise ExceptionConverter.to_sandbox_exception(e) from e
