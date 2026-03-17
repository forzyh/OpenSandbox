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
执行事件分发器模块 - Execution Event Dispatcher

本模块提供了 ExecutionEventDispatcher 类，用于处理和分发执行事件。

设计目的：
    - 解析 Server-Sent Events (SSE) 流中的事件
    - 将事件分发到相应的处理器
    - 更新 Execution 对象的状态

核心功能：
    - 事件类型识别：根据事件类型调用相应的处理方法
    - 事件处理：处理 stdout、stderr、result、error 等事件
    - 回调调用：调用用户提供的异步处理器
    - 状态更新：更新 Execution 对象的属性和日志

事件类型：
    - init: 执行初始化事件，包含执行 ID
    - stdout: 标准输出事件
    - stderr: 标准错误事件
    - result: 执行结果事件
    - error: 执行错误事件
    - execution_complete: 执行完成事件
    - execution_count: 执行计数事件

使用示例：
    ```python
    from opensandbox.adapters.converter.execution_event_dispatcher import ExecutionEventDispatcher
    from opensandbox.models.execd import Execution, ExecutionHandlers

    # 创建 Execution 对象
    execution = Execution()

    # 创建处理器
    async def on_stdout(msg):
        print(f"Output: {msg.text}")

    handlers = ExecutionHandlers(on_stdout=on_stdout)

    # 创建分发器
    dispatcher = ExecutionEventDispatcher(execution, handlers)

    # 分发事件
    event = EventNode(type="stdout", text="Hello", timestamp=1234567890)
    await dispatcher.dispatch(event)
    ```
"""

from opensandbox.adapters.converter.event_node import EventNode
from opensandbox.models.execd import (
    Execution,          # 执行结果容器
    ExecutionComplete,  # 执行完成事件
    ExecutionError,     # 执行错误信息
    ExecutionHandlers,  # 执行处理器
    ExecutionInit,      # 执行初始化事件
    ExecutionResult,    # 执行结果
    OutputMessage,      # 输出消息
)


class ExecutionEventDispatcher:
    """
    执行事件分发器

    本类负责将服务器流式响应中的事件分发到 Execution 对象和处理器。
    它解析每个事件节点，根据事件类型调用相应的处理方法，并更新执行状态。

    属性：
        execution (Execution): 执行结果对象，用于收集和存储执行数据
        handlers (ExecutionHandlers | None): 用户提供的处理器，用于回调处理

    支持的事件类型：
        - init: 初始化执行，设置执行 ID
        - stdout: 处理标准输出
        - stderr: 处理标准错误
        - result: 处理执行结果
        - error: 处理执行错误
        - execution_complete: 处理执行完成
        - execution_count: 更新执行计数

    使用示例：
        ```python
        execution = Execution()
        handlers = ExecutionHandlers(
            on_stdout=lambda msg: print(msg.text),
            on_error=lambda err: print(f"Error: {err.name}")
        )
        dispatcher = ExecutionEventDispatcher(execution, handlers)

        # 处理 SSE 事件流
        async for line in response.aiter_lines():
            event = EventNode(**json.loads(line))
            await dispatcher.dispatch(event)
        ```
    """

    def __init__(
        self,
        execution: Execution,
        handlers: ExecutionHandlers | None = None,
    ) -> None:
        """
        初始化执行事件分发器

        参数：
            execution (Execution): 执行结果对象
                - 用于存储所有执行相关的数据
                - 事件处理会更新此对象的状态

            handlers (ExecutionHandlers | None): 执行处理器
                - 包含各种事件的回调函数
                - 如果为 None，则只更新 execution 不调用回调

        使用示例：
            ```python
            execution = Execution()

            # 不带处理器
            dispatcher = ExecutionEventDispatcher(execution)

            # 带处理器
            handlers = ExecutionHandlers(on_stdout=handle_stdout)
            dispatcher = ExecutionEventDispatcher(execution, handlers)
            ```
        """
        self.execution = execution
        self.handlers = handlers

    async def dispatch(self, event_node: EventNode) -> None:
        """
        异步分发单个事件节点

        根据事件类型调用相应的处理方法。这是事件分发的入口方法。

        参数：
            event_node (EventNode): 事件节点对象
                - 包含事件的所有信息（类型、内容、时间戳等）

        处理流程：
            1. 提取事件类型和时间戳
            2. 根据事件类型调用相应的 _handle_* 方法
            3. 每个处理方法会更新 execution 并调用处理器（如果有）

        使用示例：
            ```python
            dispatcher = ExecutionEventDispatcher(execution, handlers)

            # 处理单个事件
            event = EventNode(type="stdout", text="Hello", timestamp=1234567890)
            await dispatcher.dispatch(event)
            ```
        """
        # 提取事件类型
        event_type = event_node.type
        # 提取事件时间戳
        timestamp = event_node.timestamp

        # 根据事件类型调用相应的处理方法
        if event_type == "stdout":
            await self._handle_stdout(event_node, timestamp)
        elif event_type == "stderr":
            await self._handle_stderr(event_node, timestamp)
        elif event_type == "result":
            await self._handle_result(event_node, timestamp)
        elif event_type == "error":
            await self._handle_error(event_node, timestamp)
        elif event_type == "execution_complete":
            await self._handle_execution_complete(event_node, timestamp)
        elif event_type == "init":
            await self._handle_init(event_node, timestamp)
        elif event_type == "execution_count":
            # 更新执行计数
            if event_node.execution_count is not None:
                self.execution.execution_count = event_node.execution_count

    async def _handle_init(self, event_node: EventNode, timestamp: int) -> None:
        """
        处理执行初始化事件

        从事件中提取执行 ID，更新 execution 对象，并调用 on_init 处理器。

        参数：
            event_node (EventNode): 事件节点
            timestamp (int): 事件时间戳
        """
        # 从事件文本中提取执行 ID
        execution_id = event_node.text or ""
        # 创建初始化事件对象
        init_event = ExecutionInit(
            id=execution_id,
            timestamp=timestamp,
        )
        # 更新 execution 的 ID
        self.execution.id = init_event.id
        # 调用处理器（如果有）
        if self.handlers and self.handlers.on_init:
            await self.handlers.on_init(init_event)

    async def _handle_stdout(self, event_node: EventNode, timestamp: int) -> None:
        """
        处理标准输出事件

        从事件中提取输出文本，创建输出消息，添加到日志，并调用 on_stdout 处理器。

        参数：
            event_node (EventNode): 事件节点
            timestamp (int): 事件时间戳
        """
        # 提取输出文本
        text = event_node.text or ""
        # 创建输出消息对象
        message = OutputMessage(
            text=text,
            timestamp=timestamp,
            is_error=False,  # 标准输出不是错误
        )
        # 添加到标准输出日志
        self.execution.logs.add_stdout(message)
        # 调用处理器（如果有）
        if self.handlers and self.handlers.on_stdout:
            await self.handlers.on_stdout(message)

    async def _handle_stderr(self, event_node: EventNode, timestamp: int) -> None:
        """
        处理标准错误事件

        从事件中提取错误输出文本，创建输出消息，添加到日志，并调用 on_stderr 处理器。

        参数：
            event_node (EventNode): 事件节点
            timestamp (int): 事件时间戳
        """
        # 提取错误输出文本
        text = event_node.text or ""
        # 创建输出消息对象（标记为错误）
        message = OutputMessage(
            text=text,
            timestamp=timestamp,
            is_error=True,  # 标准错误
        )
        # 添加到标准错误日志
        self.execution.logs.add_stderr(message)
        # 调用处理器（如果有）
        if self.handlers and self.handlers.on_stderr:
            await self.handlers.on_stderr(message)

    async def _handle_result(self, event_node: EventNode, timestamp: int) -> None:
        """
        处理执行结果事件

        从事件中提取执行结果，更新 execution 对象，并调用 on_result 处理器。

        参数：
            event_node (EventNode): 事件节点
            timestamp (int): 事件时间戳
        """
        # 提取结果文本（如果结果为 None 则返回空字符串）
        result_text = event_node.results.get_text() if event_node.results else ""
        # 创建执行结果对象
        result = ExecutionResult(
            text=result_text,
            timestamp=timestamp,
        )
        # 添加到执行结果列表
        self.execution.add_result(result)
        # 调用处理器（如果有）
        if self.handlers and self.handlers.on_result:
            await self.handlers.on_result(result)

    async def _handle_error(self, event_node: EventNode, timestamp: int) -> None:
        """
        处理执行错误事件

        从事件中提取错误信息，更新 execution 对象，并调用 on_error 处理器。

        参数：
            event_node (EventNode): 事件节点
            timestamp (int): 事件时间戳

        注意：
            - 如果事件中没有错误信息，直接返回
            - 错误信息包含错误名称、消息和堆栈跟踪
        """
        # 如果没有错误信息，直接返回
        if not event_node.error:
            return

        # 提取错误数据
        error_data = event_node.error
        # 创建执行错误对象
        error = ExecutionError(
            name=error_data.name or "",       # 错误名称
            value=error_data.value or "",     # 错误消息
            timestamp=timestamp,              # 时间戳
            traceback=error_data.traceback,   # 堆栈跟踪
        )
        # 更新 execution 的错误属性
        self.execution.error = error
        # 调用处理器（如果有）
        if self.handlers and self.handlers.on_error:
            await self.handlers.on_error(error)

    async def _handle_execution_complete(self, event_node: EventNode, timestamp: int) -> None:
        """
        处理执行完成事件

        从事件中提取执行完成信息，并调用 on_execution_complete 处理器。

        参数：
            event_node (EventNode): 事件节点
            timestamp (int): 事件时间戳

        注意：
            - 此事件表示执行已完成
            - 包含执行耗时信息
        """
        # 创建执行完成事件对象
        complete = ExecutionComplete(
            timestamp=timestamp,  # 完成时间戳
            execution_time_in_millis=event_node.execution_time_in_millis or 0,  # 执行耗时
        )
        # 调用处理器（如果有）
        if self.handlers and self.handlers.on_execution_complete:
            await self.handlers.on_execution_complete(complete)
