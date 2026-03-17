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
异常转换器模块 - Exception Converter

本模块提供了 ExceptionConverter 类，用于将各种类型的异常转换为 SDK 标准异常。

设计目的：
    - 统一异常处理机制，将不同类型的异常转换为 SDK 标准异常
    - 遵循 Kotlin SDK 的 ExceptionConverter 模式
    - 简化调用者的异常处理逻辑

核心功能：
    - 转换 openapi-python-client 生成的异常
    - 转换 httpx HTTP 错误
    - 转换网络/IO 错误
    - 解析错误响应体提取 SandboxError 信息

异常转换规则：
    1. SandboxException -> 直接返回（已经是 SDK 异常）
    2. API 客户端异常 -> 转换为 SandboxApiException
    3. 网络/IO 错误 -> 转换为 SandboxInternalException
    4. 参数错误（ValueError/TypeError） -> 转换为 InvalidArgumentException
    5. 其他异常 -> 转换为 SandboxInternalException

SDK 异常层次结构：
    SandboxException (基类)
    ├── SandboxApiException (API 调用失败)
    ├── SandboxInternalException (SDK 内部错误)
    └── InvalidArgumentException (参数无效)

使用示例：
    ```python
    from opensandbox.adapters.converter.exception_converter import ExceptionConverter

    try:
        # 执行可能抛出异常的操作
        result = await api_call()
    except Exception as e:
        # 转换为 SDK 标准异常
        sandbox_exception = ExceptionConverter.to_sandbox_exception(e)
        raise sandbox_exception
    ```
"""

import json
import logging
from typing import Any

from httpx import (
    ConnectError,
    HTTPStatusError,
    NetworkError,
    ReadTimeout,
    TimeoutException,
    WriteTimeout,
)

from opensandbox.api.execd.errors import UnexpectedStatus as ExecdUnexpectedStatus
from opensandbox.api.lifecycle.errors import (
    UnexpectedStatus as LifecycleUnexpectedStatus,
)
from opensandbox.exceptions import (
    InvalidArgumentException,
    SandboxApiException,
    SandboxError,
    SandboxException,
    SandboxInternalException,
)

# 配置模块日志记录器
logger = logging.getLogger(__name__)

# 定义 UnexpectedStatus 异常类型元组
# 用于 isinstance 检查，支持 lifecycle 和 execd 两种 API 的异常
UNEXPECTED_STATUS_TYPES = (LifecycleUnexpectedStatus, ExecdUnexpectedStatus)

# 定义 httpx 网络错误类型元组
# 包含所有与网络通信相关的错误类型
HTTPX_NETWORK_ERROR_TYPES = (
    ConnectError,        # 连接建立失败
    TimeoutException,    # 请求超时
    NetworkError,        # 通用网络错误
    ReadTimeout,         # 读取超时
    WriteTimeout,        # 写入超时
)


class ExceptionConverter:
    """
    异常转换器工具类 - 遵循 Kotlin SDK 模式

    本类提供了静态方法，用于将各种异常转换为 SDK 标准异常。
    包括正确解析错误响应体以提取 SandboxError 信息。

    设计原则：
        - 保持异常的原始信息（消息、原因、状态码等）
        - 提供清晰的异常层次结构
        - 便于调用者统一处理异常

    异常转换规则：
        1. SandboxException -> 直接返回（已经是 SDK 异常）
        2. UnexpectedStatus -> 转换为 SandboxApiException
        3. HTTPStatusError -> 转换为 SandboxApiException
        4. 网络/IO 错误 -> 转换为 SandboxInternalException
        5. ValueError/TypeError -> 转换为 InvalidArgumentException
        6. NotImplementedError -> 转换为 SandboxInternalException
        7. 其他异常 -> 转换为 SandboxInternalException

    使用示例：
        ```python
        from opensandbox.adapters.converter.exception_converter import ExceptionConverter

        try:
            response = await api_client.call()
        except Exception as e:
            # 转换为 SDK 标准异常
            raise ExceptionConverter.to_sandbox_exception(e)
        ```
    """

    @staticmethod
    def to_sandbox_exception(e: Exception) -> SandboxException:
        """
        将任意异常转换为 SandboxException

        遵循 Kotlin SDK 模式的异常转换规则：
        - SandboxException -> 直接返回
        - API 客户端异常 -> 转换为 SandboxApiException
        - IO/网络错误 -> 转换为带有网络错误消息的 SandboxInternalException
        - IllegalArgumentError/ValueError -> 转换为带有使用错误消息的 SandboxInternalException
        - 其他异常 -> 转换为带有意外错误消息的 SandboxInternalException

        参数：
            e (Exception): 原始异常对象

        返回：
            SandboxException: SDK 标准异常对象（或其子类）

        异常层次说明：
            - SandboxApiException: API 调用失败（HTTP 错误、响应异常等）
            - SandboxInternalException: SDK 内部错误（网络问题、意外错误等）
            - InvalidArgumentException: 参数无效（调用者使用错误）

        使用示例：
            ```python
            try:
                result = await api_call()
            except Exception as e:
                # 转换为 SDK 标准异常
                sandbox_exception = ExceptionConverter.to_sandbox_exception(e)
                raise sandbox_exception

            # 或者直接在 raise 语句中转换
            try:
                result = await api_call()
            except Exception as e:
                raise ExceptionConverter.to_sandbox_exception(e) from e
            ```
        """
        # 如果已经是 SandboxException，直接返回
        # 避免重复转换
        if isinstance(e, SandboxException):
            return e

        # 处理 openapi-python-client 的 UnexpectedStatus 错误
        # 这种错误通常在 API 返回非 200 状态码时抛出
        if _is_unexpected_status_error(e):
            return _convert_unexpected_status_to_api_exception(e)

        # 处理 httpx 的 HTTPStatusError
        # 这种错误在使用自定义 httpx 客户端时可能抛出
        if _is_httpx_status_error(e):
            return _convert_httpx_error_to_api_exception(e)

        # 处理网络/IO 错误
        # 包括 IOError、OSError、ConnectionError 等
        if isinstance(e, (IOError, OSError, ConnectionError)):
            return SandboxInternalException(
                message=f"Network connectivity error: {e}",
                cause=e,
            )

        # 处理 httpx 网络错误
        # 这些错误通常在连接建立或数据传输过程中抛出
        if _is_httpx_network_error(e):
            return SandboxInternalException(
                message=f"Network connectivity error: {e}",
                cause=e,
            )

        # 处理验证和参数错误（SDK 使用错误）
        # ValueError/TypeError 通常由无效的用户输入或模型验证抛出
        # Pydantic ValidationError 表示 SDK 模型的输入数据无效
        try:
            from pydantic import ValidationError  # type: ignore

            if isinstance(e, ValidationError):
                return InvalidArgumentException(message=str(e), cause=e)
        except Exception:
            # 如果由于某些原因 pydantic 不可用，忽略并继续
            pass

        # 处理值错误和类型错误
        # 这些通常是调用者使用 SDK 时传递了无效参数
        if isinstance(e, (ValueError, TypeError)):
            return InvalidArgumentException(message=str(e), cause=e)

        # 处理不支持的操作
        # NotImplementedError 表示请求的功能尚未实现
        if isinstance(e, NotImplementedError):
            return SandboxInternalException(
                message=f"Operation not supported: {e}",
                cause=e,
            )

        # 默认处理：意外错误
        # 所有其他未分类的异常都被视为意外错误
        return SandboxInternalException(
            message=f"Unexpected SDK error occurred: {e}",
            cause=e,
        )


def _is_unexpected_status_error(e: Exception) -> bool:
    """
    检查异常是否为 openapi-python-client 的 UnexpectedStatus 错误

    UnexpectedStatus 错误在 API 返回非预期状态码时抛出。

    参数：
        e (Exception): 要检查的异常

    返回：
        bool: 如果是 UnexpectedStatus 错误返回 True，否则返回 False
    """
    return isinstance(e, UNEXPECTED_STATUS_TYPES)


def _is_httpx_status_error(e: Exception) -> bool:
    """
    检查异常是否为 httpx 的 HTTPStatusError

    HTTPStatusError 在 HTTP 响应状态码表示错误时抛出。

    参数：
        e (Exception): 要检查的异常

    返回：
        bool: 如果是 HTTPStatusError 返回 True，否则返回 False
    """
    return isinstance(e, HTTPStatusError)


def _is_httpx_network_error(e: Exception) -> bool:
    """
    检查异常是否为 httpx 的网络相关错误

    网络错误包括连接失败、超时、网络中断等。

    参数：
        e (Exception): 要检查的异常

    返回：
        bool: 如果是网络错误返回 True，否则返回 False
    """
    return isinstance(e, HTTPX_NETWORK_ERROR_TYPES)


def _convert_unexpected_status_to_api_exception(e: Exception) -> SandboxApiException:
    """
    将 openapi-python-client 的 UnexpectedStatus 转换为 SandboxApiException

    此函数会：
    1. 提取状态码和响应内容
    2. 解析错误响应体获取 SandboxError 信息
    3. 创建包含完整信息的 SandboxApiException

    参数：
        e (Exception): UnexpectedStatus 异常

    返回：
        SandboxApiException: 转换后的 API 异常
    """
    # 提取状态码
    status_code = getattr(e, "status_code", 0)
    # 提取响应内容
    content = getattr(e, "content", b"")

    # 解析错误响应体
    sandbox_error = _parse_error_body(content)

    # 创建 API 异常
    return SandboxApiException(
        message=f"API error: HTTP {status_code}",
        status_code=status_code,
        cause=e,
        error=sandbox_error,
    )


def _convert_httpx_error_to_api_exception(e: Exception) -> SandboxApiException:
    """
    将 httpx 的 HTTPStatusError 转换为 SandboxApiException

    此函数会：
    1. 从响应中提取状态码和内容
    2. 从响应头中提取请求 ID（如果有）
    3. 解析错误响应体获取 SandboxError 信息
    4. 创建包含完整信息的 SandboxApiException

    参数：
        e (Exception): HTTPStatusError 异常

    返回：
        SandboxApiException: 转换后的 API 异常
    """
    # 获取响应对象
    response = getattr(e, "response", None)
    # 提取状态码
    status_code = response.status_code if response else 0
    # 提取响应内容
    content = response.content if response else b""
    # 初始化请求 ID
    request_id = None

    # 从响应头中提取请求 ID
    if response is not None:
        from opensandbox.adapters.converter.response_handler import extract_request_id

        request_id = extract_request_id(response.headers)

    # 解析错误响应体
    sandbox_error = _parse_error_body(content)

    # 创建 API 异常
    return SandboxApiException(
        message=f"API error: HTTP {status_code}",
        status_code=status_code,
        cause=e,
        error=sandbox_error,
        request_id=request_id,
    )


def _parse_error_body(body: Any) -> SandboxError | None:
    """
    解析错误响应体以提取 SandboxError 信息

    类似于 Kotlin SDK 的 parseSandboxError 函数。
    此函数尝试从错误响应中提取错误代码和消息。

    参数：
        body (Any): 错误响应体（bytes、str 或 dict）

    返回：
        SandboxError | None: 解析成功返回 SandboxError，否则返回 None

    解析逻辑：
        1. 如果是 bytes，解码为 UTF-8 字符串
        2. 如果是字符串，尝试解析为 JSON
        3. 从 JSON 对象中提取 code 和 message 字段
        4. 创建 SandboxError 对象

    错误处理：
        - 空响应体返回 None
        - 非 JSON 字符串返回带有原始消息的 SandboxError
        - 解析失败记录调试日志并返回 None
    """
    # 空响应体直接返回 None
    if body is None:
        return None

    try:
        # 将 bytes 转换为字符串
        if isinstance(body, bytes):
            if not body:
                return None
            body = body.decode("utf-8", errors="replace")

        # 空字符串返回 None
        if isinstance(body, str) and not body:
            return None

        # 解析 JSON 字符串
        if isinstance(body, str):
            try:
                body = json.loads(body)
            except json.JSONDecodeError:
                # 如果不是 JSON，返回带有原始字符串消息的 SandboxError
                return SandboxError(
                    code=SandboxError.UNEXPECTED_RESPONSE,
                    message=body,
                )

        # 从 dict 中提取 code 和 message
        if isinstance(body, dict):
            code: str | None = body.get("code")
            message: str | None = body.get("message")

            # 如果有 code 字段，创建 SandboxError
            if code:
                return SandboxError(code=code, message=message or "")

        # 没有有效的错误信息
        return None

    except Exception as ex:
        # 记录调试日志
        logger.debug("Failed to parse error body: %s", ex)
        return None


def parse_sandbox_error(body: Any) -> SandboxError | None:
    """
    解析错误响应体为 SandboxError 的公共函数

    此函数暴露给其他模块使用，用于直接解析错误响应体。

    参数：
        body (Any): 错误响应体（bytes、str 或 dict）

    返回：
        SandboxError | None: 解析成功返回 SandboxError，否则返回 None

    使用示例：
        ```python
        from opensandbox.adapters.converter.exception_converter import parse_sandbox_error

        error_body = b'{"code": "SANDBOX_NOT_FOUND", "message": "沙箱不存在"}'
        sandbox_error = parse_sandbox_error(error_body)
        if sandbox_error:
            print(f"Error: {sandbox_error.code} - {sandbox_error.message}")
        ```
    """
    return _parse_error_body(body)
