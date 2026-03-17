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
执行模型转换器模块 - Execution Converter

本模块提供了 ExecutionConverter 类，用于在 API 模型和领域模型之间转换执行相关的操作。

设计目的：
    - 将领域模型（RunCommandOpts）转换为 API 模型（RunCommandRequest）
    - 处理 openapi-python-client 生成的模型与 SDK 模型之间的差异
    - 提供 JSON 序列化的工具方法

核心功能：
    - to_api_run_command_request: 将命令和选项转换为 API 请求对象
    - to_api_run_command_json: 将命令和选项转换为 JSON 可序列化的字典

模型差异处理：
    - 领域模型使用 working_directory，API 模型使用 cwd
    - 领域模型使用 timedelta 表示超时，API 模型使用毫秒数
    - API 模型使用 attrs，领域模型使用 pydantic

使用示例：
    ```python
    from opensandbox.adapters.converter.execution_converter import ExecutionConverter
    from opensandbox.models.execd import RunCommandOpts
    from datetime import timedelta

    opts = RunCommandOpts(
        working_directory="/app",
        timeout=timedelta(minutes=5),
        env={"PYTHONPATH": "/workspace"}
    )

    # 转换为 API 请求对象
    api_request = ExecutionConverter.to_api_run_command_request("python script.py", opts)

    # 转换为 JSON 字典
    json_body = ExecutionConverter.to_api_run_command_json("python script.py", opts)
    ```
"""

from typing import Any

from opensandbox.api.execd.models.run_command_request import (
    RunCommandRequest as ApiRunCommandRequest,
)
from opensandbox.models.execd import RunCommandOpts


class ExecutionConverter:
    """
    执行模型转换器工具类

    本类提供了静态方法，用于在 API 模型和领域模型之间转换执行相关的操作。
    API 模型由 openapi-python-client 生成并使用 attrs，领域模型使用 pydantic。

    转换规则：
        - working_directory -> cwd
        - timeout (timedelta) -> timeout (毫秒数)
        - envs -> RunCommandRequestEnvs
        - background, uid, gid 直接映射

    使用示例：
        ```python
        from opensandbox.adapters.converter.execution_converter import ExecutionConverter
        from opensandbox.models.execd import RunCommandOpts

        opts = RunCommandOpts(working_directory="/app", timeout=timedelta(seconds=30))
        json_body = ExecutionConverter.to_api_run_command_json("ls -la", opts)
        ```
    """

    @staticmethod
    def to_api_run_command_request(command: str, opts: RunCommandOpts) -> ApiRunCommandRequest:
        """
        将领域命令和选项转换为 API RunCommandRequest

        此方法负责将 SDK 的 RunCommandOpts 转换为 openapi-python-client 生成的
        RunCommandRequest 对象。处理字段名称和单位转换。

        参数：
            command (str): 要执行的命令
                - 例如："python script.py"、"ls -la"

            opts (RunCommandOpts): 命令执行选项
                - working_directory: 工作目录
                - timeout: 超时时间（timedelta）
                - envs: 环境变量
                - uid/gid: 用户/组 ID
                - background: 是否后台执行

        返回：
            ApiRunCommandRequest: API 请求对象
                - 可以直接传递给 openapi-python-client 的 API 函数

        字段映射说明：
            - opts.working_directory -> cwd (API 字段名)
            - opts.timeout -> timeout_milliseconds (毫秒数)
            - opts.envs -> RunCommandRequestEnvs (特殊类型)
            - opts.background, uid, gid -> 直接映射

        特殊处理：
            - None 值转换为 UNSET，表示不传递该字段
            - timeout 从 timedelta 转换为毫秒整数
            - envs 需要包装到 RunCommandRequestEnvs 对象
        """
        # 导入必要的类型
        from opensandbox.api.execd.models.run_command_request_envs import (
            RunCommandRequestEnvs,
        )
        from opensandbox.api.execd.types import UNSET

        # 转换工作目录
        # 领域模型使用 working_directory，API 模型使用 cwd
        # 如果为 None，使用 UNSET 表示不传递此字段
        cwd = UNSET
        if opts.working_directory:
            cwd = opts.working_directory

        # 转换后台执行标志
        background = UNSET
        if opts.background:
            background = opts.background

        # 转换超时时间
        # 领域模型使用 timedelta，API 模型使用毫秒数
        timeout_milliseconds = UNSET
        if opts.timeout is not None:
            # 将 timedelta 转换为毫秒整数
            timeout_milliseconds = int(opts.timeout.total_seconds() * 1000)

        # 转换用户 ID
        uid = UNSET
        if opts.uid is not None:
            uid = opts.uid

        # 转换组 ID
        gid = UNSET
        if opts.gid is not None:
            gid = opts.gid

        # 转换环境变量
        # 需要包装到 RunCommandRequestEnvs 对象
        envs = UNSET
        if opts.envs is not None:
            envs_payload = RunCommandRequestEnvs()
            for key, value in opts.envs.items():
                envs_payload[key] = value
            envs = envs_payload

        # 创建并返回 API 请求对象
        return ApiRunCommandRequest(
            command=command,
            background=background,
            cwd=cwd,  # 领域模型使用 working_directory，API 使用 cwd
            timeout=timeout_milliseconds,
            uid=uid,
            gid=gid,
            envs=envs,
            # 注意：handlers 不包含在 API 请求中，它们是本地处理的
        )

    @staticmethod
    def to_api_run_command_json(command: str, opts: RunCommandOpts) -> dict[str, Any]:
        """
        将命令和选项转换为 JSON 可序列化的字典

        此方法用于将命令和选项转换为可以直接传递给 httpx 请求的字典格式。
        它集中处理 attrs 和 pydantic 模型之间的差异。

        参数：
            command (str): 要执行的命令
            opts (RunCommandOpts): 命令执行选项

        返回：
            dict[str, Any]: JSON 可序列化的字典
                - 可以直接作为 httpx 请求的 json 参数

        处理逻辑：
            1. 先调用 to_api_run_command_request 创建 API 请求对象
            2. 尝试使用 to_dict() 方法转换为字典
            3. 如果不支持 to_dict()，使用 __dict__ 作为后备方案

        使用示例：
            ```python
            from opensandbox.adapters.converter.execution_converter import ExecutionConverter
            from opensandbox.models.execd import RunCommandOpts

            opts = RunCommandOpts(timeout=timedelta(seconds=30))
            json_body = ExecutionConverter.to_api_run_command_json("python script.py", opts)

            # 使用 httpx 发送请求
            async with client.stream("POST", url, json=json_body) as response:
                ...
            ```
        """
        # 先创建 API 请求对象
        api_request = ExecutionConverter.to_api_run_command_request(command, opts)

        # 尝试使用 to_dict() 方法
        # openapi-python-client 生成的模型通常支持此方法
        if hasattr(api_request, "to_dict"):
            return api_request.to_dict()

        # 后备方案：使用 __dict__
        # 这通常不会发生，但作为保险措施
        return dict(getattr(api_request, "__dict__", {}))
