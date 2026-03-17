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
文件系统服务适配器模块 - Filesystem Adapter

本模块提供了 FilesystemAdapter 类，是文件系统服务的实现。

设计目的：
    - 实现 Filesystem 服务接口，提供沙箱内文件系统操作功能
    - 适配 openapi-python-client 自动生成的 FilesystemApi
    - 针对不同类型操作采用优化的处理方式
        - 标准操作：使用生成的 API 客户端
        - 文件上传/下载：使用直接 HTTP 调用（支持大文件流式传输）

核心功能：
    - 文件读取：read_file（文本）、read_bytes（二进制）、read_bytes_stream（流式）
    - 文件写入：write_file（单个）、write_files（批量）
    - 目录操作：create_directories、delete_directories
    - 文件删除：delete_files
    - 文件移动：move_files（支持重命名）
    - 权限管理：set_permissions
    - 内容替换：replace_contents
    - 文件搜索：search（支持通配符模式）
    - 文件信息：get_file_info

架构说明：
    FilesystemAdapter 是 Filesystem 服务接口的具体实现，它：
    1. 使用 openapi-python-client 生成的 Client 进行 API 调用
    2. 使用自定义的 httpx.AsyncClient 进行文件上传/下载
    3. 两个客户端共享同一个 connection_config 的 transport 实例

    HTTP 客户端设计：
        - _client: 标准 API 客户端，用于元数据操作
        - _httpx_client: 专用 HTTP 客户端，用于文件传输

    文件传输优化：
        - 小文件：使用 API 客户端（简单、统一）
        - 大文件上传：使用 multipart/form-data 直接 HTTP 上传
        - 大文件下载：使用流式 HTTP 下载，支持 Range 请求

认证说明：
    Execd API（执行守护进程）不需要认证，因为认证已在沙箱创建时完成。

使用示例：
    ```python
    from opensandbox.config import ConnectionConfig
    from opensandbox.adapters.filesystem_adapter import FilesystemAdapter
    from opensandbox.models.filesystem import WriteEntry, SearchEntry

    config = ConnectionConfig(api_key="key", domain="api.opensandbox.io")
    adapter = FilesystemAdapter(config, endpoint)

    # 写入文件
    await adapter.write_file("hello.py", "print('Hello')")

    # 读取文件
    content = await adapter.read_file("hello.py")
    print(content)

    # 读取二进制文件
    data = await adapter.read_bytes("image.png")

    # 流式读取大文件
    async for chunk in await adapter.read_bytes_stream("large.dat"):
        process(chunk)

    # 批量写入
    await adapter.write_files([
        WriteEntry(path="file1.txt", data="content1"),
        WriteEntry(path="file2.txt", data="content2")
    ])

    # 创建目录
    await adapter.create_directories([
        WriteEntry(path="/data/logs", mode=755)
    ])

    # 搜索文件
    results = await adapter.search(SearchEntry(
        path="/app",
        pattern="*.py"
    ))

    # 获取文件信息
    info = await adapter.get_file_info(["file1.txt", "file2.txt"])
    ```
"""

import json
import logging
from collections.abc import AsyncIterator
from io import IOBase, TextIOBase
from typing import TypedDict
from urllib.parse import quote

import httpx

# 导入异常转换器
from opensandbox.adapters.converter.exception_converter import (
    ExceptionConverter,
)
# 导入文件系统模型转换器
from opensandbox.adapters.converter.filesystem_model_converter import (
    FilesystemModelConverter,
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
# 导入文件系统模型
from opensandbox.models.filesystem import (
    ContentReplaceEntry,   # 内容替换条目
    EntryInfo,             # 文件/目录信息
    MoveEntry,             # 移动条目
    SearchEntry,           # 搜索条目
    SetPermissionEntry,    # 权限设置条目
    WriteEntry,            # 写入条目
)
from opensandbox.models.sandboxes import SandboxEndpoint
# 导入文件系统服务接口定义
from opensandbox.services.filesystem import Filesystem

# 配置模块日志记录器
logger = logging.getLogger(__name__)


class _DownloadRequest(TypedDict):
    """
    下载请求数据结构

    TypedDict 用于定义下载请求的结构，包含：
    - url: 下载 URL
    - params: 查询参数（可选）
    - headers: 请求头

    这是一个内部使用的数据结构，用于封装下载请求的各个组成部分。
    """
    url: str                              # 下载请求的完整 URL
    params: dict[str, str] | None         # URL 查询参数（可选）
    headers: dict[str, str]               # HTTP 请求头


class FilesystemAdapter(Filesystem):
    """
    文件系统服务适配器 - Filesystem 接口的实现

    本类提供了在沙箱内进行文件系统操作的完整实现，支持多种文件操作类型。

    继承关系：
        FilesystemAdapter 实现了 Filesystem Protocol 接口，提供：
        - read_file / read_bytes / read_bytes_stream: 读取文件
        - write_file / write_files: 写入文件
        - create_directories: 创建目录
        - delete_files / delete_directories: 删除文件/目录
        - move_files: 移动/重命名文件
        - set_permissions: 设置权限
        - replace_contents: 替换内容
        - search: 搜索文件
        - get_file_info: 获取文件信息

    技术实现：
        - 基于 openapi-python-client 生成的功能型 API
        - 标准操作使用生成的 API 客户端
        - 文件上传/下载使用优化的直接 HTTP 调用

    HTTP 客户端架构：
        _client (Client): 标准 API 客户端
            - 用于元数据操作（创建目录、删除、移动等）
            - 由 openapi-python-client 生成
            - 注入 _httpx_client 进行底层通信

        _httpx_client (httpx.AsyncClient): 文件传输专用客户端
            - 用于文件上传和下载
            - 支持 multipart/form-data 上传
            - 支持流式下载和 Range 请求

    属性：
        connection_config (ConnectionConfig): 连接配置
        execd_endpoint (SandboxEndpoint): Execd 服务端点

    常量：
        FILESYSTEM_UPLOAD_PATH: 文件上传 API 路径 ("/files/upload")
        FILESYSTEM_DOWNLOAD_PATH: 文件下载 API 路径 ("/files/download")

    使用示例：
        ```python
        adapter = FilesystemAdapter(config, endpoint)

        # 写入文件
        await adapter.write_file("hello.py", "print('Hello')")

        # 读取文件
        content = await adapter.read_file("hello.py")

        # 流式读取大文件
        async for chunk in await adapter.read_bytes_stream("large.dat"):
            process(chunk)
        ```
    """

    # API 路径常量
    # 文件上传端点
    FILESYSTEM_UPLOAD_PATH = "/files/upload"
    # 文件下载端点
    FILESYSTEM_DOWNLOAD_PATH = "/files/download"

    def __init__(
        self, connection_config: ConnectionConfig, execd_endpoint: SandboxEndpoint
    ) -> None:
        """
        初始化文件系统服务适配器

        构造函数负责创建和配置两种 HTTP 客户端：
        1. _client: 标准 API 客户端（用于元数据操作）
        2. _httpx_client: 文件传输专用客户端（用于上传/下载）

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
               - 用于：创建目录、删除、移动、权限设置等

            2. _httpx_client (文件传输客户端):
               - 使用正常超时
               - 包含 User-Agent 和自定义请求头
               - 共享 connection_config 的 transport
               - 用于：文件上传（multipart）、文件下载（流式）

        示例：
            ```python
            config = ConnectionConfig(
                api_key="your-api-key",
                domain="api.opensandbox.io"
            )
            endpoint = await sandbox.get_endpoint(DEFAULT_EXECD_PORT)
            adapter = FilesystemAdapter(config, endpoint)
            ```
        """
        # 保存配置和端点，后续方法使用
        self.connection_config = connection_config
        self.execd_endpoint = execd_endpoint

        # 导入 Execd API 客户端
        # 这个客户端由 openapi-python-client 生成，用于文件系统相关 API
        from opensandbox.api.execd import Client

        # 获取 Execd 服务的基础 URL
        base_url = self._get_execd_base_url()

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

        # 创建 httpx 客户端用于文件传输
        # 这个客户端由适配器拥有和管理，用于直接 HTTP 调用
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

        # 创建标准 API 客户端
        # Execd API 不需要认证（认证在沙箱层面完成）
        # 配置说明：
        #   - base_url: API 基础 URL
        #   - timeout: 请求超时
        self._client = Client(
            base_url=base_url,
            timeout=timeout,
        )

        # 将 httpx 客户端注入到 API 客户端
        # 这样生成的 API 函数就会使用这个客户端进行 HTTP 调用
        self._client.set_async_httpx_client(self._httpx_client)

    def _get_execd_base_url(self) -> str:
        """
        获取 Execd 服务的基础 URL

        辅助方法，根据连接配置和端点信息构建完整的 URL 前缀。

        返回：
            str: 基础 URL（如 "http://192.168.1.1:8080"）

        示例：
            ```python
            base_url = self._get_execd_base_url()
            # 返回：http://192.168.1.1:8080
            ```
        """
        # 获取协议（http 或 https）
        protocol = self.connection_config.protocol
        # 拼接完整的基础 URL
        return f"{protocol}://{self.execd_endpoint.endpoint}"

    async def _get_httpx_client(self) -> httpx.AsyncClient:
        """
        获取文件传输专用的 httpx 客户端

        内部方法，返回用于文件上传/下载的客户端。
        此客户端由适配器拥有和管理。

        返回：
            httpx.AsyncClient: 文件传输客户端实例
        """
        return self._httpx_client

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
            path (str): 相对路径（如 "/files/upload"）

        返回：
            str: 完整的 URL（如 "http://192.168.1.1:8080/files/upload"）

        示例：
            ```python
            url = self._get_execd_url("/files/upload")
            # 返回：http://192.168.1.1:8080/files/upload
            ```
        """
        protocol = self.connection_config.protocol
        return f"{protocol}://{self.execd_endpoint.endpoint}{path}"

    async def read_file(
        self,
        path: str,
        *,
        encoding: str = "utf-8",
        range_header: str | None = None,
    ) -> str:
        """
        读取文件内容为字符串

        便捷方法，内部调用 read_bytes 然后解码为字符串。

        参数：
            path (str): 文件路径
            encoding (str): 字符编码，默认 "utf-8"
            range_header (str | None): Range 请求头（可选）
                - 用于分块读取大文件
                - 格式："bytes=0-1023" 表示读取前 1024 字节

        返回：
            str: 文件内容（解码后的字符串）

        示例：
            ```python
            content = await adapter.read_file("hello.py")
            print(content)

            # 读取指定编码的文件
            content = await adapter.read_file("gbk.txt", encoding="gbk")

            # 分块读取
            content = await adapter.read_file(
                "large.txt",
                range_header="bytes=0-1023"
            )
            ```
        """
        # 先读取二进制内容
        content = await self.read_bytes(path, range_header=range_header)
        # 解码为字符串
        return content.decode(encoding)

    async def read_bytes(
        self,
        path: str,
        *,
        range_header: str | None = None,
    ) -> bytes:
        """
        读取文件内容为二进制字节

        支持 Range 请求，可以读取文件的部分内容。

        参数：
            path (str): 文件路径
            range_header (str | None): Range 请求头（可选）
                - 用于分块读取大文件
                - 格式："bytes=start-end"

        返回：
            bytes: 文件内容（二进制）

        异常：
            SandboxApiException: 如果读取失败

        示例：
            ```python
            # 读取完整文件
            data = await adapter.read_bytes("image.png")

            # 读取前 1KB
            data = await adapter.read_bytes(
                "large.dat",
                range_header="bytes=0-1023"
            )
            ```
        """
        # 记录调试日志
        logger.debug(f"Reading file as bytes: {path}")

        try:
            # 构建下载请求
            request_data = self._build_download_request(path, range_header)

            # 获取 httpx 客户端
            client = await self._get_httpx_client()

            # 发送 GET 请求
            # 根据是否有参数选择不同的调用方式
            if request_data["params"] is None:
                response = await client.get(
                    request_data["url"],
                    headers=request_data["headers"],
                )
            else:
                response = await client.get(
                    request_data["url"],
                    headers=request_data["headers"],
                    params=request_data["params"],
                )

            # 检查响应状态
            response.raise_for_status()

            # 返回响应内容（字节）
            return response.content

        except Exception as e:
            # 记录错误日志
            logger.error(f"Failed to read file {path}", exc_info=e)
            # 转换为 SDK 标准异常
            raise ExceptionConverter.to_sandbox_exception(e) from e

    async def read_bytes_stream(
            self,
            path: str,
            *,
            chunk_size: int = 64 * 1024,
            range_header: str | None = None,
    ) -> AsyncIterator[bytes]:
        """
        流式读取文件内容（按块迭代）

        适用于大文件读取，避免一次性加载整个文件到内存。
        使用真正的 HTTP 流式传输，逐块接收数据。

        参数：
            path (str): 文件路径
            chunk_size (int): 每块的大小（字节），默认 64KB
                - 较小的值：更多次迭代，更少内存
                - 较大的值：更少次迭代，更多内存
            range_header (str | None): Range 请求头（可选）

        返回：
            AsyncIterator[bytes]: 异步迭代器，每次迭代返回一个字节块

        异常：
            SandboxApiException: 如果流式读取失败

        示例：
            ```python
            # 流式读取大文件
            async for chunk in await adapter.read_bytes_stream("large.dat"):
                process(chunk)  # 处理每个数据块

            # 指定块大小
            async for chunk in await adapter.read_bytes_stream(
                "large.dat",
                chunk_size=1024 * 1024  # 1MB 块
            ):
                process(chunk)

            # 分块读取指定范围
            async for chunk in await adapter.read_bytes_stream(
                "large.dat",
                range_header="bytes=0-1048575"  # 前 1MB
            ):
                process(chunk)
            ```

        内存优化说明：
            此方法使用真正的流式传输，不会将整个文件加载到内存。
            适合处理 GB 级别的大文件。
        """
        # 记录调试日志
        logger.debug(f"Streaming file as bytes: {path} (chunk_size={chunk_size})")

        try:
            # 构建下载请求
            request_data = self._build_download_request(path, range_header)

            # 获取 httpx 客户端
            client = await self._get_httpx_client()

            # 提取请求参数
            url = request_data["url"]
            params = request_data["params"]
            headers = request_data["headers"]

            # 构建请求对象
            # 根据是否有参数选择不同的构建方式
            if params is None:
                request = client.build_request("GET", url, headers=headers)
            else:
                request = client.build_request(
                    "GET",
                    url,
                    headers=headers,
                    params=params,
                )

            # 发送流式请求
            # stream=True 表示我们不立即读取整个响应
            response = await client.send(request, stream=True)

            # 检查响应状态
            if response.status_code >= 300:
                # 读取错误响应体
                try:
                    await response.aread()
                finally:
                    await response.aclose()

                # 抛出异常
                raise SandboxApiException(
                    f"Failed to stream file {path}: {response.status_code}",
                    status_code=response.status_code,
                    request_id=extract_request_id(response.headers),
                )

            # 返回异步字节迭代器
            # aiter_bytes 按指定块大小迭代响应内容
            return response.aiter_bytes(chunk_size=chunk_size)

        except Exception as e:
            # 记录错误日志
            logger.error(f"Failed to stream file {path}", exc_info=e)
            # 转换为 SDK 标准异常
            raise ExceptionConverter.to_sandbox_exception(e) from e

    async def write_files(self, entries: list[WriteEntry]) -> None:
        """
        批量写入多个文件（单次操作）

        使用 multipart/form-data 格式在一次 HTTP 请求中上传多个文件。
        与 Kotlin SDK 实现保持一致。

        参数：
            entries (list[WriteEntry]): 写入条目列表
                每个条目包含：
                - path: 文件路径（必填）
                - data: 文件内容（bytes | str | IOBase）
                - mode: 文件权限（默认 755）
                - owner: 文件所有者（可选）
                - group: 文件组（可选）
                - encoding: 文本编码（可选，默认 utf-8）

        异常：
            InvalidArgumentException: 如果路径或内容为空
            SandboxApiException: 如果写入失败

        示例：
            ```python
            from opensandbox.models.filesystem import WriteEntry

            # 批量写入多个文件
            await adapter.write_files([
                WriteEntry(path="file1.txt", data="content1"),
                WriteEntry(path="file2.txt", data="content2"),
                WriteEntry(path="data.bin", data=b"\\x00\\x01\\x02"),
            ])

            # 带权限设置
            await adapter.write_files([
                WriteEntry(
                    path="script.sh",
                    data="#!/bin/bash\\necho hello",
                    mode=755  # 可执行
                )
            ])
            ```

        实现细节：
            每个文件由两部分组成：
            1. metadata: JSON 格式的元数据（路径、权限等）
            2. file: 实际的文件内容

            所有文件在单次 multipart 请求中发送。
        """
        # 空列表直接返回
        if not entries:
            return

        # 记录调试日志
        logger.debug(f"Writing {len(entries)} files")

        try:
            # 获取 httpx 客户端
            client = await self._get_httpx_client()

            # 构建 multipart 请求的各个部分
            multipart_parts = []

            # 遍历每个写入条目
            for entry in entries:
                # 验证路径不为空
                if not entry.path:
                    raise InvalidArgumentException("File path cannot be null")

                # 验证内容不为空
                if entry.data is None:
                    raise InvalidArgumentException("File data cannot be null")

                # 构建元数据对象
                metadata = {
                    "path": entry.path,
                    "owner": entry.owner,
                    "group": entry.group,
                    "mode": entry.mode,
                }
                # 序列化为 JSON
                metadata_json = json.dumps(metadata)

                # 添加元数据部分到 multipart
                multipart_parts.append(
                    ("metadata", ("metadata", metadata_json, "application/json"))
                )

                # 根据数据类型确定内容和 MIME 类型
                content: bytes | str | IOBase
                content_type: str

                if isinstance(entry.data, bytes):
                    # 二进制数据
                    content = entry.data
                    content_type = "application/octet-stream"

                elif isinstance(entry.data, str):
                    # 文本数据
                    encoding = entry.encoding or "utf-8"
                    content = entry.data
                    content_type = f"text/plain; charset={encoding}"

                elif isinstance(entry.data, IOBase):
                    # 文件流
                    if isinstance(entry.data, TextIOBase):
                        # 文本流不支持，必须是二进制流
                        raise InvalidArgumentException(
                            "File stream must be binary (opened with 'rb'). Text streams are not supported."
                        )
                    else:
                        # 二进制流
                        content = entry.data
                        content_type = "application/octet-stream"
                else:
                    # 不支持的数据类型
                    raise InvalidArgumentException(
                        f"Unsupported file data type: {type(entry.data)}"
                    )

                # 添加文件内容部分到 multipart
                multipart_parts.append(("file", (entry.path, content, content_type)))

            # 构建上传 URL
            url = self._get_execd_url(self.FILESYSTEM_UPLOAD_PATH)

            # 发送 POST 请求（multipart/form-data）
            response = await client.post(url, files=multipart_parts)

            # 检查响应状态
            response.raise_for_status()

        except Exception as e:
            # 记录错误日志
            logger.error(f"Failed to write {len(entries)} files", exc_info=e)
            # 转换为 SDK 标准异常
            raise ExceptionConverter.to_sandbox_exception(e) from e

    async def write_file(
        self,
        path: str,
        data: str | bytes | IOBase,
        *,
        encoding: str = "utf-8",
        mode: int = 755,
        owner: str | None = None,
        group: str | None = None,
    ) -> None:
        """
        写入单个文件（便捷方法）

        这是 write_files 的便捷包装，用于写入单个文件。

        参数：
            path (str): 文件路径
            data (str | bytes | IOBase): 文件内容
                - str: 文本内容（使用 encoding 编码）
                - bytes: 二进制内容
                - IOBase: 文件流（必须是二进制流 'rb'）
            encoding (str): 文本编码，默认 "utf-8"
            mode (int): 文件权限（八进制），默认 755
            owner (str | None): 文件所有者（可选）
            group (str | None): 文件组（可选）

        示例：
            ```python
            # 写入文本文件
            await adapter.write_file("hello.py", "print('Hello')")

            # 写入二进制文件
            await adapter.write_file("image.png", binary_data)

            # 带权限设置
            await adapter.write_file(
                "script.sh",
                "#!/bin/bash\\necho hello",
                mode=0o755  # 可执行
            )

            # 从文件流读取
            with open("local.txt", "rb") as f:
                await adapter.write_file("remote.txt", f)
            ```
        """
        # 构建写入条目
        entry = WriteEntry(
            path=path,
            data=data,
            mode=mode,
            owner=owner,
            group=group,
            encoding=encoding,
        )
        # 调用批量写入（单个条目）
        await self.write_files([entry])

    async def create_directories(self, entries: list[WriteEntry]) -> None:
        """
        批量创建多个目录

        使用 API 客户端创建目录，支持设置权限。

        参数：
            entries (list[WriteEntry]): 目录条目列表
                每个条目包含：
                - path: 目录路径（必填）
                - mode: 目录权限（可选）
                - owner: 所有者（可选）
                - group: 组（可选）

        异常：
            SandboxException: 如果创建失败

        示例：
            ```python
            from opensandbox.models.filesystem import WriteEntry

            # 创建单个目录
            await adapter.create_directories([
                WriteEntry(path="/data/logs", mode=755)
            ])

            # 创建多级目录
            await adapter.create_directories([
                WriteEntry(path="/data"),
                WriteEntry(path="/data/logs"),
                WriteEntry(path="/data/cache"),
            ])
            ```
        """
        try:
            # 导入创建目录的 API 函数
            from opensandbox.api.execd.api.filesystem import make_dirs

            # 获取 API 客户端
            client = await self._get_client()

            # 调用 API 创建目录
            # 使用转换器将领域模型转换为 API 模型
            response_obj = await make_dirs.asyncio_detailed(
                client=client,
                body=FilesystemModelConverter.to_api_make_dirs_body(entries),
            )

            # 处理 API 错误
            handle_api_error(response_obj, "Create directories")

        except Exception as e:
            # 记录错误日志
            logger.error("Failed to create directories", exc_info=e)
            # 转换为 SDK 标准异常
            raise ExceptionConverter.to_sandbox_exception(e) from e

    async def delete_files(self, paths: list[str]) -> None:
        """
        批量删除多个文件

        使用 API 客户端删除指定的文件。

        参数：
            paths (list[str]): 文件路径列表

        异常：
            SandboxException: 如果删除失败

        示例：
            ```python
            # 删除单个文件
            await adapter.delete_files(["temp.txt"])

            # 批量删除
            await adapter.delete_files([
                "file1.txt",
                "file2.txt",
                "file3.txt"
            ])
            ```
        """
        try:
            # 导入删除文件的 API 函数
            from opensandbox.api.execd.api.filesystem import remove_files

            # 获取 API 客户端
            client = await self._get_client()

            # 调用 API 删除文件
            response_obj = await remove_files.asyncio_detailed(
                client=client,
                path=paths,
            )

            # 处理 API 错误
            handle_api_error(response_obj, "Delete files")

        except Exception as e:
            # 记录错误日志
            logger.error(f"Failed to delete {len(paths)} files", exc_info=e)
            # 转换为 SDK 标准异常
            raise ExceptionConverter.to_sandbox_exception(e) from e

    async def delete_directories(self, paths: list[str]) -> None:
        """
        批量删除多个目录

        使用 API 客户端删除指定的目录（包括其内容）。

        参数：
            paths (list[str]): 目录路径列表

        异常：
            SandboxException: 如果删除失败

        示例：
            ```python
            # 删除单个目录
            await adapter.delete_directories(["temp"])

            # 批量删除
            await adapter.delete_directories([
                "build",
                "dist",
                "__pycache__"
            ])
            ```
        """
        try:
            # 导入删除目录的 API 函数
            from opensandbox.api.execd.api.filesystem import remove_dirs

            # 获取 API 客户端
            client = await self._get_client()

            # 调用 API 删除目录
            response_obj = await remove_dirs.asyncio_detailed(
                client=client,
                path=paths,
            )

            # 处理 API 错误
            handle_api_error(response_obj, "Delete directories")

        except Exception as e:
            # 记录错误日志
            logger.error(f"Failed to delete {len(paths)} directories", exc_info=e)
            # 转换为 SDK 标准异常
            raise ExceptionConverter.to_sandbox_exception(e) from e

    async def move_files(self, entries: list[MoveEntry]) -> None:
        """
        批量移动或重命名文件和目录

        使用 API 客户端移动或重命名文件/目录。

        参数：
            entries (list[MoveEntry]): 移动条目列表
                每个条目包含：
                - source: 源路径（必填）
                - destination: 目标路径（必填）

        异常：
            SandboxException: 如果移动失败

        示例：
            ```python
            from opensandbox.models.filesystem import MoveEntry

            # 重命名单个文件
            await adapter.move_files([
                MoveEntry(source="old.txt", destination="new.txt")
            ])

            # 批量移动
            await adapter.move_files([
                MoveEntry(source="file1.txt", destination="archive/file1.txt"),
                MoveEntry(source="file2.txt", destination="archive/file2.txt"),
            ])

            # 移动目录
            await adapter.move_files([
                MoveEntry(source="old_dir", destination="new_dir")
            ])
            ```
        """
        try:
            # 导入重命名文件的 API 函数
            from opensandbox.api.execd.api.filesystem import rename_files

            # 使用转换器将领域模型转换为 API 模型
            rename_items = FilesystemModelConverter.to_api_rename_file_items(entries)

            # 获取 API 客户端
            client = await self._get_client()

            # 调用 API 重命名文件
            response_obj = await rename_files.asyncio_detailed(
                client=client,
                body=rename_items,
            )

            # 处理 API 错误
            handle_api_error(response_obj, "Move files")

        except Exception as e:
            # 记录错误日志
            logger.error("Failed to move files", exc_info=e)
            # 转换为 SDK 标准异常
            raise ExceptionConverter.to_sandbox_exception(e) from e

    async def set_permissions(self, entries: list[SetPermissionEntry]) -> None:
        """
        批量设置文件权限

        使用 API 客户端修改文件的权限模式。

        参数：
            entries (list[SetPermissionEntry]): 权限设置条目列表
                每个条目包含：
                - path: 文件路径（必填）
                - mode: 权限模式（必填，八进制）

        异常：
            SandboxException: 如果设置失败

        示例：
            ```python
            from opensandbox.models.filesystem import SetPermissionEntry

            # 设置单个文件权限
            await adapter.set_permissions([
                SetPermissionEntry(path="script.sh", mode=755)
            ])

            # 批量设置
            await adapter.set_permissions([
                SetPermissionEntry(path="script1.sh", mode=755),
                SetPermissionEntry(path="script2.sh", mode=755),
                SetPermissionEntry(path="data.txt", mode=644),
            ])
            ```
        """
        try:
            # 导入设置权限的 API 函数
            from opensandbox.api.execd.api.filesystem import chmod_files

            # 获取 API 客户端
            client = await self._get_client()

            # 调用 API 设置权限
            # 使用转换器将领域模型转换为 API 模型
            response_obj = await chmod_files.asyncio_detailed(
                client=client,
                body=FilesystemModelConverter.to_api_chmod_files_body(entries),
            )

            # 处理 API 错误
            handle_api_error(response_obj, "Set permissions")

        except Exception as e:
            # 记录错误日志
            logger.error("Failed to set permissions", exc_info=e)
            # 转换为 SDK 标准异常
            raise ExceptionConverter.to_sandbox_exception(e) from e

    async def replace_contents(self, entries: list[ContentReplaceEntry]) -> None:
        """
        批量替换文件内容

        使用 API 客户端替换文件中的指定内容。

        参数：
            entries (list[ContentReplaceEntry]): 内容替换条目列表
                每个条目包含：
                - path: 文件路径（必填）
                - old_content: 要替换的旧内容（必填）
                - new_content: 新内容（必填）

        异常：
            SandboxException: 如果替换失败

        示例：
            ```python
            from opensandbox.models.filesystem import ContentReplaceEntry

            # 替换单个文件内容
            await adapter.replace_contents([
                ContentReplaceEntry(
                    path="config.py",
                    old_content="DEBUG = True",
                    new_content="DEBUG = False"
                )
            ])
            ```
        """
        try:
            # 导入替换内容的 API 函数
            from opensandbox.api.execd.api.filesystem import replace_content

            # 获取 API 客户端
            client = await self._get_client()

            # 调用 API 替换内容
            # 使用转换器将领域模型转换为 API 模型
            response_obj = await replace_content.asyncio_detailed(
                client=client,
                body=FilesystemModelConverter.to_api_replace_content_body(entries),
            )

            # 处理 API 错误
            handle_api_error(response_obj, "Replace contents")

        except Exception as e:
            # 记录错误日志
            logger.error("Failed to replace contents", exc_info=e)
            # 转换为 SDK 标准异常
            raise ExceptionConverter.to_sandbox_exception(e) from e

    async def search(self, entry: SearchEntry) -> list[EntryInfo]:
        """
        搜索文件

        使用 API 客户端搜索匹配模式的文件。

        参数：
            entry (SearchEntry): 搜索条目
                - path: 搜索起始路径（必填）
                - pattern: 匹配模式（必填，支持通配符）
                  例如："*.py"、"**/*.txt"

        返回：
            list[EntryInfo]: 匹配的文件信息列表
                每个 EntryInfo 包含：
                - path: 文件路径
                - type: 类型（file/directory）
                - size: 文件大小
                - mode: 权限模式
                - modified_at: 修改时间

        异常：
            SandboxException: 如果搜索失败

        示例：
            ```python
            from opensandbox.models.filesystem import SearchEntry

            # 搜索 Python 文件
            results = await adapter.search(SearchEntry(
                path="/app",
                pattern="*.py"
            ))

            for info in results:
                print(f"{info.path}: {info.size} bytes")

            # 递归搜索
            results = await adapter.search(SearchEntry(
                path="/app",
                pattern="**/*.txt"
            ))
            ```
        """
        try:
            # 导入搜索文件的 API 函数
            from opensandbox.api.execd.api.filesystem import search_files
            # 导入文件信息模型
            from opensandbox.api.execd.models import FileInfo

            # 获取 API 客户端
            client = await self._get_client()

            # 调用 API 搜索文件
            response_obj = await search_files.asyncio_detailed(
                client=client,
                path=entry.path,
                pattern=entry.pattern,
            )

            # 处理 API 错误
            handle_api_error(response_obj, "Search files")

            # 获取解析后的响应
            parsed = response_obj.parsed

            # 如果响应为空，返回空列表
            if not parsed:
                return []

            # 验证响应类型并转换
            if isinstance(parsed, list) and all(isinstance(x, FileInfo) for x in parsed):
                # 使用转换器将 API 模型转换为 SDK 模型
                return FilesystemModelConverter.to_entry_info_list(parsed)

            # 响应类型不符，抛出异常
            raise SandboxApiException(
                message="Search files failed: unexpected response type",
                request_id=extract_request_id(getattr(response_obj, "headers", None)),
            )

        except Exception as e:
            # 记录错误日志
            logger.error("Failed to search files", exc_info=e)
            # 转换为 SDK 标准异常
            raise ExceptionConverter.to_sandbox_exception(e) from e

    async def get_file_info(self, paths: list[str]) -> dict[str, EntryInfo]:
        """
        批量获取文件信息

        使用 API 客户端获取多个文件的详细信息。

        参数：
            paths (list[str]): 文件路径列表

        返回：
            dict[str, EntryInfo]: 文件信息字典
                - key: 文件路径
                - value: EntryInfo 对象（包含大小、权限、修改时间等）

        异常：
            SandboxException: 如果获取失败

        示例：
            ```python
            # 获取单个文件信息
            info = await adapter.get_file_info(["config.py"])
            print(info["config.py"].size)

            # 批量获取
            infos = await adapter.get_file_info([
                "file1.txt",
                "file2.txt",
                "file3.txt"
            ])

            for path, info in infos.items():
                print(f"{path}: {info.size} bytes, mode={info.mode}")
            ```
        """
        try:
            # 导入获取文件信息的 API 函数
            from opensandbox.api.execd.api.filesystem import get_files_info

            # 获取 API 客户端
            client = await self._get_client()

            # 调用 API 获取文件信息
            response_obj = await get_files_info.asyncio_detailed(
                client=client,
                path=paths,
            )

            # 处理 API 错误
            handle_api_error(response_obj, "Get file info")

            # 如果响应为空，返回空字典
            if not response_obj.parsed:
                return {}

            # 使用转换器将 API 模型转换为 SDK 模型
            return FilesystemModelConverter.to_entry_info_map(response_obj.parsed)

        except Exception as e:
            # 记录错误日志
            logger.error(f"Failed to get file info for {len(paths)} paths", exc_info=e)
            # 转换为 SDK 标准异常
            raise ExceptionConverter.to_sandbox_exception(e) from e

    def _build_download_request(
            self, path: str, range_header: str | None = None
    ) -> _DownloadRequest:
        """
        构建文件下载请求

        辅助方法，为文件下载操作构建 HTTP 请求的各个组成部分。

        参数：
            path (str): 文件路径
            range_header (str | None): Range 请求头（可选）
                - 用于分块读取
                - 格式："bytes=start-end"

        返回：
            _DownloadRequest: 包含 URL、参数和请求头的字典
                - url: 完整的下载 URL
                - params: 查询参数（当前实现为 None）
                - headers: 请求头（包含 Range 等）

        实现细节：
            - 文件路径使用 URL 编码（quote）处理，确保特殊字符正确传输
            - Range 头添加到请求头中，而不是查询参数

        示例：
            ```python
            request = self._build_download_request("file.txt")
            # 返回：{
            #     "url": "http://.../files/download?path=file.txt",
            #     "params": None,
            #     "headers": {}
            # }

            request = self._build_download_request(
                "file.txt",
                range_header="bytes=0-1023"
            )
            # 返回：{
            #     "url": "http://.../files/download?path=file.txt",
            #     "params": None,
            #     "headers": {"Range": "bytes=0-1023"}
            # }
            ```
        """
        # URL 编码文件路径
        # quote 将特殊字符转换为 %XX 格式，safe="/" 保留斜杠
        encoded_path = quote(path, safe="/")

        # 构建下载 URL
        # path 作为查询参数传递
        url = f"{self._get_execd_url(self.FILESYSTEM_DOWNLOAD_PATH)}?path={encoded_path}"

        # 初始化请求头
        headers: dict[str, str] = {}

        # 如果有 Range 头，添加到请求头中
        if range_header:
            headers["Range"] = range_header

        # 返回请求数据结构
        return {
            "url": url,
            "params": None,
            "headers": headers,
        }
