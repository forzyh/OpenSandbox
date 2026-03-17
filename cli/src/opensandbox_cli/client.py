# Copyright 2026 Alibaba Group Holding Ltd.
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

"""SDK 客户端工厂模块。

本模块定义了 ClientContext 类，用于在 Click 命令之间共享 SDK 客户端实例和配置。
主要功能包括：
1. 管理连接配置（ConnectionConfigSync）
2. 提供沙盒管理器（SandboxManagerSync）的懒加载创建
3. 提供连接到现有沙盒的方法
4. 管理资源清理

使用场景：
- 所有 CLI 命令通过 Click 的 ctx.obj 共享此上下文
- 避免重复创建连接和客户端实例
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from opensandbox.config.connection_sync import ConnectionConfigSync
from opensandbox.sync.manager import SandboxManagerSync
from opensandbox.sync.sandbox import SandboxSync

from opensandbox_cli.output import OutputFormatter


@dataclass
class ClientContext:
    """CLI 命令共享的上下文对象。

    该类通过 Click 的 ctx.obj 机制在所有命令之间共享，提供：
    1. 解析后的配置信息
    2. 输出格式化工具
    3. 懒加载的连接配置
    4. 懒加载的沙盒管理器

    属性：
        resolved_config: 合并所有配置源后的最终配置字典
        output: 输出格式化工具实例
        _connection_config: 懒加载的连接配置（内部使用）
        _manager: 懒加载的沙盒管理器（内部使用）

    使用示例：
        @click.command()
        @click.pass_obj
        def my_command(obj: ClientContext):
            # 访问配置
            api_key = obj.resolved_config.get("api_key")

            # 获取管理器
            manager = obj.get_manager()

            # 连接沙盒
            sandbox = obj.connect_sandbox("sandbox-id")
    """

    resolved_config: dict[str, Any]
    output: OutputFormatter
    _connection_config: ConnectionConfigSync | None = field(
        default=None, init=False, repr=False
    )
    _manager: SandboxManagerSync | None = field(
        default=None, init=False, repr=False
    )

    @property
    def connection_config(self) -> ConnectionConfigSync:
        """获取连接配置，支持懒加载。

        首次访问时根据 resolved_config 创建 ConnectionConfigSync 实例，
        后续访问直接返回缓存的实例。

        返回：
            ConnectionConfigSync: SDK 连接配置对象

        配置项说明：
            - api_key: API 认证密钥
            - domain: API 服务器域名
            - protocol: 通信协议（http/https）
            - request_timeout: 请求超时时间
        """
        if self._connection_config is None:
            cfg = self.resolved_config
            self._connection_config = ConnectionConfigSync(
                api_key=cfg.get("api_key"),
                domain=cfg.get("domain"),
                protocol=cfg.get("protocol", "http"),
                request_timeout=timedelta(seconds=cfg.get("request_timeout", 30)),
            )
        return self._connection_config

    def get_manager(self) -> SandboxManagerSync:
        """获取沙盒管理器实例（懒加载）。

        首次调用时创建 SandboxManagerSync 实例，后续调用返回同一实例。
        管理器用于执行沙盒的生命周期管理操作（创建、删除、列表等）。

        返回：
            SandboxManagerSync: 沙盒管理器实例
        """
        if self._manager is None:
            self._manager = SandboxManagerSync.create(self.connection_config)
        return self._manager

    def connect_sandbox(
        self, sandbox_id: str, *, skip_health_check: bool = True
    ) -> SandboxSync:
        """连接到已存在的沙盒。

        通过沙盒 ID 建立连接，返回可用于操作该沙盒的 SandboxSync 实例。

        参数：
            sandbox_id: 要连接的沙盒 ID
            skip_health_check: 是否跳过健康检查，默认为 True

        返回：
            SandboxSync: 沙盒操作代理对象

        使用示例：
            sandbox = obj.connect_sandbox("sb-123")
            # 执行沙盒操作
            result = sandbox.commands.run("echo hello")
            sandbox.close()
        """
        return SandboxSync.connect(
            sandbox_id,
            connection_config=self.connection_config,
            skip_health_check=skip_health_check,
        )

    def close(self) -> None:
        """释放资源。

        清理所有持有的资源：
        1. 关闭沙盒管理器
        2. 关闭连接配置的传输层

        该方法在 CLI 退出时自动调用，确保资源正确释放。
        """
        if self._manager is not None:
            self._manager.close()
            self._manager = None
        if self._connection_config is not None:
            self._connection_config.close_transport_if_owned()
            self._connection_config = None
