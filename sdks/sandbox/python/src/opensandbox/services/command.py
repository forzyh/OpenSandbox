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
命令执行服务接口模块 - Commands Service Protocol

本模块定义了 Commands 服务协议接口，用于沙箱内的命令执行操作。

设计目的：
    - 定义命令执行服务的接口规范
    - 使用 Protocol 实现鸭子类型（结构性子类型）
    - 支持异步命令执行和流式输出

核心接口：
    - Commands: 命令执行服务协议

主要方法：
    - run: 执行 Shell 命令（支持流式输出）
    - interrupt: 中断正在运行的命令
    - get_command_status: 获取命令执行状态
    - get_background_command_logs: 获取后台命令日志

使用示例：
    ```python
    from opensandbox.services.command import Commands
    from opensandbox.models.execd import RunCommandOpts, ExecutionHandlers

    # 实现 Commands 接口的类
    class MyCommandService:
        async def run(self, command, opts=None, handlers=None):
            ...
        async def interrupt(self, execution_id):
            ...
        async def get_command_status(self, execution_id):
            ...
        async def get_background_command_logs(self, execution_id, cursor=None):
            ...
    ```
"""

from typing import Protocol

from opensandbox.models.execd import (
    CommandLogs,          # 命令日志
    CommandStatus,        # 命令状态
    Execution,            # 执行结果
    ExecutionHandlers,    # 执行处理器
    RunCommandOpts,       # 命令执行选项
)


class Commands(Protocol):
    """
    命令执行服务协议接口

    本接口定义了沙箱环境中命令执行的核心功能。
    使用 Protocol 实现结构性子类型，任何实现这些方法的类都自动成为 Commands 的子类型。

    功能特性：
        - 安全命令执行：在隔离的沙箱环境中执行 Shell 命令
        - 流式输出支持：实时获取命令的 stdout/stderr 输出
        - 超时处理：支持命令执行超时控制
        - 会话管理：跟踪和管理命令执行实例
        - 后台执行：支持后台模式和日志获取

    主要方法：
        run: 执行 Shell 命令
        interrupt: 中断正在运行的命令
        get_command_status: 获取命令状态
        get_background_command_logs: 获取后台命令日志

    实现说明：
        CommandsAdapter 是此接口的主要实现，它：
        1. 使用 openapi-python-client 生成的 API 客户端
        2. 使用 SSE 处理流式响应
        3. 处理异常转换和错误处理

    使用示例：
        ```python
        from opensandbox import Sandbox

        async with await Sandbox.create("python:3.11") as sandbox:
            # 执行命令
            result = await sandbox.commands.run("ls -la")
            print(f"Exit code: {result.exit_code}")

            # 带流式处理
            async def on_stdout(msg):
                print(f"Output: {msg.text}")

            result = await sandbox.commands.run(
                "python script.py",
                handlers=ExecutionHandlers(on_stdout=on_stdout)
            )

            # 中断命令
            await sandbox.commands.interrupt(result.id)

            # 获取状态
            status = await sandbox.commands.get_command_status(result.id)
        ```
    """

    async def run(
        self,
        command: str,
        *,
        opts: RunCommandOpts | None = None,
        handlers: ExecutionHandlers | None = None,
    ) -> Execution:
        """
        在沙箱环境中执行 Shell 命令

        这是命令执行的核心方法，支持前台（流式）和后台两种执行模式。

        执行模式：
            - 前台模式（默认）：实时流式输出，适合交互式命令
            - 后台模式：命令在后台执行，通过 get_background_command_logs 获取日志

        参数：
            command (str): 要执行的 Shell 命令文本
                - 例如："ls -la"、"python script.py"
                - 不能为空或只包含空白字符

            opts (RunCommandOpts | None): 命令执行选项（可选）
                - background: 是否后台执行
                - working_directory: 工作目录
                - timeout: 超时时间
                - envs: 环境变量
                - uid/gid: 运行用户/组 ID

            handlers (ExecutionHandlers | None): 流式处理器（可选）
                - on_stdout: 标准输出回调
                - on_stderr: 标准错误回调
                - on_result: 执行结果回调
                - on_error: 错误回调
                - on_init: 初始化回调
                - on_execution_complete: 完成回调

        返回：
            Execution: 执行结果对象，包含：
                - id: 执行 ID
                - execution_count: 执行计数
                - result: 执行结果列表
                - error: 错误信息（如果失败）
                - logs.stdout: 标准输出列表
                - logs.stderr: 标准错误列表
                - exit_code: 退出码

        异常：
            SandboxException: 如果操作失败
            InvalidArgumentException: 如果命令为空

        使用示例：
            ```python
            # 基本用法
            result = await commands.run("ls -la")
            for line in result.logs.stdout:
                print(line.text)

            # 带选项
            result = await commands.run(
                "python script.py",
                opts=RunCommandOpts(
                    working_directory="/app",
                    timeout=timedelta(minutes=5)
                )
            )

            # 带流式处理器
            async def on_stdout(msg):
                print(f"STDOUT: {msg.text}")

            result = await commands.run(
                "python long_running.py",
                handlers=ExecutionHandlers(on_stdout=on_stdout)
            )
            ```
        """
        ...

    async def interrupt(self, execution_id: str) -> None:
        """
        中断并终止正在运行的命令执行

        此方法向与给定执行 ID 关联的进程发送终止信号
        （通常是 SIGTERM/SIGKILL）。

        参数：
            execution_id (str): 要中断的执行实例的唯一标识符
                - 从 run() 方法的返回结果中获取

        异常：
            SandboxException: 如果操作失败
                - 执行可能已经完成或不存在

        使用示例：
            ```python
            # 启动长时间运行的命令
            result = await commands.run("sleep 60")
            execution_id = result.id

            # 在需要时中断
            await commands.interrupt(execution_id)
            print("Command interrupted")
            ```

        注意事项：
            - 中断是异步的，可能需要一些时间完成
            - 某些命令可能无法被中断（如系统调用）
            - 中断后应检查执行状态确认是否成功
        """
        ...

    async def get_command_status(self, execution_id: str) -> CommandStatus:
        """
        获取命令的当前运行状态

        查询指定执行实例的当前状态，包括运行状态和退出码（如果可用）。

        参数：
            execution_id (str): 要查询的执行实例的唯一标识符

        返回：
            CommandStatus: 命令状态对象，包含：
                - id: 命令 ID
                - content: 原始命令内容
                - running: 是否仍在运行
                - exit_code: 退出码（如果已完成）
                - error: 错误消息（如果失败）
                - started_at: 开始时间
                - finished_at: 完成时间

        异常：
            SandboxException: 如果操作失败
                - 执行 ID 可能不存在

        使用示例：
            ```python
            status = await commands.get_command_status(execution_id)

            if status.running:
                print("Command is still running")
            else:
                print(f"Command finished with exit code: {status.exit_code}")
            ```
        """
        ...

    async def get_background_command_logs(
        self, execution_id: str, cursor: int | None = None
    ) -> CommandLogs:
        """
        获取后台命令的日志（非流式）

        获取后台执行命令的输出日志，支持使用游标进行增量读取。

        参数：
            execution_id (str): 要查询的执行实例的唯一标识符

            cursor (int | None): 可选的行游标，用于增量读取
                - None: 从头开始获取日志
                - 整数值：从上次返回的游标位置继续获取
                - 用于分页获取大量日志

        返回：
            CommandLogs: 命令日志对象，包含：
                - content: 原始输出内容（stdout/stderr 混合）
                - cursor: 最新游标位置（如果有更多日志）

        异常：
            SandboxException: 如果操作失败

        使用示例：
            ```python
            # 获取完整日志
            logs = await commands.get_background_command_logs(execution_id)
            print(logs.content)

            # 增量获取日志
            cursor = None
            while True:
                logs = await commands.get_background_command_logs(
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
        ...
