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
OpenSandbox Python SDK - Python 沙箱开发工具包

本模块是 OpenSandbox 的 Python SDK 主入口，提供了安全、隔离的代码执行环境。

功能概述：
    - 沙箱生命周期管理：创建、启动、暂停、恢复、终止沙箱实例
    - 文件系统操作：读写文件、创建目录、删除文件/目录、权限管理
    - 命令执行：在沙箱内执行 Shell 命令，支持流式输出
    - 资源监控：获取沙箱的 CPU、内存等资源使用情况
    - 健康检查：监控沙箱的运行状态

核心类：
    - Sandbox：异步沙箱类，用于创建和管理单个沙箱实例
    - SandboxManager：异步沙箱管理器，用于管理多个沙箱实例
    - SandboxSync：同步沙箱类，提供阻塞式的沙箱操作接口
    - SandboxManagerSync：同步沙箱管理器

基本使用流程：
    1. 使用 Sandbox.create() 创建沙箱实例
    2. 通过 sandbox.files 进行文件操作
    3. 通过 sandbox.commands 执行命令
    4. 通过 sandbox.metrics 获取资源使用信息
    5. 使用 sandbox.kill() 终止沙箱
    6. 使用 sandbox.close() 关闭连接

注意：沙箱资源的生命周期管理
    - 使用上下文管理器（async with）会在退出时自动调用 close() 关闭连接
    - 但必须显式调用 kill() 来终止远程沙箱实例，否则沙箱会继续运行直到超时

## Basic Usage (基本使用示例)

```python
import asyncio
from opensandbox import Sandbox
from opensandbox.models.execd import RunCommandOpts
from opensandbox.models.sandboxes import SandboxImageSpec

async def main():
    # 创建沙箱实例
    #
    # 生命周期说明：
    # - 退出上下文管理器时会调用 sandbox.close()（仅适用于本地 HTTP 资源）
    # - 必须显式调用 sandbox.kill() 来终止远程沙箱实例
    async with await Sandbox.create("python:3.11") as sandbox:
        # 写入文件
        await sandbox.files.write_file("hello.py", "print('Hello World')")

        # 执行命令
        result = await sandbox.commands.run("python hello.py")
        print(result.logs.stdout[0].text)  # 输出：Hello World

if __name__ == "__main__":
    asyncio.run(main())
```

## Advanced Usage (高级使用示例)

```python
from datetime import timedelta
from opensandbox import Sandbox
from opensandbox.config import ConnectionConfig
from opensandbox.models.execd import RunCommandOpts
from opensandbox.models.sandboxes import SandboxImageSpec, SandboxImageAuth

async def main():
    # 配置连接参数
    config = ConnectionConfig(
        api_key="your-api-key",        # API 密钥，用于身份验证
        domain="api.opensandbox.io"    # API 域名
    )

    # 使用私有镜像仓库的认证信息
    image_spec = SandboxImageSpec(
        "my-registry.com/python:3.11",  # 私有镜像地址
        auth=SandboxImageAuth(username="user", password="secret")  # 镜像认证
    )

    # 创建沙箱，指定超时时间、环境变量等
    sandbox = await Sandbox.create(
        image_spec,
        timeout=timedelta(minutes=30),      # 沙箱存活 30 分钟
        env={"PYTHONPATH": "/workspace"},   # 设置环境变量
        connection_config=config,           # 使用自定义连接配置
    )

    try:
        # 文件操作
        await sandbox.files.write_file("script.py", "print('Hello OpenSandbox!')")

        # 命令执行
        result = await sandbox.commands.run("python script.py")
        print(result.logs.stdout[0].text)

        # 获取资源使用指标
        metrics = await sandbox.get_metrics()
        print(f"Memory usage: {metrics.memory_used_in_mib}MB")

    finally:
        # 确保清理资源
        await sandbox.kill()    # 终止沙箱
        await sandbox.close()   # 关闭连接

if __name__ == "__main__":
    asyncio.run(main())
```

对于需要持久化上下文的高级代码执行功能（如变量持久化、多语言支持等），
请使用独立的 `opensandbox-code-interpreter` 包。
"""

# 从标准库导入版本信息获取工具
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

# 导入核心沙箱管理类
# SandboxManager：异步沙箱管理器，用于创建和管理多个沙箱
from opensandbox.manager import SandboxManager
# Sandbox：异步沙箱类，核心类，用于创建和管理单个沙箱实例
from opensandbox.sandbox import Sandbox
# 同步版本的沙箱类和管理器，提供阻塞式 API
from opensandbox.sync import SandboxManagerSync, SandboxSync

# 获取包版本信息
# 如果包未安装（如开发环境），则使用默认版本号 "0.0.0"
try:
    __version__ = _pkg_version("opensandbox")
except PackageNotFoundError:  # pragma: no cover
    # 用于可编辑安装或未安装源码签出时的回退方案
    __version__ = "0.0.0"

# 定义模块的公共导出接口
# 使用 __all__ 可以控制使用 "from opensandbox import *" 时导入的内容
__all__ = [
    "Sandbox",              # 异步沙箱类（最常用）
    "SandboxManager",       # 异步沙箱管理器
    "SandboxSync",          # 同步沙箱类
    "SandboxManagerSync",   # 同步沙箱管理器
]
