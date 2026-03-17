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
代码解释器主模块 - Code Interpreter

本模块提供了 CodeInterpreter 类，是代码解释器 SDK 的核心入口。

设计目的：
    - 封装基础沙箱功能，提供专业化的代码执行接口
    - 支持多语言代码执行（Python、JavaScript、Bash、Java、Kotlin）
    - 提供执行上下文管理，支持变量持久化
    - 集成沙箱的文件系统和命令执行功能

核心功能：
    - 代码执行：通过 codes 服务执行多语言代码
    - 文件操作：通过 files 服务操作沙箱文件系统
    - 命令执行：通过 commands 服务执行 Shell 命令
    - 资源监控：通过 metrics 服务获取资源使用情况

架构说明：
    CodeInterpreter 是 Sandbox 的封装层，采用组合模式：
    - 内部持有一个 Sandbox 实例
    - 持有一个 Codes 服务实例用于代码执行
    - 委托文件、命令、指标操作到内部 Sandbox

    创建流程：
    1. 用户首先创建 Sandbox 实例
    2. 调用 CodeInterpreter.create(sandbox) 包装
    3. create() 方法创建 Codes 服务并返回 CodeInterpreter

    设计理由：
    - 职责分离：Sandbox 负责基础设施，CodeInterpreter 负责代码执行
    - 灵活组合：可以单独使用 Sandbox 或 CodeInterpreter
    - 清晰接口：codes 属性提供明确的代码执行入口

使用示例：
    ```python
    from opensandbox import Sandbox
    from code_interpreter import CodeInterpreter

    # 创建沙箱
    sandbox = await Sandbox.create("python:3.11")

    # 创建代码解释器
    interpreter = await CodeInterpreter.create(sandbox=sandbox)

    # 执行代码
    from code_interpreter.models.code import SupportedLanguage
    context = await interpreter.codes.create_context(SupportedLanguage.PYTHON)
    result = await interpreter.codes.run("print('Hello World')", context=context)

    # 访问底层沙箱进行文件操作
    await interpreter.files.write_file("data.txt", "content")

    # 清理资源
    await sandbox.kill()
    await sandbox.close()
    ```
"""

import logging

# 导入异常类
from opensandbox.exceptions import (
    InvalidArgumentException,     # 无效参数异常
    SandboxException,             # 沙箱通用异常
    SandboxInternalException,     # 沙箱内部异常
)
# 导入基础沙箱类
from opensandbox.sandbox import Sandbox

# 导入适配器工厂
# 用于创建代码执行服务
from code_interpreter.adapters.factory import AdapterFactory
# 导入代码服务接口
from code_interpreter.services.code import Codes

# 配置模块日志记录器
logger = logging.getLogger(__name__)


class CodeInterpreter:
    """
    代码解释器主类 - 提供安全、隔离的代码执行能力

    本类扩展了基础沙箱功能，提供专业化的代码执行特性：
    - 多语言代码执行：Python、JavaScript、Bash、Java、Kotlin
    - 会话管理：持久化的执行上下文，变量状态跨执行保持
    - 沙箱集成：完全访问底层沙箱的文件系统和命令执行功能
    - 流式执行：实时代码执行与输出流式传输
    - 变量检查：访问执行变量和状态

    核心属性：
        sandbox (Sandbox): 底层沙箱实例
            - 提供文件系统、命令执行、资源监控等基础功能
            - 可通过此属性访问所有沙箱功能

        codes (Codes): 代码执行服务
            - 提供多语言代码执行能力
            - 支持执行上下文管理
            - 支持流式输出和中断

        files: 文件系统服务（委托给 sandbox.files）
            - 提供文件读写、目录操作等功能

        commands: 命令执行服务（委托给 sandbox.commands）
            - 提供 Shell 命令执行功能

        metrics: 指标服务（委托给 sandbox.metrics）
            - 提供资源使用情况监控

        id (str): 沙箱/解释器的唯一标识符

    设计模式：
        - 组合模式（Composition）：内部持有 Sandbox 实例
        - 代理模式（Proxy）：files/commands/metrics 委托给内部 Sandbox
        - 工厂模式（Factory）：使用 create() 类方法创建实例

    使用示例：
        ```python
        # 创建沙箱
        sandbox = await Sandbox.create(
            "python:3.11",
            resource={"cpu": "1", "memory": "2Gi"}
        )

        # 创建代码解释器
        interpreter = await CodeInterpreter.create(sandbox=sandbox)

        # 执行代码（带上下文）
        from code_interpreter.models.code import SupportedLanguage
        context = await interpreter.codes.create_context(SupportedLanguage.PYTHON)

        result = await interpreter.codes.run(
            "print('Hello World')",
            context=context
        )
        print(result.logs.stdout)  # Hello World

        # 访问底层沙箱进行文件操作
        from opensandbox.models.filesystem import WriteEntry
        await interpreter.sandbox.files.write_files([
            WriteEntry(path="data.txt", data="Hello")
        ])

        # 在代码中读取文件
        file_result = await interpreter.codes.run(
            "with open('data.txt') as f: print(f.read())",
            context=context,
        )

        # 始终清理资源
        await sandbox.kill()
        await sandbox.close()
        ```

    注意事项：
        - 必须显式调用 sandbox.kill() 终止沙箱
        - 必须调用 sandbox.close() 关闭连接
        - 建议使用 try/finally 确保资源清理
    """

    def __init__(self, sandbox: Sandbox, code_service: Codes) -> None:
        """
        初始化代码解释器

        构造函数保存沙箱实例和代码服务实例。

        注意：此构造函数仅供内部使用。
        请使用 CodeInterpreter.create() 类方法创建实例。

        参数：
            sandbox (Sandbox): 底层沙箱实例
                - 提供文件系统、命令执行、资源监控等基础功能
            code_service (Codes): 代码执行服务实现
                - 提供多语言代码执行能力
                - 实现 Codes Protocol 接口

        内部实现：
            构造函数仅保存两个核心组件的引用：
            - _sandbox: 底层沙箱实例
            - _code_service: 代码执行服务

        示例：
            ```python
            # 不推荐直接使用构造函数
            # interpreter = CodeInterpreter(sandbox, code_service)

            # 推荐使用工厂方法
            interpreter = await CodeInterpreter.create(sandbox=sandbox)
            ```
        """
        # 保存底层沙箱实例
        self._sandbox = sandbox

        # 保存代码执行服务
        self._code_service = code_service

    @property
    def sandbox(self) -> Sandbox:
        """
        获取底层沙箱实例

        此属性提供对底层沙箱的完全访问权限。

        返回：
            Sandbox: 底层沙箱实例

        使用场景：
            - 访问沙箱的生命周期管理方法（kill、close）
            - 访问沙箱的完整 API（可能未在 CodeInterpreter 中暴露）
            - 获取沙箱的连接配置等信息

        示例：
            ```python
            # 获取沙箱 ID
            sandbox_id = interpreter.sandbox.id

            # 终止沙箱
            await interpreter.sandbox.kill()

            # 关闭连接
            await interpreter.sandbox.close()

            # 获取连接配置
            config = interpreter.sandbox.connection_config
            ```
        """
        return self._sandbox

    @property
    def id(self) -> str:
        """
        获取代码解释器的唯一标识符

        此 ID 与底层沙箱的 ID 相同，因为代码解释器是沙箱的封装。

        返回：
            str: 代码解释器/沙箱的唯一标识符

        示例：
            ```python
            interpreter = await CodeInterpreter.create(sandbox=sandbox)
            print(f"Interpreter ID: {interpreter.id}")
            # 输出：Interpreter ID: sandbox-123
            ```
        """
        return self._sandbox.id

    @property
    def files(self):
        """
        获取文件系统服务

        此属性委托给底层沙箱的 files 服务，提供文件操作功能。

        返回：
            Filesystem: 文件系统服务实例

        可用操作：
            - write_file / write_files: 写入文件
            - read_file / read_bytes: 读取文件
            - create_directories: 创建目录
            - delete_files / delete_directories: 删除文件/目录
            - move_files: 移动/重命名文件
            - set_permissions: 设置权限
            - search: 搜索文件
            - get_file_info: 获取文件信息

        示例：
            ```python
            # 写入文件
            await interpreter.files.write_file(
                "hello.py",
                "print('Hello')"
            )

            # 读取文件
            content = await interpreter.files.read_file("hello.py")

            # 批量写入
            from opensandbox.models.filesystem import WriteEntry
            await interpreter.files.write_files([
                WriteEntry(path="file1.txt", data="content1"),
                WriteEntry(path="file2.txt", data="content2")
            ])
            ```
        """
        return self._sandbox.files

    @property
    def commands(self):
        """
        获取命令执行服务

        此属性委托给底层沙箱的 commands 服务，提供 Shell 命令执行功能。

        返回：
            Commands: 命令执行服务实例

        可用操作：
            - run: 执行命令（支持流式输出）
            - interrupt: 中断正在运行的命令
            - get_command_status: 获取命令状态
            - get_background_command_logs: 获取命令日志

        示例：
            ```python
            # 执行命令
            result = await interpreter.commands.run("ls -la")
            print(result.logs.stdout)

            # 带选项执行
            from opensandbox.models.execd import RunCommandOpts
            result = await interpreter.commands.run(
                "python script.py",
                opts=RunCommandOpts(timeout=timedelta(minutes=5))
            )
            ```
        """
        return self._sandbox.commands

    @property
    def metrics(self):
        """
        获取指标监控服务

        此属性委托给底层沙箱的 metrics 服务，提供资源使用情况监控。

        返回：
            Metrics: 指标服务实例

        可用操作：
            - get_metrics: 获取资源使用指标

        示例：
            ```python
            # 获取资源使用情况
            metrics = await interpreter.metrics.get_metrics()
            print(f"CPU: {metrics.cpu_percent}%")
            print(f"Memory: {metrics.memory_used_in_mib}MB")
            ```
        """
        return self._sandbox.metrics

    @property
    def codes(self) -> Codes:
        """
        获取代码执行服务

        此属性提供高级代码执行功能，是 CodeInterpreter 的核心功能。

        返回：
            Codes: 代码执行服务实例

        可用操作：
            - create_context: 创建执行上下文
            - get_context: 获取现有上下文
            - list_contexts: 列出上下文
            - delete_context / delete_contexts: 删除上下文
            - run: 执行代码（支持上下文和流式输出）
            - interrupt: 中断代码执行

        支持的语言：
            - Python: 完整的 Python 3.x 支持
            - JavaScript/Node.js: ES6+ 支持
            - Bash: Shell 脚本
            - Java: 编译和执行
            - Kotlin: 脚本和编译执行

        示例：
            ```python
            from code_interpreter.models.code import SupportedLanguage

            # 创建执行上下文
            context = await interpreter.codes.create_context(
                SupportedLanguage.PYTHON
            )

            # 执行代码（变量持久化）
            result1 = await interpreter.codes.run(
                "x = 42",
                context=context
            )

            # 后续执行可以访问之前的变量
            result2 = await interpreter.codes.run(
                "print(x)",
                context=context
            )

            # 带流式处理执行
            async def on_stdout(line):
                print(line)

            result = await interpreter.codes.run(
                "print('Hello')",
                handlers=ExecutionHandlers(on_stdout=on_stdout)
            )
            ```
        """
        return self._code_service

    @classmethod
    async def create(cls, sandbox: Sandbox) -> "CodeInterpreter":
        """
        从现有沙箱实例创建代码解释器

        这是创建 CodeInterpreter 的推荐方式。此工厂方法负责：
        1. 验证沙箱实例
        2. 创建适配器工厂
        3. 获取代码执行端点
        4. 创建代码执行服务
        5. 返回初始化的 CodeInterpreter

        设计说明：
            CodeInterpreter 必须通过包装现有的 Sandbox 实例来创建。
            这种设计确保了职责的清晰分离：
            - Sandbox: 负责基础设施（容器、资源、网络）
            - CodeInterpreter: 在沙箱之上添加代码执行功能

        参数：
            sandbox (Sandbox): 现有的沙箱实例
                - 必须是已创建的 Sandbox 对象
                - 将作为代码解释器的底层基础设施

        返回：
            CodeInterpreter: 新创建的代码解释器实例
                - 包装了传入的沙箱
                - 配置了代码执行服务

        异常：
            InvalidArgumentException: 如果未提供沙箱实例
            SandboxException: 如果创建失败（如获取端点失败）
            SandboxInternalException: 如果内部服务初始化失败

        创建流程详解：
            1. 验证 sandbox 参数不为 None
            2. 创建 AdapterFactory（使用沙箱的连接配置）
            3. 获取 execd 服务端口（默认端口）
            4. 通过工厂创建代码执行服务
            5. 返回 CodeInterpreter 实例

        示例：
            ```python
            from opensandbox import Sandbox
            from code_interpreter import CodeInterpreter

            # 首先创建沙箱
            sandbox = await Sandbox.create(
                "python:3.11",
                resource={"cpu": "1", "memory": "2Gi"}
            )

            # 创建代码解释器
            interpreter = await CodeInterpreter.create(sandbox=sandbox)

            # 现在可以使用代码执行功能
            context = await interpreter.codes.create_context(
                SupportedLanguage.PYTHON
            )
            result = await interpreter.codes.run(
                "print('Hello')",
                context=context
            )
            ```

        最佳实践：
            ```python
            sandbox = await Sandbox.create("python:3.11")
            try:
                interpreter = await CodeInterpreter.create(sandbox=sandbox)

                # 使用解释器...
                await interpreter.codes.run("print('Hello')")

            finally:
                # 确保清理资源
                await sandbox.kill()
                await sandbox.close()
            ```
        """
        # 验证沙箱实例不为 None
        # 沙箱是必需的，没有沙箱无法创建代码解释器
        if sandbox is None:
            raise InvalidArgumentException("Sandbox instance must be provided")

        # 记录创建日志
        logger.info("Creating code interpreter from sandbox: %s", sandbox.id)

        # 创建适配器工厂
        # 工厂使用沙箱的连接配置来创建各种服务
        factory = AdapterFactory(sandbox.connection_config)

        try:
            # 导入默认 execd 端口常量
            # execd 是执行守护进程，提供代码执行服务
            from opensandbox.constants import DEFAULT_EXECD_PORT

            # 获取代码执行端点
            # 这是沙箱内 execd 服务的网络访问地址
            code_interpreter_endpoint = await sandbox.get_endpoint(DEFAULT_EXECD_PORT)

            # 通过工厂创建代码执行服务
            # Codes 服务负责实际的代码执行
            code_execution_service = factory.create_code_execution_service(
                code_interpreter_endpoint
            )

            # 记录成功日志
            logger.info("Code interpreter %s created successfully", sandbox.id)

            # 返回新创建的 CodeInterpreter 实例
            return cls(sandbox, code_execution_service)

        except Exception as e:
            # 异常处理
            # 如果是 SDK 标准异常，直接抛出
            if isinstance(e, SandboxException):
                raise

            # 否则包装为内部异常
            raise SandboxInternalException(
                f"Failed to create code interpreter: {e}", cause=e
            ) from e
