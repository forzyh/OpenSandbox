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
适配器工厂模块 - Adapter Factory

本模块提供了 AdapterFactory 类，用于创建和管理各种服务适配器实例。

设计目的：
    - 集中管理服务适配器的创建逻辑
    - 确保所有适配器共享相同的连接配置和传输层
    - 提供统一的服务创建接口，简化客户端代码

架构说明：
    本工厂遵循工厂模式（Factory Pattern）， encapsulates 了服务适配器的实例化逻辑。
    所有适配器都共享同一个 ConnectionConfig 中的 transport 实例，这样可以：
    - 确保连接池的一致性
    - 统一代理配置
    - 统一重试行为
    - 减少资源消耗

提供的服务类型：
    - Sandboxes：沙箱生命周期管理服务（创建、删除、暂停、恢复等）
    - Filesystem：文件系统服务（读写文件、目录操作等）
    - Commands：命令执行服务（执行 Shell 命令）
    - Health：健康检查服务（监控沙箱状态）
    - Metrics：指标收集服务（获取资源使用情况）

使用示例：
    ```python
    from opensandbox.config import ConnectionConfig
    from opensandbox.adapters.factory import AdapterFactory

    # 创建连接配置
    config = ConnectionConfig(
        api_key="your-api-key",
        domain="api.opensandbox.io"
    )

    # 创建适配器工厂
    factory = AdapterFactory(config)

    # 通过工厂创建各种服务
    sandbox_service = factory.create_sandbox_service()
    filesystem_service = factory.create_filesystem_service(endpoint)
    command_service = factory.create_command_service(endpoint)
    ```
"""

# 导入各种适配器类
# 适配器是服务接口的具体实现，负责与 API 进行通信
from opensandbox.adapters.command_adapter import CommandsAdapter
from opensandbox.adapters.filesystem_adapter import FilesystemAdapter
from opensandbox.adapters.health_adapter import HealthAdapter
from opensandbox.adapters.metrics_adapter import MetricsAdapter
from opensandbox.adapters.sandboxes_adapter import SandboxesAdapter

# 导入连接配置类，包含所有 HTTP 客户端共享的配置
from opensandbox.config import ConnectionConfig

# 导入沙箱端点模型，用于指定服务访问的目标地址
from opensandbox.models.sandboxes import SandboxEndpoint

# 导入服务接口定义（Protocol）
# 这些是抽象接口，适配器是它们的具体实现
from opensandbox.services.command import Commands
from opensandbox.services.filesystem import Filesystem
from opensandbox.services.health import Health
from opensandbox.services.metrics import Metrics
from opensandbox.services.sandbox import Sandboxes


class AdapterFactory:
    """
    适配器工厂类 - 负责创建各种服务适配器实例

    本类封装了服务适配器的实例化逻辑，确保所有服务都使用一致的连接配置。

    设计模式：工厂模式（Factory Pattern）
    - 将对象的创建逻辑集中到一个类中
    - 客户端代码无需关心具体的实现细节
    - 便于统一管理和修改

    连接共享机制：
        每个适配器都会创建自己的 httpx 客户端，但它们都共享同一个
        ConnectionConfig 中提供的 transport 实例。这样可以：
        - 复用 TCP 连接，减少握手开销
        - 统一连接池管理
        - 一致的代理和重试配置

    属性：
        connection_config (ConnectionConfig): 共享的连接配置，包含认证信息、超时设置、传输层等

    使用示例：
        ```python
        config = ConnectionConfig(...)
        factory = AdapterFactory(config)

        # 创建沙箱管理服务
        sandbox_service = factory.create_sandbox_service()

        # 创建文件系统服务（需要端点信息）
        filesystem_service = factory.create_filesystem_service(endpoint)

        # 创建命令执行服务
        command_service = factory.create_command_service(endpoint)
        ```
    """

    def __init__(self, connection_config: ConnectionConfig) -> None:
        """
        初始化适配器工厂

        构造函数保存连接配置，供后续创建服务适配器时使用。

        参数：
            connection_config (ConnectionConfig): 共享的连接配置对象
                - 包含 API 密钥、域名、超时设置等
                - 包含共享的 transport 实例，用于连接池管理
                - 包含自定义请求头等配置

        示例：
            ```python
            config = ConnectionConfig(
                api_key="your-api-key",
                domain="api.opensandbox.io",
                request_timeout=timedelta(seconds=30)
            )
            factory = AdapterFactory(config)
            ```
        """
        # 保存连接配置，供后续创建服务时使用
        self.connection_config = connection_config

    def create_sandbox_service(self) -> Sandboxes:
        """
        创建沙箱管理服务适配器

        此服务用于沙箱的生命周期管理，包括：
        - 创建新的沙箱实例
        - 获取沙箱信息和状态
        - 列出所有沙箱
        - 暂停/恢复沙箱
        - 续期沙箱
        - 终止沙箱

        返回：
            Sandboxes: 沙箱管理服务实例
                提供 create_sandbox、get_sandbox_info、kill_sandbox 等方法

        示例：
            ```python
            sandbox_service = factory.create_sandbox_service()

            # 创建沙箱
            response = await sandbox_service.create_sandbox(
                spec=SandboxImageSpec("python:3.11"),
                ...
            )

            # 获取沙箱信息
            info = await sandbox_service.get_sandbox_info(sandbox_id)

            # 终止沙箱
            await sandbox_service.kill_sandbox(sandbox_id)
            ```
        """
        # 创建并返回沙箱适配器实例
        # SandboxesAdapter 实现了 Sandboxes 接口，负责与沙箱管理 API 通信
        return SandboxesAdapter(self.connection_config)

    def create_filesystem_service(self, endpoint: SandboxEndpoint) -> Filesystem:
        """
        创建文件系统服务适配器

        此服务用于在沙箱内进行文件操作，包括：
        - 读取/写入文件内容
        - 创建/删除目录
        - 移动/重命名文件
        - 设置文件权限
        - 搜索文件
        - 获取文件信息

        参数：
            endpoint (SandboxEndpoint): 沙箱端点信息
                - 包含沙箱的网络访问地址
                - 包含访问该端点所需的请求头
                - 用于定位具体的沙箱实例进行文件操作

        返回：
            Filesystem: 文件系统服务实例
                提供 read_file、write_file、delete_files、search 等方法

        示例：
            ```python
            # 先获取沙箱端点
            endpoint = await sandbox.get_endpoint(port=DEFAULT_EXECD_PORT)

            # 创建文件系统服务
            fs_service = factory.create_filesystem_service(endpoint)

            # 写入文件
            await fs_service.write_file("hello.py", "print('Hello')")

            # 读取文件
            content = await fs_service.read_file("hello.py")
            ```
        """
        # 创建并返回文件系统适配器实例
        # FilesystemAdapter 实现了 Filesystem 接口，负责与文件系统 API 通信
        return FilesystemAdapter(self.connection_config, endpoint)

    def create_command_service(self, endpoint: SandboxEndpoint) -> Commands:
        """
        创建命令执行服务适配器

        此服务用于在沙箱内执行 Shell 命令，包括：
        - 运行命令（支持同步和流式输出）
        - 中断正在运行的命令
        - 获取命令执行状态
        - 获取命令执行日志

        参数：
            endpoint (SandboxEndpoint): 沙箱端点信息
                - 包含沙箱的网络访问地址
                - 用于定位具体的沙箱实例执行命令

        返回：
            Commands: 命令执行服务实例
                提供 run、interrupt、get_command_status、get_background_command_logs 等方法

        示例：
            ```python
            # 创建命令服务
            cmd_service = factory.create_command_service(endpoint)

            # 执行命令
            result = await cmd_service.run("ls -la")
            print(result.logs.stdout)

            # 中断命令
            await cmd_service.interrupt(execution_id)

            # 获取命令状态
            status = await cmd_service.get_command_status(execution_id)
            ```
        """
        # 创建并返回命令适配器实例
        # CommandsAdapter 实现了 Commands 接口，负责与命令执行 API 通信
        return CommandsAdapter(self.connection_config, endpoint)

    def create_health_service(self, endpoint: SandboxEndpoint) -> Health:
        """
        创建健康检查服务适配器

        此服务用于监控沙箱的健康状态，包括：
        - 检查沙箱是否存活
        - 检查沙箱是否就绪
        - 获取沙箱健康状态详情

        参数：
            endpoint (SandboxEndpoint): 沙箱端点信息
                - 包含沙箱的网络访问地址
                - 用于定位具体的沙箱实例进行健康检查

        返回：
            Health: 健康检查服务实例
                提供 check_health、is_alive 等方法

        示例：
            ```python
            # 创建健康检查服务
            health_service = factory.create_health_service(endpoint)

            # 检查沙箱是否存活
            is_alive = await health_service.is_alive()

            # 获取健康状态
            status = await health_service.check_health()
            ```
        """
        # 创建并返回健康检查适配器实例
        # HealthAdapter 实现了 Health 接口，负责与健康检查 API 通信
        return HealthAdapter(self.connection_config, endpoint)

    def create_metrics_service(self, endpoint: SandboxEndpoint) -> Metrics:
        """
        创建指标收集服务适配器

        此服务用于收集沙箱的资源使用指标，包括：
        - CPU 使用率
        - 内存使用量
        - 磁盘使用量
        - 网络流量统计

        参数：
            endpoint (SandboxEndpoint): 沙箱端点信息
                - 包含沙箱的网络访问地址
                - 用于定位具体的沙箱实例收集指标

        返回：
            Metrics: 指标收集服务实例
                提供 get_metrics 等方法

        示例：
            ```python
            # 创建指标服务
            metrics_service = factory.create_metrics_service(endpoint)

            # 获取资源使用指标
            metrics = await metrics_service.get_metrics()
            print(f"CPU: {metrics.cpu_percent}%")
            print(f"Memory: {metrics.memory_used_in_mib}MB")
            ```
        """
        # 创建并返回指标收集适配器实例
        # MetricsAdapter 实现了 Metrics 接口，负责与指标收集 API 通信
        return MetricsAdapter(self.connection_config, endpoint)
