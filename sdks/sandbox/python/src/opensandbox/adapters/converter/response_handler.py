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
统一 API 响应处理器模块 - Response Handler

本模块提供了统一的 API 响应处理工具函数。

设计目的：
    - 提供集中化的 API 响应处理方式
    - 消除在每个适配器方法中重复的响应处理逻辑
    - 统一异常转换和错误处理机制

核心功能：
    1. 状态码验证：检查响应状态码是否表示成功
    2. 错误响应处理：解析错误响应体并提取错误信息
    3. 统一异常转换：将错误转换为 SandboxApiException
    4. 请求 ID 提取：从响应头中提取 X-Request-ID

主要函数：
    - extract_request_id: 从响应头中提取请求 ID
    - handle_api_error: 检查并处理 API 错误
    - require_parsed: 验证并返回解析后的响应数据

使用示例：
    ```python
    from opensandbox.adapters.converter.response_handler import (
        handle_api_error,
        require_parsed,
        extract_request_id
    )

    # 调用 API
    response_obj = await api_function.asyncio_detailed(client=client)

    # 检查错误
    handle_api_error(response_obj, "Get metrics")

    # 获取解析后的数据
    parsed = require_parsed(response_obj, Metrics, "Get metrics")

    # 提取请求 ID
    request_id = extract_request_id(response_obj.headers)
    ```
"""

import logging
from http import HTTPStatus
from typing import Any, TypeVar

from opensandbox.exceptions import SandboxApiException

# 配置模块日志记录器
logger = logging.getLogger(__name__)


# 泛型类型变量，用于 require_parsed 函数的返回类型
T = TypeVar("T")


def extract_request_id(headers: Any) -> str | None:
    """
    从响应头中以不区分大小写的方式提取 X-Request-ID

    X-Request-ID 是服务端生成的唯一请求标识，用于追踪和调试。

    参数：
        headers (Any): 响应头对象
            - 可以是 httpx.Headers 或其他支持 get 方法的对象

    返回：
        str | None: 请求 ID 字符串，如果不存在或提取失败则返回 None

    处理逻辑：
        1. 检查 headers 是否存在
        2. 尝试以不区分大小写的方式获取 X-Request-ID
        3. 去除空白字符
        4. 处理异常情况

    使用示例：
        ```python
        request_id = extract_request_id(response.headers)
        if request_id:
            print(f"Request ID: {request_id}")
        ```
    """
    # 空检查
    if not headers:
        return None

    try:
        # httpx.Headers 支持不区分大小写的查找
        # 尝试两种大小写形式以确保兼容性
        value = headers.get("X-Request-ID") or headers.get("x-request-id")

        # 如果是字符串，去除空白
        if isinstance(value, str):
            value = value.strip()

        # 返回处理后的值或 None
        return value or None

    except Exception:
        # 任何异常都返回 None
        return None


def _status_code_to_int(status_code: Any) -> int:
    """
    将 openapi-python-client 响应中的状态码转换为整数

    openapi-python-client 可能使用 http.HTTPStatus 枚举，
    而某些调用者可能已经提供整数。

    参数：
        status_code (Any): 状态码，可以是 int、HTTPStatus 或其他类型

    返回：
        int: 整数形式的状态码，如果转换失败返回 0

    处理逻辑：
        1. 如果是 HTTPStatus 枚举，转换为整数
        2. 如果已经是整数，直接返回
        3. 尝试获取 value 属性
        4. 尝试强制转换为 int
        5. 所有转换失败返回 0
    """
    # HTTPStatus 枚举转换
    if isinstance(status_code, HTTPStatus):
        return int(status_code)

    # 已经是整数
    if isinstance(status_code, int):
        return status_code

    # 尝试获取 value 属性（HTTPStatus 有 value 属性）
    value = getattr(status_code, "value", None)
    if isinstance(value, int):
        return value

    # 尝试强制转换
    try:
        return int(status_code)
    except Exception:
        return 0


def require_parsed(response_obj: Any, expected_type: type[T], operation_name: str) -> T:
    """
    验证并返回 openapi-python-client 响应中的解析数据

    在调用 handle_api_error() 之后使用此函数来确保：
    - 解析的数据存在
    - 解析的数据类型与预期类型匹配

    参数：
        response_obj (Any): openapi-python-client 的响应对象
        expected_type (type[T]): 预期的数据类型
        operation_name (str): 操作名称，用于错误消息

    返回：
        T: 解析后的数据对象

    异常：
        SandboxApiException: 如果解析数据不存在或类型不匹配

    验证逻辑：
        1. 提取状态码和请求 ID 用于错误消息
        2. 获取 parsed 属性（openapi-python-client 的解析数据）
        3. 检查 parsed 是否为 None
        4. 检查 parsed 是否是预期类型
        5. 返回解析后的数据

    使用示例：
        ```python
        response_obj = await get_metrics.asyncio_detailed(client=client)
        handle_api_error(response_obj, "Get metrics")
        metrics = require_parsed(response_obj, Metrics, "Get metrics")
        ```
    """
    # 提取状态码
    status_code = _status_code_to_int(getattr(response_obj, "status_code", 0))
    # 提取请求 ID
    request_id = extract_request_id(getattr(response_obj, "headers", None))

    # 获取解析后的数据
    parsed = getattr(response_obj, "parsed", None)

    # 检查解析数据是否存在
    if parsed is None:
        raise SandboxApiException(
            message=f"{operation_name} failed: empty response",
            status_code=status_code,
            request_id=request_id,
        )

    # 检查类型是否匹配
    if not isinstance(parsed, expected_type):
        raise SandboxApiException(
            message=f"{operation_name} failed: unexpected response type",
            status_code=status_code,
            request_id=request_id,
        )

    # 返回解析后的数据
    return parsed


def handle_api_error(response_obj: Any, operation_name: str = "API call") -> None:
    """
    检查 API 响应中的错误，如有需要抛出异常

    在访问 response_obj.parsed 之前调用此函数来验证响应。

    参数：
        response_obj (Any): asyncio_detailed 或 sync_detailed 返回的 Response 对象
        operation_name (str): 操作名称，用于错误消息
            - 默认为 "API call"

    异常：
        SandboxApiException: 如果响应表示错误

    错误判断逻辑：
        1. 状态码 >= 300 表示错误
        2. 从 parsed 中提取错误消息（如果有）
        3. 创建并抛出 SandboxApiException

    错误消息提取优先级：
        1. parsed.message（如果有 message 属性）
        2. parsed.code（如果有 code 属性）
        3. 默认格式："{operation_name} failed: HTTP {status_code}"

    使用示例：
        ```python
        response_obj = await api_function.asyncio_detailed(client=client)

        # 检查错误
        handle_api_error(response_obj, "Create sandbox")

        # 如果没有抛出异常，继续处理
        parsed = response_obj.parsed
        ```
    """
    # 提取状态码
    status_code = _status_code_to_int(getattr(response_obj, "status_code", 0))
    # 提取请求 ID
    request_id = extract_request_id(getattr(response_obj, "headers", None))

    # 记录调试日志
    logger.debug(f"{operation_name} response: status={status_code}")

    # 状态码 >= 300 表示错误
    if status_code >= 300:
        # 构建错误消息
        error_message = f"{operation_name} failed: HTTP {status_code}"

        # 尝试从 parsed 中提取更详细的错误消息
        if hasattr(response_obj, "parsed") and response_obj.parsed is not None:
            # 优先使用 message 属性
            if hasattr(response_obj.parsed, "message"):
                error_message = f"{operation_name} failed: {response_obj.parsed.message}"
            # 回退到 code 属性
            elif hasattr(response_obj.parsed, "code"):
                error_message = f"{operation_name} failed: {response_obj.parsed.code}"

        # 抛出 API 异常
        raise SandboxApiException(
            message=error_message,
            status_code=status_code,
            request_id=request_id,
        )
