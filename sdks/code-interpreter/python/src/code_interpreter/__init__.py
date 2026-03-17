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
OpenSandbox Code Interpreter SDK - 代码解释器开发工具包

本模块提供了 OpenSandbox 代码解释器的 Python SDK，构建在基础沙箱设施之上，
提供高级代码执行功能。

功能概述：
    - 多语言代码执行：支持 Python、JavaScript、Bash、Java、Kotlin 等语言
    - 会话管理：持久化的执行上下文，变量状态跨执行保持
    - 变量检查：访问执行变量和状态
    - 流式执行：实时代码执行与输出流式传输
    - 沙箱集成：完全访问底层沙箱的文件系统和命令执行功能

核心类：
    - CodeInterpreter：代码解释器主类，提供代码执行功能
    - CodeInterpreterSync：同步版本的代码解释器
    - CodeContext：执行上下文，包含语言和可选的会话 ID
    - SupportedLanguage：支持的语言枚举

与基础沙箱的关系：
    CodeInterpreter 是在基础 Sandbox 之上的封装，提供：
    - 代码执行专业化：针对代码执行场景优化
    - 会话持久化：变量和导入在多次执行间保持
    - 多语言支持：统一的 API 支持多种编程语言

基本使用流程：
    1. 首先创建基础 Sandbox 实例
    2. 使用 CodeInterpreter.create() 包装 Sandbox
    3. 通过 interpreter.codes 执行代码
    4. 通过 interpreter.sandbox.files 等进行文件操作
    5. 使用 sandbox.kill() 和 sandbox.close() 清理资源

使用示例：
    ```python
    import asyncio
    from opensandbox import Sandbox
    from code_interpreter import CodeInterpreter, SupportedLanguage

    async def main():
        # 首先创建沙箱
        sandbox = await Sandbox.create("python:3.11")

        # 创建代码解释器（包装沙箱）
        interpreter = await CodeInterpreter.create(sandbox=sandbox)

        # 创建执行上下文
        context = await interpreter.codes.create_context(SupportedLanguage.PYTHON)

        # 执行代码（变量会持久化）
        result1 = await interpreter.codes.run(
            "x = 42; import numpy as np",
            context=context
        )

        # 后续执行可以访问之前的变量
        result2 = await interpreter.codes.run(
            "print(f'Value: {x}, NumPy: {np.__version__}')",
            context=context
        )

        # 访问底层沙箱进行文件操作
        await interpreter.sandbox.files.write_file(
            "data.txt",
            "Hello World"
        )

        # 清理资源
        await sandbox.kill()
        await sandbox.close()

    if __name__ == "__main__":
        asyncio.run(main())
    ```
"""

# 从标准库导入版本信息获取工具
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

# 导入代码解释器主类
# CodeInterpreter 是异步版本的代码解释器，提供完整的代码执行功能
from code_interpreter.code_interpreter import CodeInterpreter

# 导入代码执行相关的模型
from code_interpreter.models.code import (
    CodeContext,          # 执行上下文，包含语言和会话 ID
    SupportedLanguage,    # 支持的语言枚举
)

# 导入同步版本的代码解释器
# CodeInterpreterSync 提供阻塞式的 API，适合非异步场景
from code_interpreter.sync.code_interpreter import CodeInterpreterSync

# 定义模块的公共导出接口
# 使用 __all__ 控制使用 "from code_interpreter import *" 时导入的内容
__all__ = [
    "CodeInterpreter",      # 异步代码解释器（最常用）
    "CodeInterpreterSync",  # 同步代码解释器
    "CodeContext",          # 执行上下文
    "SupportedLanguage",    # 支持的语言
]

# 获取包版本信息
# 如果包未安装（如开发环境），则使用默认版本号 "0.0.0"
try:
    __version__ = _pkg_version("opensandbox-code-interpreter")
except PackageNotFoundError:  # pragma: no cover
    # 用于可编辑安装或未安装源码签出时的回退方案
    __version__ = "0.0.0"
