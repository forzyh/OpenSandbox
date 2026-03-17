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
事件节点模型模块 - EventNode

本模块提供了 EventNode 类，用于解析 execd 服务端发送的 Server-Sent Events (SSE) 事件。

设计目的：
    - 表示命令执行或代码执行过程中的单个事件
    - 对应 OpenAPI 规范中的 ServerStreamEvent
    - 支持解析多种事件类型（输出、结果、错误等）

核心类：
    - EventNode: 事件节点主类，包含事件的所有信息
    - EventNodeError: 错误信息容器
    - EventNodeResults: 执行结果容器

SSE 事件类型：
    - execution.created: 执行创建事件
    - execution.stdout: 标准输出事件
    - execution.stderr: 标准错误事件
    - execution.results: 执行结果事件
    - execution.completed: 执行完成事件
    - execution.error: 执行错误事件

使用示例：
    ```python
    from opensandbox.adapters.converter.event_node import EventNode

    # 解析 SSE 事件
    event_dict = {
        "type": "execution.stdout",
        "text": "Hello World",
        "timestamp": 1234567890
    }
    event = EventNode(**event_dict)
    print(f"Event type: {event.type}")
    print(f"Output: {event.text}")
    ```
"""

from pydantic import BaseModel, ConfigDict, Field


class EventNodeError(BaseModel):
    """
    事件节点中的错误信息容器

    本类用于表示代码执行过程中发生的错误，包含错误名称、错误消息和堆栈跟踪。

    属性：
        name (str | None): 错误名称/类型
            - 例如：'SyntaxError', 'RuntimeError', 'NameError'
            - 对应 Python 异常类的 __name__ 属性

        value (str | None): 错误消息
            - 描述错误的具体内容
            - 对应 Python 异常类的 str() 返回值

        traceback (list[str]): 堆栈跟踪
            - 错误发生时的调用栈信息
            - 每个元素是堆栈的一行
            - 用于调试和定位问题

    使用示例：
        ```python
        error = EventNodeError(
            name="ZeroDivisionError",
            value="division by zero",
            traceback=["File 'script.py', line 10, in <module>", "    1/0"]
        )
        print(f"Error: {error.name}: {error.value}")
        ```
    """

    # 错误名称，使用 ename 作为 JSON 别名
    name: str | None = Field(default=None, alias="ename")
    # 错误值/消息，使用 evalue 作为 JSON 别名
    value: str | None = Field(default=None, alias="evalue")
    # 堆栈跟踪列表，默认为空列表
    traceback: list[str] = Field(default_factory=list)


class EventNodeResults(BaseModel):
    """
    事件节点中的执行结果容器

    本类用于存储代码执行的输出结果，支持多种 MIME 类型的内容。

    属性：
        text (str | None): 文本格式的执行结果
            - UTF-8 编码的字符串
            - 最常见的输出格式

    特殊配置：
        extra="allow": 允许额外的字段，支持其他 MIME 类型的内容
            - 如 application/json, image/png 等
            - 这些额外内容可以通过字典访问方式获取

    方法：
        get_text(): 获取结果的文本表示

    使用示例：
        ```python
        results = EventNodeResults(text="42", application_json='{"key": "value"}')
        print(results.get_text())  # 输出：42
        print(results.application_json)  # 输出：{"key": "value"}
        ```
    """

    # 文本结果，使用 text 作为 JSON 别名
    text: str | None = Field(default=None, alias="text")

    def get_text(self) -> str:
        """
        获取结果的文本表示

        返回结果的文本内容，如果结果为 None 则返回空字符串。

        返回：
            str: 结果的文本表示

        使用示例：
            ```python
            results = EventNodeResults(text="Hello")
            print(results.get_text())  # 输出：Hello

            results = EventNodeResults()
            print(results.get_text())  # 输出："" (空字符串)
            ```
        """
        return self.text or ""

    # 允许额外的字段，支持其他 MIME 类型的内容
    model_config = ConfigDict(extra="allow")


class EventNode(BaseModel):
    """
    服务器流式事件表示类

    本类表示来自服务器的单个 SSE 事件，对应 OpenAPI 规范中的 ServerStreamEvent。
    它是解析和处理命令执行或代码执行事件的核心数据模型。

    事件类型（type 字段）：
        - execution.created: 执行创建事件，包含执行 ID
        - execution.stdout: 标准输出事件，包含输出文本
        - execution.stderr: 标准错误事件，包含错误输出
        - execution.results: 执行结果事件，包含返回值
        - execution.completed: 执行完成事件，包含执行时间
        - execution.error: 执行错误事件，包含错误详情

    属性：
        type (str): 事件类型
            - 标识事件的种类
            - 用于决定如何处理事件内容

        text (str | None): 事件文本内容
            - 对于 stdout/stderr 事件，包含输出内容
            - 对于其他事件可能为 None

        execution_count (int | None): 执行计数
            - 当前执行在会话中的序号
            - 从 1 开始递增
            - 仅在某些事件类型中提供

        execution_time_in_millis (int | None): 执行时间（毫秒）
            - 从执行开始到当前事件的时间
            - 用于性能分析

        timestamp (int): 事件时间戳
            - Unix 时间戳（毫秒）
            - 事件生成的绝对时间

        results (EventNodeResults | None): 执行结果
            - 包含代码执行的返回值
            - 仅在执行结果事件中提供

        error (EventNodeError | None): 错误信息
            - 包含错误的详细信息
            - 仅在错误事件中提供

    使用示例：
        ```python
        # 解析标准输出事件
        stdout_event = EventNode(
            type="execution.stdout",
            text="Hello World",
            timestamp=1234567890
        )

        # 解析错误事件
        error_event = EventNode(
            type="execution.error",
            error=EventNodeError(name="Error", value="Something went wrong"),
            timestamp=1234567890
        )

        # 解析执行结果事件
        result_event = EventNode(
            type="execution.results",
            results=EventNodeResults(text="42"),
            execution_count=1,
            timestamp=1234567890
        )
        ```

    注意事项：
        - 使用 Pydantic 的模型验证功能
        - 支持从字典直接构造对象：EventNode(**event_dict)
        - 字段使用别名与 API 响应格式兼容
    """

    # 事件类型，必填字段
    type: str
    # 事件文本内容，可选
    text: str | None = None
    # 执行计数，使用 execution_count 作为 JSON 别名
    execution_count: int | None = Field(default=None, alias="execution_count")
    # 执行时间（毫秒），使用 execution_time 作为 JSON 别名
    execution_time_in_millis: int | None = Field(default=None, alias="execution_time")
    # 事件时间戳，必填字段
    timestamp: int
    # 执行结果，可选
    results: EventNodeResults | None = None
    # 错误信息，可选
    error: EventNodeError | None = None
