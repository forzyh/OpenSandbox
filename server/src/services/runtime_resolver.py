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
安全运行时配置解析器模块。

本模块用于将安全运行时配置转换为后端特定的参数：
- Docker：OCI 运行时名称（如 "runsc"、"kata-runtime"）
- Kubernetes：RuntimeClass 名称（如 "gvisor"、"kata-qemu"）

主要功能：
- SecureRuntimeResolver 类：将 AppConfig 转换为运行时参数
- validate_secure_runtime_on_startup 函数：在服务器启动时验证运行时可用性

安全运行时（Secure Runtime）是一种容器隔离技术，如 Google 的 gVisor
或 Intel 的 Kata Containers，它们提供比传统容器更强的安全隔离。
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Optional

from kubernetes.client.exceptions import ApiException

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from docker import DockerClient
    from src.config import AppConfig, SecureRuntimeConfig
    from src.services.k8s.client import K8sClient


class SecureRuntimeResolver:
    """
    安全容器运行时配置解析器。

    将服务器级别的安全运行时配置转换为后端特定的参数：
    - Docker：OCI 运行时名称（如 "runsc"、"kata-runtime"）
    - Kubernetes：RuntimeClass 名称（如 "gvisor"、"kata-qemu"）

    支持的运行时类型：
    - gvisor：Google 开发的容器沙箱，提供系统调用级别的隔离
    - kata：Intel 开发的轻量级虚拟机容器，提供硬件级别的隔离
    - firecracker：AWS 开发的基于 MicroVM 的隔离技术

    Attributes:
        secure_runtime: 安全运行时配置
        runtime_mode: 运行时模式（"docker" 或 "kubernetes"）
    """

    # 默认 Docker 运行时映射表
    # 将运行时类型映射到具体的 OCI 运行时名称
    DEFAULT_DOCKER_RUNTIMES = {
        "gvisor": "runsc",       # gVisor 使用 runsc 运行时
        "kata": "kata-runtime",  # Kata Containers 使用 kata-runtime
    }

    # 默认 Kubernetes RuntimeClass 映射表
    # 将运行时类型映射到具体的 RuntimeClass 名称
    DEFAULT_K8S_RUNTIME_CLASSES = {
        "gvisor": "gvisor",      # gVisor 的 RuntimeClass
        "kata": "kata-qemu",     # Kata Containers 使用 QEMU 后端
        "firecracker": "kata-fc", # Kata Containers 使用 Firecracker 后端
    }

    def __init__(self, config: AppConfig):
        """
        使用应用配置初始化解析器。

        Args:
            config: 应用配置，包含 secure_runtime 设置

        Examples:
            >>> resolver = SecureRuntimeResolver(app_config)
            >>> if resolver.is_enabled():
            ...     runtime = resolver.get_docker_runtime()
        """
        self.secure_runtime: Optional[SecureRuntimeConfig] = getattr(
            config, "secure_runtime", None
        )
        self.runtime_mode = config.runtime.type  # "docker" 或 "kubernetes"

    def is_enabled(self) -> bool:
        """
        检查是否配置并启用了安全运行时。

        Returns:
            bool: 如果配置了安全运行时且类型不为空则返回 True

        Examples:
            >>> resolver.is_enabled()
            True
        """
        return (
            self.secure_runtime is not None
            and self.secure_runtime.type != ""
        )

    def get_docker_runtime(self) -> Optional[str]:
        """
        获取安全容器的 Docker OCI 运行时名称。

        如果配置了 docker_runtime 则返回配置值，否则使用
        安全运行时类型的默认映射。

        Returns:
            str: OCI 运行时名称（如 "runsc"、"kata-runtime"）
            None: 如果未启用安全运行时

        Examples:
            >>> # 配置了 gvisor 类型，未指定 docker_runtime
            >>> resolver.get_docker_runtime()
            'runsc'
            >>> # 配置了显式的 docker_runtime
            >>> resolver.get_docker_runtime()
            'custom-runtime'
        """
        if not self.is_enabled():
            return None

        if self.secure_runtime is None:
            return None

        # 如果配置了显式的 docker_runtime，优先使用
        if self.secure_runtime.docker_runtime:
            return self.secure_runtime.docker_runtime

        # 否则使用默认映射
        runtime_type = self.secure_runtime.type
        return self.DEFAULT_DOCKER_RUNTIMES.get(runtime_type)

    def get_k8s_runtime_class(self) -> Optional[str]:
        """
        获取安全容器的 Kubernetes RuntimeClass 名称。

        如果配置了 k8s_runtime_class 则返回配置值，否则使用
        安全运行时类型的默认映射。

        Returns:
            str: RuntimeClass 名称（如 "gvisor"、"kata-qemu"）
            None: 如果未启用安全运行时

        Examples:
            >>> # 配置了 gvisor 类型，未指定 k8s_runtime_class
            >>> resolver.get_k8s_runtime_class()
            'gvisor'
            >>> # 配置了显式的 k8s_runtime_class
            >>> resolver.get_k8s_runtime_class()
            'custom-runtime-class'
        """
        if not self.is_enabled():
            return None

        if self.secure_runtime is None:
            return None

        # 如果配置了显式的 k8s_runtime_class，优先使用
        if self.secure_runtime.k8s_runtime_class:
            return self.secure_runtime.k8s_runtime_class

        # 否则使用默认映射
        runtime_type = self.secure_runtime.type
        return self.DEFAULT_K8S_RUNTIME_CLASSES.get(runtime_type)


async def validate_secure_runtime_on_startup(
    config: AppConfig,
    docker_client: Optional["DockerClient"] = None,
    k8s_client: Optional["K8sClient"] = None,
) -> None:
    """
    在启动时验证配置的安全运行时是否可用。

    本函数执行故障快速检测（fail-fast）验证，确保服务器
    以有效的安全运行时配置启动。验证内容：
    - Docker 运行时：验证运行时是否存在于 Docker 守护进程中
    - Kubernetes RuntimeClass：验证 RuntimeClass 是否存在于集群中

    Args:
        config: 应用配置
        docker_client: 用于运行时验证的 Docker 客户端（可选）
        k8s_client: 用于 RuntimeClass 验证的 K8s 客户端包装器（可选）

    Raises:
        ValueError: 如果配置的安全运行时不可用
        Exception: 其他验证错误

    Examples:
        >>> await validate_secure_runtime_on_startup(config, docker_client)
        # 如果运行时不可用，将抛出 ValueError
    """
    resolver = SecureRuntimeResolver(config)

    if not resolver.is_enabled():
        logger.info("未配置安全运行时。")
        return

    if config.runtime.type == "docker":
        await _validate_docker_runtime(resolver, docker_client)
    elif config.runtime.type == "kubernetes":
        await _validate_k8s_runtime_class(resolver, k8s_client, config)
    else:
        logger.warning(
            "跳过了未知运行时类型的安全运行时验证：%s",
            config.runtime.type,
        )


async def _validate_docker_runtime(
    resolver: SecureRuntimeResolver,
    docker_client: Optional["DockerClient"],
) -> None:
    """
    验证 Docker OCI 运行时是否存在。

    通过检查 Docker 守护进程的运行时列表来验证配置的运行时是否可用。

    Args:
        resolver: 安全运行时解析器
        docker_client: Docker 客户端

    Raises:
        ValueError: 如果配置的运行时不可用
    """
    runtime_name = resolver.get_docker_runtime()

    if not runtime_name:
        logger.info("未配置安全容器的 Docker 运行时。")
        return

    logger.info("验证 Docker OCI 运行时：%s", runtime_name)

    if docker_client is None:
        logger.warning(
            "Docker 客户端不可用；跳过运行时验证。"
            "运行时 '%s' 将被使用但不会被验证。",
            runtime_name,
        )
        return

    try:
        # 从 Docker 守护进程获取可用运行时列表
        # Docker 将运行时存储在守护进程配置中
        info = docker_client.info()
        runtimes = info.get("Runtimes", {})

        if runtime_name not in runtimes:
            available = ", ".join(runtimes.keys()) if runtimes else "无"
            raise ValueError(
                f"配置的 Docker 运行时 '{runtime_name}' 不可用。"
                f"可用的运行时：{available}。"
                f"请在启动服务器之前安装并配置该运行时。"
            )

        logger.info(
            "Docker OCI 运行时 '%s' 可用：%s",
            runtime_name,
            runtimes.get(runtime_name, {}),
        )
    except Exception as exc:
        logger.error("验证 Docker 运行时失败：%s", exc)
        raise


async def _validate_k8s_runtime_class(
    resolver: SecureRuntimeResolver,
    k8s_client: Optional["K8sClient"],
    config: AppConfig,
) -> None:
    """
    验证 Kubernetes RuntimeClass 是否存在。

    通过查询 Kubernetes API 来验证配置的 RuntimeClass 是否存在。

    Args:
        resolver: 安全运行时解析器
        k8s_client: K8s 客户端包装器
        config: 应用配置

    Raises:
        ValueError: 如果配置的 RuntimeClass 不存在
        ApiException: Kubernetes API 错误
    """
    runtime_class_name = resolver.get_k8s_runtime_class()

    if not runtime_class_name:
        logger.info("未配置安全容器的 Kubernetes RuntimeClass。")
        return

    logger.info("验证 Kubernetes RuntimeClass：%s", runtime_class_name)

    if k8s_client is None:
        logger.warning(
            "Kubernetes 客户端不可用；跳过 RuntimeClass 验证。"
            "RuntimeClass '%s' 将被使用但不会被验证。",
            runtime_class_name,
        )
        return

    try:
        loop = asyncio.get_event_loop()
        # 在线程池中运行同步 API 调用
        await loop.run_in_executor(None, k8s_client.read_runtime_class, runtime_class_name)
        logger.info("Kubernetes RuntimeClass '%s' 可用。", runtime_class_name)
    except ApiException as exc:
        if exc.status == 404:
            raise ValueError(
                f"配置的 Kubernetes RuntimeClass '{runtime_class_name}' 不存在。"
                f"请在启动服务器之前创建该 RuntimeClass。"
            ) from exc
        logger.error("验证 RuntimeClass 失败：%s", exc)
        raise
    except Exception as exc:
        logger.error("验证 RuntimeClass 失败：%s", exc)
        raise


__all__ = [
    "SecureRuntimeResolver",
    "validate_secure_runtime_on_startup",
]
