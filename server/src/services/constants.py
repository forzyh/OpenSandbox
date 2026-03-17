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
Sandbox 服务的共享常量定义模块。

本模块定义了 OpenSandbox 系统中使用的各种常量，包括：
- 标签前缀和标签键常量：用于 Kubernetes 和 Docker 的资源标记
- 错误代码类：定义了 Docker、Kubernetes 和通用错误代码

这些常量在整个服务层中被广泛使用，确保了命名的一致性和可维护性。
"""

# 保留标签前缀，用于系统内部管理的标签
# 所有以该前缀开头的标签都由系统管理，用户不能通过 metadata 设置
RESERVED_LABEL_PREFIX = "opensandbox.io/"

# Sandbox ID 标签键，用于在容器/Pod 上标记 sandbox 的唯一标识符
SANDBOX_ID_LABEL = "opensandbox.io/id"

# Sandbox 过期时间标签键，用于标记 sandbox 的自动过期时间戳
SANDBOX_EXPIRES_AT_LABEL = "opensandbox.io/expires-at"

# 手动清理标记标签键，用于标记需要手动清理的 sandbox
SANDBOX_MANUAL_CLEANUP_LABEL = "opensandbox.io/manual-cleanup"

# 主机映射端口标签（桥接模式）
# 记录容器端口到主机端口的映射关系
# SANDBOX_EMBEDDING_PROXY_PORT_LABEL: 映射容器 44772 端口到主机端口
SANDBOX_EMBEDDING_PROXY_PORT_LABEL = "opensandbox.io/embedding-proxy-port"
# SANDBOX_HTTP_PORT_LABEL: 映射容器 8080 端口到主机端口
SANDBOX_HTTP_PORT_LABEL = "opensandbox.io/http-port"

# OSSFS 挂载信息标签键，用于记录 OSSFS 挂载配置
SANDBOX_OSSFS_MOUNTS_LABEL = "opensandbox.io/ossfs-mounts"

# Ingress 模式下的自定义请求头名称
# 用于在网关路由模式中传递目标 sandbox 信息
OPEN_SANDBOX_INGRESS_HEADER = "OpenSandbox-Ingress-To"


class SandboxErrorCodes:
    """
    Sandbox 服务的标准错误代码类。

    定义了系统中所有可能的错误代码，按类别分组：
    - Docker 运行时错误代码
    - Kubernetes 运行时错误代码
    - 通用错误代码
    - 卷/存储相关错误代码

    这些错误代码用于 API 响应中，帮助客户端识别和处理特定类型的错误。
    """

    # ==================== Docker 运行时错误代码 ====================
    # Docker 客户端初始化失败
    DOCKER_INITIALIZATION_ERROR = "DOCKER::INITIALIZATION_ERROR"
    # 容器查询失败
    CONTAINER_QUERY_FAILED = "DOCKER::SANDBOX_QUERY_FAILED"
    # Sandbox 未找到
    SANDBOX_NOT_FOUND = "DOCKER::SANDBOX_NOT_FOUND"
    # 镜像拉取失败
    IMAGE_PULL_FAILED = "DOCKER::SANDBOX_IMAGE_PULL_FAILED"
    # 容器启动失败
    CONTAINER_START_FAILED = "DOCKER::SANDBOX_START_FAILED"
    # Sandbox 删除失败
    SANDBOX_DELETE_FAILED = "DOCKER::SANDBOX_DELETE_FAILED"
    # Sandbox 未运行
    SANDBOX_NOT_RUNNING = "DOCKER::SANDBOX_NOT_RUNNING"
    # Sandbox 暂停失败
    SANDBOX_PAUSE_FAILED = "DOCKER::SANDBOX_PAUSE_FAILED"
    # Sandbox 未暂停
    SANDBOX_NOT_PAUSED = "DOCKER::SANDBOX_NOT_PAUSED"
    # Sandbox 恢复失败
    SANDBOX_RESUME_FAILED = "DOCKER::SANDBOX_RESUME_FAILED"
    # 过期时间无效
    INVALID_EXPIRATION = "DOCKER::INVALID_EXPIRATION"
    # 过期时间未延长
    EXPIRATION_NOT_EXTENDED = "DOCKER::EXPIRATION_NOT_EXTENDED"
    # execd 启动失败
    EXECD_START_FAILED = "DOCKER::SANDBOX_EXECD_START_FAILED"
    # execd 分发失败
    EXECD_DISTRIBUTION_FAILED = "DOCKER::SANDBOX_EXECD_DISTRIBUTION_FAILED"
    # bootstrap 安装失败
    BOOTSTRAP_INSTALL_FAILED = "DOCKER::SANDBOX_BOOTSTRAP_INSTALL_FAILED"
    # 入口点无效
    INVALID_ENTRYPOINT = "DOCKER::INVALID_ENTRYPOINT"
    # 端口无效
    INVALID_PORT = "DOCKER::INVALID_PORT"
    # 网络模式端点不可用
    NETWORK_MODE_ENDPOINT_UNAVAILABLE = "DOCKER::NETWORK_MODE_ENDPOINT_UNAVAILABLE"

    # ==================== Kubernetes 运行时错误代码 ====================
    # Kubernetes 客户端初始化失败
    K8S_INITIALIZATION_ERROR = "KUBERNETES::INITIALIZATION_ERROR"
    # Kubernetes Sandbox 未找到
    K8S_SANDBOX_NOT_FOUND = "KUBERNETES::SANDBOX_NOT_FOUND"
    # Pod 失败
    K8S_POD_FAILED = "KUBERNETES::POD_FAILED"
    # Pod 就绪超时
    K8S_POD_READY_TIMEOUT = "KUBERNETES::POD_READY_TIMEOUT"
    # Kubernetes API 错误
    K8S_API_ERROR = "KUBERNETES::API_ERROR"
    # Pod IP 不可用
    K8S_POD_IP_NOT_AVAILABLE = "KUBERNETES::POD_IP_NOT_AVAILABLE"

    # ==================== 通用错误代码 ====================
    # 未知错误
    UNKNOWN_ERROR = "SANDBOX::UNKNOWN_ERROR"
    # API 不支持
    API_NOT_SUPPORTED = "SANDBOX::API_NOT_SUPPORTED"
    # 元数据标签无效
    INVALID_METADATA_LABEL = "SANDBOX::INVALID_METADATA_LABEL"
    # 参数无效
    INVALID_PARAMETER = "SANDBOX::INVALID_PARAMETER"

    # ==================== 卷/存储相关错误代码 ====================
    # 卷名称无效
    INVALID_VOLUME_NAME = "VOLUME::INVALID_NAME"
    # 卷名称重复
    DUPLICATE_VOLUME_NAME = "VOLUME::DUPLICATE_NAME"
    # 卷后端无效
    INVALID_VOLUME_BACKEND = "VOLUME::INVALID_BACKEND"
    # 挂载路径无效
    INVALID_MOUNT_PATH = "VOLUME::INVALID_MOUNT_PATH"
    # 子路径无效
    INVALID_SUB_PATH = "VOLUME::INVALID_SUB_PATH"
    # 主机路径无效
    INVALID_HOST_PATH = "VOLUME::INVALID_HOST_PATH"
    # 主机路径不被允许
    HOST_PATH_NOT_ALLOWED = "VOLUME::HOST_PATH_NOT_ALLOWED"
    # PVC 名称无效
    INVALID_PVC_NAME = "VOLUME::INVALID_PVC_NAME"
    # 不支持的卷后端类型
    UNSUPPORTED_VOLUME_BACKEND = "VOLUME::UNSUPPORTED_BACKEND"
    # 主机路径未找到
    HOST_PATH_NOT_FOUND = "VOLUME::HOST_PATH_NOT_FOUND"
    # 主机路径创建失败
    HOST_PATH_CREATE_FAILED = "VOLUME::HOST_PATH_CREATE_FAILED"
    # PVC 卷未找到
    PVC_VOLUME_NOT_FOUND = "VOLUME::PVC_NOT_FOUND"
    # PVC 卷检查失败
    PVC_VOLUME_INSPECT_FAILED = "VOLUME::PVC_INSPECT_FAILED"
    # PVC 子路径不支持的驱动
    PVC_SUBPATH_UNSUPPORTED_DRIVER = "VOLUME::PVC_SUBPATH_UNSUPPORTED_DRIVER"
    # OSSFS 版本无效
    INVALID_OSSFS_VERSION = "VOLUME::INVALID_OSSFS_VERSION"
    # OSSFS 端点无效
    INVALID_OSSFS_ENDPOINT = "VOLUME::INVALID_OSSFS_ENDPOINT"
    # OSSFS Bucket 无效
    INVALID_OSSFS_BUCKET = "VOLUME::INVALID_OSSFS_BUCKET"
    # OSSFS 选项无效
    INVALID_OSSFS_OPTION = "VOLUME::INVALID_OSSFS_OPTION"
    # OSSFS 凭证无效
    INVALID_OSSFS_CREDENTIALS = "VOLUME::INVALID_OSSFS_CREDENTIALS"
    # OSSFS 挂载根路径无效
    INVALID_OSSFS_MOUNT_ROOT = "VOLUME::INVALID_OSSFS_MOUNT_ROOT"
    # OSSFS 路径未找到
    OSSFS_PATH_NOT_FOUND = "VOLUME::OSSFS_PATH_NOT_FOUND"
    # OSSFS 挂载失败
    OSSFS_MOUNT_FAILED = "VOLUME::OSSFS_MOUNT_FAILED"
    # OSSFS 卸载失败
    OSSFS_UNMOUNT_FAILED = "VOLUME::OSSFS_UNMOUNT_FAILED"


__all__ = [
    "RESERVED_LABEL_PREFIX",
    "SANDBOX_ID_LABEL",
    "SANDBOX_EXPIRES_AT_LABEL",
    "SANDBOX_MANUAL_CLEANUP_LABEL",
    "SANDBOX_EMBEDDING_PROXY_PORT_LABEL",
    "SANDBOX_HTTP_PORT_LABEL",
    "SANDBOX_OSSFS_MOUNTS_LABEL",
    "OPEN_SANDBOX_INGRESS_HEADER",
    "SandboxErrorCodes",
]
