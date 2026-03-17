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
代码执行服务接口模块 - Code Service

本模块定义了 Codes Protocol 接口，是代码执行服务的契约。

设计目的：
    - 定义代码执行服务的标准接口
    - 支持多语言代码解释（Python、JavaScript、Bash、Java、Kotlin）
    - 提供上下文管理、会话持久化能力
    - 支持实时执行和流式输出

核心概念：
    1. 执行上下文（CodeContext）
       - 维护变量、导入、工作目录的状态
       - 支持多次执行之间的状态持久化
       - 每个上下文有唯一的 ID

    2. 会话管理
       - 创建：create_context() 创建新的执行环境
       - 获取：get_context() 获取现有上下文
       - 列表：list_contexts() 列出所有活跃上下文
       - 删除：delete_context() 删除指定上下文

    3. 代码执行
       - 支持带上下文执行（变量持久化）
       - 支持无上下文执行（一次性执行）
       - 支持流式输出（实时获取 stdout/stderr）
       - 支持中断（停止长时间运行的代码）

支持的语言：
    - Python: 完整的 Python 3.x 支持，包含包管理
    - JavaScript/Node.js: ES6+ 语法，npm 包支持
    - Bash: Shell 脚本，完整的系统访问
    - Java: 编译和执行，classpath 管理
    - Kotlin: 脚本和编译执行

关键特性：
    - 执行上下文：隔离的环境，状态持久化
    - 变量持久化：变量和导入在执行间保持
    - 实时中断：安全停止长时间运行的代码
    - 输出流式：实时的 stdout/stderr 输出
    - 错误处理：语言特定的错误解析和报告

使用示例：
    ```python
    from code_interpreter.models.code import SupportedLanguage

    # 创建执行上下文
    context = await code_service.create_context(SupportedLanguage.PYTHON)

    # 执行代码（变量持久化）
    result1 = await code_service.run(
        "import numpy as np; x = 42",
        context=context,
    )

    # 后续执行可以访问之前的变量
    result2 = await code_service.run(
        "print(f'Value: {x}, NumPy version: {np.__version__}')",
        context=context,
    )
    # 变量 'x' 和 'np' 在执行间保持

    # 中断长时间运行的代码
    await code_service.interrupt(execution_id)

    # 删除上下文
    await code_service.delete_context(context.id)
    ```

架构说明：
    Codes 是一个 Protocol（结构子类型），定义了代码执行服务的接口。
    任何实现此 Protocol 的类都可以作为代码执行服务使用。

    实际实现：
        - CodeService: 标准的代码执行服务实现
        - 可以通过依赖注入替换为其他实现

    这种设计支持：
        - 接口与实现分离
        - 易于测试（可以注入 mock 实现）
        - 灵活扩展（可以添加新的实现）
"""

from typing import Protocol, overload

# 导入执行相关的模型
# Execution: 执行结果，包含输出、错误、退出码等
# ExecutionHandlers: 执行处理器，包含流式回调函数
from opensandbox.models.execd import Execution, ExecutionHandlers

# 导入代码上下文模型
from code_interpreter.models.code import CodeContext


class Codes(Protocol):
    """
    代码执行服务协议 - 多语言代码解释的服务接口

    此 Protocol 定义了代码执行服务的标准接口，提供：
    - 上下文管理：创建、获取、列出、删除执行上下文
    - 代码执行：在指定上下文中执行代码
    - 中断支持：停止正在运行的代码执行

    设计模式：
        - Protocol（结构子类型）：定义接口，不强制继承
        - 任何实现相同方法的类都自动成为 Codes 的子类型
        - 支持静态类型检查，同时保持灵活性

    支持的语言：
        - Python: 完整的 Python 3.x 支持，包含 pip 包管理
        - JavaScript/Node.js: ES6+ 语法，npm 包支持
        - Bash: Shell 脚本，完整的系统访问权限
        - Java: 源代码编译和执行，classpath 管理
        - Kotlin: 脚本模式和编译执行

    核心特性：

        1. 执行上下文（Execution Contexts）
           - 隔离的执行环境
           - 状态在多次执行间持久化
           - 每个上下文有唯一的 ID 和语言标识

        2. 变量持久化（Variable Persistence）
           - 变量在多次执行间保持
           - 导入的模块持久化
           - 工作目录持久化

        3. 实时中断（Real-time Interruption）
           - 安全停止长时间运行的代码
           - 保持解释器状态一致
           - 不损坏上下文

        4. 输出流式（Output Streaming）
           - 实时捕获 stdout/stderr
           - 正确的缓冲处理
           - 支持自定义处理器

        5. 错误处理（Error Handling）
           - 语言特定的错误解析
           - 详细的错误报告
           - 堆栈跟踪支持

    使用示例：
        ```python
        from code_interpreter.models.code import SupportedLanguage
        from opensandbox.models.execd import ExecutionHandlers

        # 创建执行上下文
        context = await code_service.create_context(SupportedLanguage.PYTHON)
        print(f"Context ID: {context.id}")

        # 执行代码（变量会持久化）
        result1 = await code_service.run(
            "import numpy as np",
            context=context,
        )
        result2 = await code_service.run(
            "x = 42",
            context=context,
        )

        # 后续执行可以访问之前的变量和导入
        result3 = await code_service.run(
            "print(f'Value: {x}, NumPy: {np.__version__}')",
            context=context,
        )
        # 输出：Value: 42, NumPy: 1.24.0

        # 带流式处理执行
        async def on_stdout(line: str):
            print(f"STDOUT: {line}")

        async def on_stderr(line: str):
            print(f"STDERR: {line}")

        result = await code_service.run(
            "print('Hello'); import sys; sys.stderr.write('Error')",
            context=context,
            handlers=ExecutionHandlers(
                on_stdout=on_stdout,
                on_stderr=on_stderr
            )
        )

        # 中断长时间运行的代码
        execution_id = result.id
        await code_service.interrupt(execution_id)

        # 列出所有上下文
        contexts = await code_service.list_contexts(SupportedLanguage.PYTHON)

        # 删除上下文
        await code_service.delete_context(context.id)
        ```

    实现说明：
        此 Protocol 定义了接口，实际实现由具体服务类提供。
        实现类需要：
        - 维护上下文状态
        - 与后端执行服务通信
        - 处理 SSE 流式响应
        - 管理错误和异常
    """

    async def create_context(self, language: str) -> CodeContext:
        """
        创建新的执行上下文

        执行上下文是代码执行的基本单元，维护以下状态：
        - 变量：已定义的变量及其值
        - 导入：已导入的模块
        - 工作目录：当前工作目录
        - 语言：执行环境的编程语言

        上下文优势：
            - 状态持久化：多次执行共享同一状态
            - 交互式编程：类似 Jupyter 的体验
            - 资源复用：避免重复导入和初始化

        参数：
            language (str): 编程语言
                - "python": Python 3.x
                - "javascript": JavaScript/Node.js
                - "bash": Bash Shell
                - "java": Java
                - "kotlin": Kotlin

        返回：
            CodeContext: 新创建的执行上下文
                - id: 上下文的唯一标识符
                - language: 上下文的语言
                - created_at: 创建时间

        异常：
            SandboxException: 如果语言不支持或创建失败

        使用示例：
            ```python
            # 创建 Python 上下文
            context = await code_service.create_context("python")
            print(f"Created context: {context.id}")

            # 创建 JavaScript 上下文
            js_context = await code_service.create_context("javascript")

            # 创建 Bash 上下文
            bash_context = await code_service.create_context("bash")
            ```

        上下文使用模式：
            ```python
            # 创建上下文
            context = await code_service.create_context("python")

            # 第一次执行：定义变量
            await code_service.run("x = 42", context=context)

            # 第二次执行：使用之前的变量
            result = await code_service.run("print(x)", context=context)
            # 输出：42

            # 第三次执行：导入模块
            await code_service.run("import numpy as np", context=context)

            # 第四次执行：使用导入的模块
            result = await code_service.run(
                "print(np.random.randint(100))",
                context=context
            )
            ```

        注意事项：
            - 每个上下文消耗一定的系统资源
            - 不需要的上下文应及时删除
            - 不同语言的上下文完全隔离
        """
        ...

    async def get_context(self, context_id: str) -> CodeContext:
        """
        获取现有的执行上下文

        通过上下文 ID 获取已存在的上下文信息。

        参数：
            context_id (str): 上下文的唯一标识符
                - 从 create_context() 的返回值获取
                - 或从 list_contexts() 的返回值获取

        返回：
            CodeContext: 现有的执行上下文
                - id: 上下文 ID
                - language: 上下文的语言
                - created_at: 创建时间

        异常：
            SandboxException: 如果上下文不存在

        使用示例：
            ```python
            # 创建上下文
            context = await code_service.create_context("python")
            context_id = context.id

            # 稍后获取同一上下文
            context = await code_service.get_context(context_id)
            print(f"Language: {context.language}")
            ```

        注意事项：
            - 如果上下文已被删除，此方法会抛出异常
            - 上下文有生命周期，超时后可能被自动清理
        """
        ...

    async def list_contexts(self, language: str) -> list[CodeContext]:
        """
        列出指定语言的所有活跃上下文

        获取当前存在的所有执行上下文，按语言过滤。

        参数：
            language (str): 执行运行时
                - "python": Python 上下文
                - "javascript": JavaScript 上下文
                - "bash": Bash 上下文
                - "java": Java 上下文
                - "kotlin": Kotlin 上下文

        返回：
            list[CodeContext]: 上下文列表
                - 每个元素是一个 CodeContext 对象
                - 按创建时间排序（可能）

        异常：
            SandboxException: 如果列出失败

        使用示例：
            ```python
            # 列出所有 Python 上下文
            contexts = await code_service.list_contexts("python")
            print(f"Found {len(contexts)} Python contexts")

            for ctx in contexts:
                print(f"  - {ctx.id} (created: {ctx.created_at})")

            # 列出所有 JavaScript 上下文
            js_contexts = await code_service.list_contexts("javascript")
            ```

        清理模式：
            ```python
            # 列出并删除所有上下文
            contexts = await code_service.list_contexts("python")
            for ctx in contexts:
                await code_service.delete_context(ctx.id)
            ```
        """
        ...

    async def delete_context(self, context_id: str) -> None:
        """
        删除指定的执行上下文

        彻底删除上下文及其所有状态（变量、导入等）。
        这是一个不可逆操作。

        参数：
            context_id (str): 要删除的上下文 ID
                - 从 create_context() 或 list_contexts() 获取

        异常：
            SandboxException: 如果删除失败

        使用示例：
            ```python
            # 创建上下文
            context = await code_service.create_context("python")

            # 使用上下文...
            await code_service.run("x = 42", context=context)

            # 删除上下文（清理资源）
            await code_service.delete_context(context.id)
            ```

        资源管理最佳实践：
            ```python
            context = await code_service.create_context("python")
            try:
                # 使用上下文执行代码
                await code_service.run("x = 42", context=context)
            finally:
                # 确保删除上下文
                await code_service.delete_context(context.id)
            ```

        注意事项：
            - 删除后无法恢复上下文状态
            - 删除正在使用的上下文可能导致错误
            - 建议在使用完毕后立即删除
        """
        ...

    async def delete_contexts(self, language: str) -> None:
        """
        删除指定语言的所有执行上下文

        批量删除指定语言下的所有活跃上下文。
        这是一个不可逆操作。

        参数：
            language (str): 执行运行时
                - "python": 删除所有 Python 上下文
                - "javascript": 删除所有 JavaScript 上下文
                - "bash": 删除所有 Bash 上下文
                - "java": 删除所有 Java 上下文
                - "kotlin": 删除所有 Kotlin 上下文

        异常：
            SandboxException: 如果删除失败

        使用示例：
            ```python
            # 删除所有 Python 上下文
            await code_service.delete_contexts("python")

            # 删除所有 JavaScript 上下文
            await code_service.delete_contexts("javascript")

            # 清理所有上下文
            for lang in ["python", "javascript", "bash", "java", "kotlin"]:
                await code_service.delete_contexts(lang)
            ```

        清理场景：
            - 测试完成后清理所有测试上下文
            - 会话结束时清理资源
            - 达到上下文数量限制时清理旧上下文

        注意事项：
            - 此操作影响所有该语言的上下文
            - 删除后无法恢复任何上下文状态
            - 确保没有其他进程正在使用这些上下文
        """
        ...

    @overload
    async def run(
        self,
        code: str,
        *,
        context: CodeContext,
        handlers: ExecutionHandlers | None = None,
    ) -> Execution: ...

    @overload
    async def run(
        self,
        code: str,
        *,
        language: str,
        handlers: ExecutionHandlers | None = None,
    ) -> Execution: ...

    async def run(
        self,
        code: str,
        *,
        language: str | None = None,
        context: CodeContext | None = None,
        handlers: ExecutionHandlers | None = None,
    ) -> Execution:
        """
        执行代码

        这是代码执行的核心方法，在指定的上下文中运行代码字符串。

        执行模式：
            1. 带上下文执行（推荐）
               - 变量和导入在多次执行间持久化
               - 适合交互式编程场景
               - 需要预先创建 CodeContext

            2. 无上下文执行（一次性）
               - 每次执行都是独立的环境
               - 适合一次性脚本执行
               - 使用语言参数指定默认上下文

        参数：
            code (str): 要执行的源代码
                - 有效的目标语言代码
                - 例如："print('Hello')"（Python）
                - 例如："console.log('Hello')"（JavaScript）

            language (str | None): 语言选择器（可选）
                - 当 context 为 None 时使用
                - 指定使用哪种语言的默认上下文
                - execd 会在 omit context.id 时创建/复用默认会话
                - 如果同时提供 language 和 context，它们必须匹配

            context (CodeContext | None): 执行上下文（可选）
                - 如果提供，代码在此上下文中执行
                - 变量和导入会持久化
                - 如果为 None，使用默认 Python 上下文

            handlers (ExecutionHandlers | None): 流式处理器（可选）
                - on_stdout: 标准输出回调
                - on_stderr: 标准错误回调
                - on_event: 通用事件回调
                - 如果为 None，不启用流式处理

        返回：
            Execution: 执行结果
                - id: 执行 ID
                - execution_count: 执行计数
                - result: 执行结果列表
                - error: 错误信息（如果有）
                - logs.stdout: 标准输出列表
                - logs.stderr: 标准错误列表
                - exit_code: 退出码

        异常：
            SandboxException: 如果执行失败或超时

        执行行为说明：
            - 异步：非阻塞执行，正确的 async/await 处理
            - 有状态：变量和导入在上下文中持久化
            - 流式：输出在产生时实时捕获
            - 可中断：可以使用 interrupt() 方法停止

        使用示例：
            ```python
            # 模式 1：带上下文执行（变量持久化）
            context = await code_service.create_context("python")

            # 第一次执行：定义变量
            await code_service.run("x = 42", context=context)

            # 第二次执行：使用之前的变量
            result = await code_service.run("print(x)", context=context)
            # 输出：42

            # 模式 2：无上下文执行（使用默认上下文）
            result = await code_service.run(
                "print('Hello')",
                language="python"
            )

            # 模式 3：带流式处理
            async def on_stdout(line: str):
                print(f"STDOUT: {line}")

            async def on_stderr(line: str):
                print(f"STDERR: {line}")

            result = await code_service.run(
                "print('Hello'); import sys; sys.stderr.write('Error')",
                context=context,
                handlers=ExecutionHandlers(
                    on_stdout=on_stdout,
                    on_stderr=on_stderr
                )
            )
            ```

        多语言示例：
            ```python
            # Python
            result = await code_service.run(
                "import numpy as np; print(np.__version__)",
                language="python"
            )

            # JavaScript
            result = await code_service.run(
                "console.log('Hello from Node.js')",
                language="javascript"
            )

            # Bash
            result = await code_service.run(
                "echo 'Hello from Bash'",
                language="bash"
            )
            ```

        错误处理：
            ```python
            try:
                result = await code_service.run(
                    "1 / 0",  # 除零错误
                    context=context
                )
            except SandboxException as e:
                print(f"Execution failed: {e}")

            # 检查执行结果中的错误
            if result.error:
                print(f"Execution error: {result.error}")
            ```

        注意事项：
            - 代码执行有超时限制（默认 30 秒）
            - 长时间运行的代码应使用 interrupt() 中断
            - 敏感操作（如网络访问）可能受沙箱限制
        """
        ...

    async def interrupt(self, execution_id: str) -> None:
        """
        中断正在运行的代码执行

        安全地终止一个正在执行的代码，清理相关资源。

        中断机制：
            - 安全：保持解释器状态，不损坏上下文
            - 协作式：尊重语言特定的中断机制
                - Python: 发送 KeyboardInterrupt
                - JavaScript: 使用 vm 的中断能力
                - Bash: 发送 SIGINT 信号
            - 超时：如果需要，在合理超时后强制终止

        参数：
            execution_id (str): 要中断的执行 ID
                - 从 run() 方法的返回结果获取
                - 例如：execution.id

        异常：
            SandboxException: 如果中断失败

        使用示例：
            ```python
            import asyncio

            # 启动长时间运行的代码
            result = await code_service.run(
                "import time; time.sleep(60)",
                context=context
            )
            execution_id = result.id

            # 在另一个任务中中断
            await asyncio.sleep(1)  # 等待 1 秒
            await code_service.interrupt(execution_id)
            print("Execution interrupted")
            ```

        中断模式：
            ```python
            # 带超时的中断
            import asyncio

            async def run_with_timeout(code, context, timeout):
                result = await code_service.run(code, context=context)
                execution_id = result.id

                # 设置超时中断
                async def interrupt_if_needed():
                    await asyncio.sleep(timeout)
                    await code_service.interrupt(execution_id)

                asyncio.create_task(interrupt_if_needed())
                return result
            ```

        注意事项：
            - 中断是异步的，可能需要一些时间完成
            - 某些操作可能无法中断（如系统调用）
            - 中断后应检查执行状态确认是否成功
            - 中断不会删除上下文，可以继续使用
        """
        ...
