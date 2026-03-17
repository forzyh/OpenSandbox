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

"""
沙箱服务工厂模块。

本模块提供工厂函数，用于根据应用配置创建相应的沙箱服务实现实例。
工厂模式的好处：
1. 解耦：调用者不需要知道具体的实现类
2. 可扩展：添加新的实现时只需修改工厂函数
3. 配置驱动：服务类型由配置文件决定，无需修改代码

支持的服务类型：
- docker: 使用 Docker 容器作为沙箱运行时
- kubernetes: 使用 Kubernetes 工作负载作为沙箱运行时

未来可以添加的实现：
- containerd: 使用 containerd 作为运行时
- podman: 使用 Podman 作为运行时
- 其他容器运行时

使用示例：
    # 基本用法（从全局配置读取）
    service = create_sandbox_service()

    # 指定服务类型（覆盖配置）
    service = create_sandbox_service(service_type="docker")

    # 使用自定义配置
    config = load_config("/path/to/config.toml")
    service = create_sandbox_service(config=config)
"""

import logging
from typing import Optional

from src.config import AppConfig, get_config
from src.services.docker import DockerSandboxService
from src.services.k8s import KubernetesSandboxService
from src.services.sandbox_service import SandboxService

logger = logging.getLogger(__name__)


def create_sandbox_service(
    service_type: Optional[str] = None,
    config: Optional[AppConfig] = None,
) -> SandboxService:
    """
    根据配置创建沙箱服务实例。

    工厂函数根据配置或指定的服务类型返回相应的沙箱服务实现。
    支持的服务类型在 `implementations` 字典中定义。

    创建流程：
    1. 确定配置：使用提供的配置或全局配置
    2. 确定服务类型：使用指定的类型或配置中的类型
    3. 查找实现类：从注册表中查找对应的实现类
    4. 创建实例：实例化实现类并返回

    Args:
        service_type: 可选的服务实现类型覆盖，如 "docker" 或 "kubernetes"。
                      如果未提供，使用配置中的 runtime.type。
        config: 可选的应用配置。如果未提供，使用全局配置。

    Returns:
        SandboxService: 配置的沙箱服务实现实例

    Raises:
        ValueError: 如果配置的服务类型不受支持

    Examples:
        # 使用全局配置创建服务
        >>> service = create_sandbox_service()

        # 覆盖服务类型
        >>> service = create_sandbox_service(service_type="docker")

        # 使用自定义配置
        >>> config = load_config("/path/to/config.toml")
        >>> service = create_sandbox_service(config=config)
    """
    # 使用提供的配置或获取全局配置
    active_config = config or get_config()
    # 确定服务类型：参数覆盖 > 配置中的类型，转换为小写进行比较
    selected_type = (service_type or active_config.runtime.type).lower()

    logger.info("创建沙箱服务，类型：%s", selected_type)

    # 服务实现注册表
    # 键：服务类型名称（小写）
    # 值：对应的服务实现类
    # 添加新的实现时在此处注册
    implementations: dict[str, type[SandboxService]] = {
        "docker": DockerSandboxService,
        "kubernetes": KubernetesSandboxService,
        # 未来的实现可以添加在这里：
        # "containerd": ContainerdSandboxService,
        # "podman": PodmanSandboxService,
    }

    # 检查服务类型是否受支持
    if selected_type not in implementations:
        # 构建受支持类型的列表，用于错误消息
        supported_types = ", ".join(implementations.keys())
        raise ValueError(
            f"不支持的沙箱服务类型：{selected_type}。"
            f"受支持的类型：{supported_types}"
        )

    # 获取实现类并创建实例
    implementation_class = implementations[selected_type]
    return implementation_class(config=active_config)
