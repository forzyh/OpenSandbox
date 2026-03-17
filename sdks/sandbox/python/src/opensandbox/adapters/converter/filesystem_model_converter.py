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
文件系统模型转换器模块 - Filesystem Model Converter

本模块提供了 FilesystemModelConverter 类，用于在 API 模型和领域模型之间转换文件系统操作数据。

设计目的：
    - 将 API 模型转换为 SDK 领域模型（FileInfo -> EntryInfo）
    - 将领域模型转换为 API 请求体（WriteEntry -> MakeDirsBody 等）
    - 处理 openapi-python-client 生成的模型与 SDK 模型之间的差异

核心功能：
    - to_entry_info: 将 API FileInfo 转换为领域 EntryInfo
    - to_entry_info_list: 批量转换 FileInfo 列表
    - to_entry_info_map: 将 API 响应转换为路径到 EntryInfo 的映射
    - to_api_make_dirs_body: 将 WriteEntry 列表转换为 MakeDirsBody
    - to_api_chmod_files_body: 将 SetPermissionEntry 列表转换为 ChmodFilesBody
    - to_api_replace_content_body: 将 ContentReplaceEntry 列表转换为 ReplaceContentBody
    - to_api_rename_file_items: 将 MoveEntry 列表转换为 RenameFileItem 列表

使用示例：
    ```python
    from opensandbox.adapters.converter.filesystem_model_converter import FilesystemModelConverter
    from opensandbox.models.filesystem import WriteEntry

    # 转换 FileInfo 到 EntryInfo
    entry_info = FilesystemModelConverter.to_entry_info(api_file_info)

    # 转换为创建目录的 API 请求体
    entries = [WriteEntry(path="/app/logs", mode=0o755)]
    body = FilesystemModelConverter.to_api_make_dirs_body(entries)
    ```
"""

from typing import Any

from opensandbox.api.execd.models import FileInfo
from opensandbox.models.filesystem import (
    ContentReplaceEntry,    # 内容替换条目
    EntryInfo,              # 文件/目录信息
    MoveEntry,              # 移动/重命名条目
    SetPermissionEntry,     # 权限设置条目
    WriteEntry,             # 写入条目
)


class FilesystemModelConverter:
    """
    文件系统模型转换器工具类

    本类提供了静态方法，用于在 API 模型和领域模型之间转换文件系统操作数据。
    遵循 SandboxModelConverter 的模式。

    转换方向：
        1. API -> 领域：FileInfo -> EntryInfo
        2. 领域 -> API: WriteEntry -> MakeDirsBody 等

    使用示例：
        ```python
        from opensandbox.adapters.converter.filesystem_model_converter import FilesystemModelConverter

        # API 到领域
        entry_info = FilesystemModelConverter.to_entry_info(api_file_info)

        # 领域到 API
        body = FilesystemModelConverter.to_api_chmod_files_body(entries)
        ```
    """

    @staticmethod
    def to_entry_info(api_file_info: FileInfo) -> EntryInfo:
        """
        将 API FileInfo 转换为领域 EntryInfo

        此方法负责将 openapi-python-client 生成的 FileInfo 对象转换为
        SDK 的 EntryInfo 对象。所有字段直接映射。

        参数：
            api_file_info (FileInfo): API 文件信息对象
                - path: 文件/目录路径
                - mode: 权限模式
                - owner: 所有者
                - group: 组
                - size: 大小（字节）
                - modified_at: 修改时间
                - created_at: 创建时间

        返回：
            EntryInfo: 领域模型文件信息对象
                - 包含与 API 对象相同的字段

        使用示例：
            ```python
            entry_info = FilesystemModelConverter.to_entry_info(api_file_info)
            print(f"Path: {entry_info.path}, Size: {entry_info.size} bytes")
            ```
        """
        return EntryInfo(
            path=api_file_info.path,          # 文件/目录路径
            mode=api_file_info.mode,          # 权限模式
            owner=api_file_info.owner,        # 所有者
            group=api_file_info.group,        # 组
            size=api_file_info.size,          # 大小（字节）
            modified_at=api_file_info.modified_at,  # 修改时间
            created_at=api_file_info.created_at,    # 创建时间
        )

    @staticmethod
    def to_entry_info_list(api_file_infos: list[FileInfo]) -> list[EntryInfo]:
        """
        将 API FileInfo 列表转换为领域 EntryInfo 列表

        批量转换多个文件信息对象。

        参数：
            api_file_infos (list[FileInfo]): API 文件信息列表

        返回：
            list[EntryInfo]: 领域模型文件信息列表

        使用示例：
            ```python
            entry_list = FilesystemModelConverter.to_entry_info_list(api_file_list)
            for entry in entry_list:
                print(f"{entry.path}: {entry.size} bytes")
            ```
        """
        # 空列表检查
        if not api_file_infos:
            return []

        # 逐项转换
        return [FilesystemModelConverter.to_entry_info(item) for item in api_file_infos]

    @staticmethod
    def to_entry_info_map(api_response: Any) -> dict[str, EntryInfo]:
        """
        将 API 响应转换为路径到 EntryInfo 的映射

        此方法处理两种类型的 API 响应：
        1. 带有 additional_properties 属性的对象
        2. 普通字典

        参数：
            api_response (Any): API 响应对象
                - 可以是带有 additional_properties 的对象
                - 也可以是普通字典

        返回：
            dict[str, EntryInfo]: 路径到文件信息的映射
                - 键：文件/目录路径
                - 值：EntryInfo 对象

        使用示例：
            ```python
            response = await get_files_info.asyncio_detailed(client=client)
            info_map = FilesystemModelConverter.to_entry_info_map(response.parsed)

            for path, info in info_map.items():
                print(f"{path}: {info.size} bytes")
            ```
        """
        # 空响应检查
        if not api_response:
            return {}

        result: dict[str, EntryInfo] = {}

        # 处理带有 additional_properties 的对象
        if hasattr(api_response, "additional_properties"):
            for path, info_data in api_response.additional_properties.items():
                if isinstance(info_data, FileInfo):
                    result[path] = FilesystemModelConverter.to_entry_info(info_data)

        # 处理普通字典
        elif isinstance(api_response, dict):
            for path, info_data in api_response.items():
                if isinstance(info_data, FileInfo):
                    result[path] = FilesystemModelConverter.to_entry_info(info_data)

        return result

    @staticmethod
    def to_api_make_dirs_body(entries: list[WriteEntry]) -> Any:
        """
        将目录条目列表转换为 MakeDirsBody

        此方法将 SDK 的 WriteEntry 列表转换为 openapi-python-client 生成的
        MakeDirsBody 对象，用于创建目录的 API 请求。

        参数：
            entries (list[WriteEntry]): 目录条目列表
                - path: 目录路径
                - mode: 权限模式
                - owner: 所有者
                - group: 组

        返回：
            MakeDirsBody: API 请求体对象
                - 可以直接传递给 API 函数

        使用示例：
            ```python
            entries = [
                WriteEntry(path="/app/logs", mode=0o755),
                WriteEntry(path="/app/data", mode=0o700, owner="appuser")
            ]
            body = FilesystemModelConverter.to_api_make_dirs_body(entries)
            await make_dirs.asyncio_detailed(client=client, body=body)
            ```
        """
        # 导入 API 模型
        from opensandbox.api.execd.models.make_dirs_body import MakeDirsBody

        # 构建目录数据字典
        dirs_data = {
            entry.path: {
                "mode": entry.mode,
                "owner": entry.owner,
                "group": entry.group,
            }
            for entry in entries
        }

        # 使用 from_dict 创建 API 对象
        return MakeDirsBody.from_dict(dirs_data)

    @staticmethod
    def to_api_chmod_files_body(entries: list[SetPermissionEntry]) -> Any:
        """
        将权限设置条目列表转换为 ChmodFilesBody

        此方法将 SDK 的 SetPermissionEntry 列表转换为 openapi-python-client 生成的
        ChmodFilesBody 对象，用于修改文件权限的 API 请求。

        参数：
            entries (list[SetPermissionEntry]): 权限设置条目列表
                - path: 文件/目录路径
                - mode: 权限模式
                - owner: 所有者
                - group: 组

        返回：
            ChmodFilesBody: API 请求体对象
                - 可以直接传递给 API 函数

        使用示例：
            ```python
            entries = [
                SetPermissionEntry(path="/app/script.py", mode=0o755),
                SetPermissionEntry(path="/app/data", owner="appuser")
            ]
            body = FilesystemModelConverter.to_api_chmod_files_body(entries)
            await chmod_files.asyncio_detailed(client=client, body=body)
            ```
        """
        # 导入 API 模型
        from opensandbox.api.execd.models.chmod_files_body import ChmodFilesBody

        # 构建权限数据字典
        permission_data = {
            entry.path: {
                "mode": entry.mode,
                "owner": entry.owner,
                "group": entry.group,
            }
            for entry in entries
        }

        # 使用 from_dict 创建 API 对象
        return ChmodFilesBody.from_dict(permission_data)

    @staticmethod
    def to_api_replace_content_body(entries: list[ContentReplaceEntry]) -> Any:
        """
        将内容替换条目列表转换为 ReplaceContentBody

        此方法将 SDK 的 ContentReplaceEntry 列表转换为 openapi-python-client 生成的
        ReplaceContentBody 对象，用于替换文件内容的 API 请求。

        参数：
            entries (list[ContentReplaceEntry]): 内容替换条目列表
                - path: 文件路径
                - old_content: 要替换的旧内容
                - new_content: 新内容

        返回：
            ReplaceContentBody: API 请求体对象
                - 可以直接传递给 API 函数

        注意：
            Execd API 期望键名为 "old" 和 "new"（参见 execd-api.yaml 中的 ReplaceFileContentItem）

        使用示例：
            ```python
            entries = [
                ContentReplaceEntry(
                    path="/app/config.py",
                    old_content="DEBUG = True",
                    new_content="DEBUG = False"
                )
            ]
            body = FilesystemModelConverter.to_api_replace_content_body(entries)
            await replace_content.asyncio_detailed(client=client, body=body)
            ```
        """
        # 导入 API 模型
        from opensandbox.api.execd.models.replace_content_body import ReplaceContentBody

        # 构建替换数据字典
        # 注意：Execd API 期望键名为 "old" 和 "new"
        replace_data = {
            entry.path: {
                "old": entry.old_content,  # 旧内容
                "new": entry.new_content,  # 新内容
            }
            for entry in entries
        }

        # 使用 from_dict 创建 API 对象
        return ReplaceContentBody.from_dict(replace_data)

    @staticmethod
    def to_api_rename_file_items(entries: list[MoveEntry]) -> Any:
        """
        将移动条目列表转换为 RenameFileItem 列表

        此方法将 SDK 的 MoveEntry 列表转换为 openapi-python-client 生成的
        RenameFileItem 对象列表，用于重命名/移动文件的 API 请求。

        参数：
            entries (list[MoveEntry]): 移动条目列表
                - src: 源路径
                - dest: 目标路径

        返回：
            list[RenameFileItem]: RenameFileItem 对象列表
                - 可以直接传递给 API 函数

        使用示例：
            ```python
            entries = [
                MoveEntry(src="/app/old_name.txt", dest="/app/new_name.txt"),
                MoveEntry(src="/app/old_dir", dest="/app/new_dir")
            ]
            items = FilesystemModelConverter.to_api_rename_file_items(entries)
            await rename_files.asyncio_detailed(client=client, items=items)
            ```
        """
        # 导入 API 模型
        from opensandbox.api.execd.models.rename_file_item import RenameFileItem

        # 转换为 RenameFileItem 列表
        return [RenameFileItem(src=e.src, dest=e.dest) for e in entries]
