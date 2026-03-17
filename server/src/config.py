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
OpenSandbox 服务器应用配置管理模块。

本模块负责从 TOML 配置文件中加载和管理应用程序的所有配置项。
默认配置文件路径为 ~/.sandbox.toml，但可以通过环境变量 SANDBOX_CONFIG_PATH 覆盖。

配置加载流程：
1. 从指定的配置文件路径读取 TOML 格式的配置数据
2. 使用 Pydantic 进行数据验证和类型转换
3. 将验证后的配置存储为全局变量供其他模块使用

配置结构采用分层设计：
- server: FastAPI 服务器配置（端口、日志级别、API 密钥等）
- runtime: 沙箱运行时配置（Docker 或 Kubernetes）
- docker: Docker 特定配置（网络模式、安全设置等）
- kubernetes: Kubernetes 特定配置（命名空间、服务账户等）
- ingress: 入口配置（直接暴露或通过网关）
- storage: 存储配置（主机路径允许列表、OSSFS 挂载根目录等）
- secure_runtime: 安全运行时配置（gVisor、Kata、Firecracker）

配置验证：
- 使用 Pydantic 的 model_validator 进行跨字段验证
- 确保配置项之间的兼容性（如 Docker 运行时不能配置 Kubernetes 特定选项）
- 验证网络配置的有效性（IP 地址、域名格式等）
"""

from __future__ import annotations

import ipaddress
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, Field, ValidationError, model_validator

try:  # Python 3.11+
    import tomllib  # type: ignore[attr-defined]
except ModuleNotFoundError:  # Python 3.10 fallback
    import tomli as tomllib  # type: ignore[import]

logger = logging.getLogger(__name__)

CONFIG_ENV_VAR = "SANDBOX_CONFIG_PATH"
DEFAULT_CONFIG_PATH = Path.home() / ".sandbox.toml"

_DOMAIN_RE = re.compile(r"^(?=.{1,253}$)(?!-)[A-Za-z0-9-]{1,63}(?:\.[A-Za-z0-9-]{1,63})+$")
_WILDCARD_DOMAIN_RE = re.compile(r"^\*\.(?!-)[A-Za-z0-9-]{1,63}(?:\.[A-Za-z0-9-]{1,63})+$")
_IPV4_WITH_PORT_RE = re.compile(r"^(?P<ip>(?:\d{1,3}\.){3}\d{1,3})(?::(?P<port>\d{1,5}))?$")

INGRESS_MODE_DIRECT = "direct"
INGRESS_MODE_GATEWAY = "gateway"
GATEWAY_ROUTE_MODE_WILDCARD = "wildcard"
GATEWAY_ROUTE_MODE_HEADER = "header"
GATEWAY_ROUTE_MODE_URI = "uri"


def _is_valid_ip(host: str) -> bool:
    """
    验证给定的字符串是否是有效的 IP 地址。

    Args:
        host: 要验证的主机字符串

    Returns:
        bool: 如果是有效的 IPv4 或 IPv6 地址返回 True，否则返回 False
    """
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def _is_valid_ip_or_ip_port(address: str) -> bool:
    """
    验证给定的字符串是否是有效的 IP 地址或 IP:端口格式。

    Args:
        address: 要验证的地址字符串，可以是 "192.168.1.1" 或 "192.168.1.1:8080" 格式

    Returns:
        bool: 如果是有效的 IP 或 IP:端口格式返回 True，否则返回 False
    """
    match = _IPV4_WITH_PORT_RE.match(address)
    if not match:
        return False
    ip_str = match.group("ip")
    if not _is_valid_ip(ip_str):
        return False
    port_str = match.group("port")
    if port_str is None:
        return True
    try:
        port = int(port_str)
    except ValueError:
        return False
    return 1 <= port <= 65535


def _is_valid_domain(host: str) -> bool:
    """
    验证给定的字符串是否是有效的域名。

    Args:
        host: 要验证的域名字符串

    Returns:
        bool: 如果是有效的域名格式返回 True，否则返回 False
    """
    return bool(_DOMAIN_RE.match(host))


def _is_wildcard_domain(host: str) -> bool:
    """
    验证给定的字符串是否是有效的通配符域名（以 *. 开头）。

    Args:
        host: 要验证的通配符域名字符串

    Returns:
        bool: 如果是有效的通配符域名格式返回 True，否则返回 False
    """
    return bool(_WILDCARD_DOMAIN_RE.match(host))


class GatewayRouteModeConfig(BaseModel):
    """
    网关路由模式配置。

    定义网关如何处理传入的请求路由。支持三种模式：
    - wildcard: 通配符域名路由（如 *.example.com）
    - header: 基于请求头的路由
    - uri: 基于 URI 路径的路由
    """

    mode: Literal[
        GATEWAY_ROUTE_MODE_WILDCARD,
        GATEWAY_ROUTE_MODE_HEADER,
        GATEWAY_ROUTE_MODE_URI,
    ] = Field(
        ...,
        description="Routing mode used by the gateway (wildcard, header, uri).",
    )

    class Config:
        populate_by_name = True


class GatewayConfig(BaseModel):
    """
    网关模式配置，用于入口暴露。

    当沙箱需要通过网关暴露时使用此配置。网关地址可以是域名或 IP 地址，
    可以包含端口号（但不包含协议前缀，由客户端决定使用 http 或 https）。

    Attributes:
        address: 网关主机地址，用于暴露沙箱（域名或 IP，可以包含 :端口，不允许包含协议前缀）
        route: 网关使用的路由模式配置
    """

    address: str = Field(
        ...,
        description="网关主机地址，用于暴露沙箱（域名或 IP，可以包含 :端口，不允许包含协议前缀）",
        min_length=1,
    )
    route: GatewayRouteModeConfig = Field(
        ...,
        description="网关使用的路由模式配置",
    )


class IngressConfig(BaseModel):
    """
    沙箱入口暴露配置。

    定义沙箱如何对外暴露服务。支持两种模式：
    - direct: 直接模式，沙箱直接使用主机网络或通过端口映射暴露
    - gateway: 网关模式，沙箱通过统一的网关入口暴露，网关根据路由规则转发请求

    验证规则：
    - gateway 模式下必须提供 gateway 配置
    - direct 模式下不能提供 gateway 配置
    - gateway 模式下，如果使用 wildcard 路由模式，address 必须是通配符域名
    - gateway 模式下，如果使用非 wildcard 路由模式，address 不能包含通配符
    """

    mode: Literal[INGRESS_MODE_DIRECT, INGRESS_MODE_GATEWAY] = Field(
        default=INGRESS_MODE_DIRECT,
        description="Ingress exposure mode (direct or gateway).",
    )
    gateway: Optional[GatewayConfig] = Field(
        default=None,
        description="Gateway configuration required when mode = 'gateway'.",
    )

    @model_validator(mode="after")
    def validate_ingress_mode(self) -> "IngressConfig":
        if self.mode == INGRESS_MODE_GATEWAY and self.gateway is None:
            raise ValueError("gateway block must be provided when ingress.mode = 'gateway'.")
        if self.mode == INGRESS_MODE_DIRECT and self.gateway is not None:
            raise ValueError("gateway block must be omitted unless ingress.mode = 'gateway'.")

        if self.mode == INGRESS_MODE_GATEWAY and self.gateway:
            route_mode = self.gateway.route.mode
            address_raw = self.gateway.address
            hostport = address_raw
            if "://" in address_raw:
                raise ValueError("ingress.gateway.address must not include a scheme; clients choose http/https.")

            if route_mode == GATEWAY_ROUTE_MODE_WILDCARD:
                if not _is_wildcard_domain(hostport):
                    raise ValueError(
                        "ingress.gateway.address must be a wildcard domain (e.g., *.example.com) "
                        "when gateway.route.mode is wildcard."
                    )
            else:
                if "*" in hostport:
                    raise ValueError(
                        "ingress.gateway.address must not contain wildcard when gateway.route.mode is not wildcard."
                    )
                if not (_is_valid_domain(hostport) or _is_valid_ip_or_ip_port(hostport)):
                    raise ValueError(
                        "ingress.gateway.address must be a valid domain, IP, or IP:port when gateway.route.mode is not wildcard."
                    )
        return self


class ServerConfig(BaseModel):
    """
    FastAPI 服务器配置。

    定义生命周期 API 服务器的基本运行参数。

    Attributes:
        host: 生命周期 API 服务器绑定的网络接口地址，默认为 "0.0.0.0"（监听所有接口）
        port: 生命周期 API 服务器暴露的端口号，范围 1-65535，默认 8080
        log_level: 服务器进程的 Python 日志级别，如 "DEBUG"、"INFO"、"WARNING"、"ERROR"
        api_key: 用于认证传入生命周期 API 调用的全局 API 密钥，可选
        eip: 绑定的公共 IP 地址，设置后用于返回沙箱端点时作为主机部分
        max_sandbox_timeout_seconds: 请求指定超时时间时允许的最大沙箱 TTL（秒），
                                    如果不设置则禁用服务器端上限
    """

    host: str = Field(
        default="0.0.0.0",
        description="生命周期 API 服务器绑定的网络接口地址",
        min_length=1,
    )
    port: int = Field(
        default=8080,
        ge=1,
        le=65535,
        description="生命周期 API 服务器暴露的端口号",
    )
    log_level: str = Field(
        default="INFO",
        description="服务器进程的 Python 日志级别",
        min_length=3,
    )
    api_key: Optional[str] = Field(
        default=None,
        description="用于认证传入生命周期 API 调用的全局 API 密钥",
    )
    eip: Optional[str] = Field(
        default=None,
        description="绑定的公共 IP 地址，设置后用于返回沙箱端点时作为主机部分",
    )
    max_sandbox_timeout_seconds: Optional[int] = Field(
        default=None,
        ge=60,
        description=(
            "请求指定超时时间时允许的最大沙箱 TTL（秒）。"
            "如果不配置此项，则禁用服务器端上限。"
        ),
    )


class KubernetesRuntimeConfig(BaseModel):
    """
    Kubernetes 特定的运行时配置。

    定义在 Kubernetes 环境中运行沙箱时的各种参数，包括：
    - kubeconfig 配置路径
    - informer 缓存设置
    - API 请求速率限制
    - 命名空间和服务账户配置
    - 工作负载提供者类型
    - execd 初始化容器资源限制

    Attributes:
        kubeconfig_path: 用于 API 认证的 kubeconfig 文件绝对路径，默认使用集群内服务账户
        informer_enabled: [Beta] 启用 informer 支持的缓存用于工作负载读取，
                          保持 watch 以减少 API 压力，设为 false 禁用
        informer_resync_seconds: [Beta] informer 缓存的全量重新同步间隔（秒），
                                 较短的间隔会更积极地刷新缓存
        informer_watch_timeout_seconds: [Beta] 重启 informer 流之前的 watch 超时时间（秒）
        read_qps: Kubernetes API 读取请求（get/list）的最大每秒请求数，0 表示无限制（不限速）
        read_burst: 读取速率限制器的突发大小，0 表示使用 read_qps 作为突发值（最小为 1）
        write_qps: Kubernetes API 写入请求（create/delete/patch）的最大每秒请求数，0 表示无限制
        write_burst: 写入速率限制器的突发大小，0 表示使用 write_qps 作为突发值（最小为 1）
        namespace: 沙箱工作负载使用的 Kubernetes 命名空间
        service_account: 绑定到沙箱工作负载的服务账户
        workload_provider: 工作负载提供者类型，如果不指定，使用第一个注册的提供者
        batchsandbox_template_file: BatchSandbox CR YAML 模板文件路径，当 workload_provider 为 'batchsandbox' 时使用
        sandbox_create_timeout_seconds: 创建后等待沙箱就绪（分配 IP）的超时时间（秒）
        sandbox_create_poll_interval_seconds: 等待沙箱就绪时的轮询间隔（秒）
        execd_init_resources: execd 初始化容器的资源请求/限制，如果不设置则不应用资源约束
    """

    kubeconfig_path: Optional[str] = Field(
        default=None,
        description="Absolute path to the kubeconfig file used for API authentication.",
    )
    informer_enabled: bool = Field(
        default=True,
        description=(
            "[Beta] Enable informer-backed cache for workload reads. "
            "Keeps a watch to reduce API pressure; set false to disable."
        ),
    )
    informer_resync_seconds: int = Field(
        default=300,
        ge=1,
        description=(
            "[Beta] Full resync interval for informer cache (seconds). "
            "Shorter intervals refresh the cache more eagerly."
        ),
    )
    informer_watch_timeout_seconds: int = Field(
        default=60,
        ge=1,
        description=(
            "[Beta] Watch timeout (seconds) before restarting the informer stream."
        ),
    )
    read_qps: float = Field(
        default=0.0,
        ge=0,
        description=(
            "Maximum read requests per second to the Kubernetes API (get/list). "
            "0 means unlimited (no rate limiting)."
        ),
    )
    read_burst: int = Field(
        default=0,
        ge=0,
        description=(
            "Burst size for the read rate limiter. "
            "0 means use read_qps as burst (minimum 1)."
        ),
    )
    write_qps: float = Field(
        default=0.0,
        ge=0,
        description=(
            "Maximum write requests per second to the Kubernetes API (create/delete/patch). "
            "0 means unlimited (no rate limiting)."
        ),
    )
    write_burst: int = Field(
        default=0,
        ge=0,
        description=(
            "Burst size for the write rate limiter. "
            "0 means use write_qps as burst (minimum 1)."
        ),
    )
    namespace: Optional[str] = Field(
        default=None,
        description="Namespace used for sandbox workloads.",
    )
    service_account: Optional[str] = Field(
        default=None,
        description="Service account bound to sandbox workloads.",
    )
    workload_provider: Optional[str] = Field(
        default=None,
        description="Workload provider type. If not specified, uses the first registered provider.",
    )
    batchsandbox_template_file: Optional[str] = Field(
        default=None,
        description="Path to BatchSandbox CR YAML template file. Used when workload_provider is 'batchsandbox'.",
    )
    sandbox_create_timeout_seconds: int = Field(
        default=60,
        ge=1,
        description="Timeout in seconds to wait for a sandbox to become ready (IP assigned) after creation.",
    )
    sandbox_create_poll_interval_seconds: float = Field(
        default=1.0,
        gt=0,
        description="Polling interval in seconds when waiting for a sandbox to become ready after creation.",
    )
    execd_init_resources: Optional["ExecdInitResources"] = Field(
        default=None,
        description=(
            "Resource requests/limits for the execd init container. "
            "If unset, no resource constraints are applied."
        ),
    )


class ExecdInitResources(BaseModel):
    """Resource requests and limits for the execd init container."""

    limits: Optional[Dict[str, str]] = Field(
        default=None,
        description='Resource limits, e.g. {cpu = "100m", memory = "128Mi"}.',
    )
    requests: Optional[Dict[str, str]] = Field(
        default=None,
        description='Resource requests, e.g. {cpu = "50m", memory = "64Mi"}.',
    )


class AgentSandboxRuntimeConfig(BaseModel):
    """Agent-sandbox runtime configuration."""

    template_file: Optional[str] = Field(
        default=None,
        description="Path to Sandbox CR YAML template file for agent-sandbox.",
    )
    shutdown_policy: Literal["Delete", "Retain"] = Field(
        default="Delete",
        description="Shutdown policy applied when a sandbox expires (Delete or Retain).",
    )
    ingress_enabled: bool = Field(
        default=True,
        description="Whether ingress routing to agent-sandbox pods is expected to be enabled.",
    )


class StorageConfig(BaseModel):
    """Volume and storage configuration for sandbox mounts."""

    allowed_host_paths: list[str] = Field(
        default_factory=list,
        description=(
            "Allowlist of host path prefixes permitted for host bind mounts. "
            "If empty, all host paths are allowed (not recommended for production). "
            "Each entry must be an absolute path (e.g., '/data/opensandbox')."
        ),
    )
    ossfs_mount_root: str = Field(
        default="/mnt/ossfs",
        description=(
            "Host-side root directory where OSSFS mounts are resolved. "
            "Resolved OSSFS host paths are built as "
            "'ossfs_mount_root/<bucket>/<volume.subPath?>'."
        ),
    )


class EgressConfig(BaseModel):
    """Egress sidecar configuration."""

    image: Optional[str] = Field(
        default=None,
        description="Container image for the egress sidecar (used when network policy is requested).",
        min_length=1,
    )


class RuntimeConfig(BaseModel):
    """Runtime selection (docker, kubernetes, etc.)."""

    type: Literal["docker", "kubernetes"] = Field(
        ...,
        description="Active sandbox runtime implementation.",
    )
    execd_image: str = Field(
        ...,
        description="Container image that contains the execd binary for sandbox initialization.",
        min_length=1,
    )


class SecureRuntimeConfig(BaseModel):
    """Secure container runtime configuration (gVisor, Kata, Firecracker)."""

    type: Literal["", "gvisor", "kata", "firecracker"] = Field(
        default="",
        description=(
            "Secure runtime type. Empty means no secure runtime. "
            "gVisor uses runsc OCI runtime. "
            "Kata uses kata-runtime (OCI) or kata-qemu (RuntimeClass). "
            "Firecracker uses kata-fc (RuntimeClass, Kubernetes only)."
        ),
    )
    docker_runtime: Optional[str] = Field(
        default=None,
        description=(
            "OCI runtime name for Docker (e.g., 'runsc' for gVisor, 'kata-runtime' for Kata). "
            "When specified, the Docker daemon will use this runtime instead of runc."
        ),
    )
    k8s_runtime_class: Optional[str] = Field(
        default=None,
        description=(
            "Kubernetes RuntimeClass name for secure containers. "
            "Common values: 'gvisor', 'kata-qemu', 'kata-fc'. "
            "When specified, pods will have runtimeClassName set to this value."
        ),
    )

    @model_validator(mode="after")
    def validate_secure_runtime(self) -> "SecureRuntimeConfig":
        if self.type == "":
            # No secure runtime configured
            if self.docker_runtime is not None or self.k8s_runtime_class is not None:
                raise ValueError(
                    "docker_runtime and k8s_runtime_class must be omitted when secure_runtime.type is empty."
                )
            return self

        if self.type == "firecracker":
            # Firecracker is Kubernetes-only
            if self.k8s_runtime_class is None:
                raise ValueError(
                    "secure_runtime.k8s_runtime_class is required when secure_runtime.type is 'firecracker'."
                )
            # Optional: also allow docker_runtime for consistency, but Firecracker won't use it

        # For gVisor and Kata, at least one runtime must be specified
        if self.type in ("gvisor", "kata"):
            if self.docker_runtime is None and self.k8s_runtime_class is None:
                raise ValueError(
                    f"At least one of secure_runtime.docker_runtime or secure_runtime.k8s_runtime_class "
                    f"must be specified when secure_runtime.type is '{self.type}'."
                )

        return self


class DockerConfig(BaseModel):
    """Docker runtime specific settings."""

    network_mode: str = Field(
        default="host",
        description="Docker network mode for sandbox containers (host, bridge, or a custom user-defined network name).",
    )
    api_timeout: Optional[int] = Field(
        default=None,
        ge=1,
        description="Docker API timeout in seconds. If unset, default is 180.",
    )
    host_ip: Optional[str] = Field(
        default=None,
        description=(
            "Docker host IP or hostname for bridge-mode endpoint URLs when the server runs in a container."
        ),
    )
    drop_capabilities: list[str] = Field(
        default_factory=lambda: [
            "AUDIT_WRITE",
            "MKNOD",
            "NET_ADMIN",
            "NET_RAW",
            "SYS_ADMIN",
            "SYS_MODULE",
            "SYS_PTRACE",
            "SYS_TIME",
            "SYS_TTY_CONFIG",
        ],
        description=(
            "Linux capabilities to drop from sandbox containers. Defaults to a conservative set to reduce host impact."
        ),
    )
    apparmor_profile: Optional[str] = Field(
        default=None,
        description=(
            "Optional AppArmor profile name applied to sandbox containers. Leave unset to let Docker choose the default."
        ),
    )
    no_new_privileges: bool = Field(
        default=True,
        description="Enable the kernel no_new_privileges flag to block privilege escalation inside the container.",
    )
    seccomp_profile: Optional[str] = Field(
        default=None,
        description=(
            "Optional seccomp profile name or path applied to sandbox containers. Leave unset to use Docker's default profile."
        ),
    )
    pids_limit: Optional[int] = Field(
        default=512,
        ge=1,
        description="Maximum number of processes allowed per sandbox container. Set to null to disable the limit.",
    )


class AppConfig(BaseModel):
    """Root application configuration model."""

    server: ServerConfig = Field(default_factory=ServerConfig)
    runtime: RuntimeConfig = Field(..., description="Sandbox runtime configuration.")
    kubernetes: Optional[KubernetesRuntimeConfig] = None
    agent_sandbox: Optional["AgentSandboxRuntimeConfig"] = None
    ingress: Optional[IngressConfig] = None
    docker: DockerConfig = Field(default_factory=DockerConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    egress: Optional[EgressConfig] = None
    secure_runtime: Optional[SecureRuntimeConfig] = Field(
        default=None,
        description="Secure container runtime configuration (gVisor, Kata, Firecracker).",
    )

    @model_validator(mode="after")
    def validate_runtime_blocks(self) -> "AppConfig":
        if self.runtime.type == "docker":
            if self.kubernetes is not None:
                raise ValueError("Kubernetes block must be omitted when runtime.type = 'docker'.")
            if self.agent_sandbox is not None:
                raise ValueError("agent_sandbox block must be omitted when runtime.type = 'docker'.")
            if self.ingress is not None and self.ingress.mode != INGRESS_MODE_DIRECT:
                raise ValueError("ingress.mode must be 'direct' when runtime.type = 'docker'.")
            if self.secure_runtime is not None and self.secure_runtime.type == "firecracker":
                raise ValueError( "secure_runtime.type 'firecracker' is only compatible with runtime.type='kubernetes'.")
        elif self.runtime.type == "kubernetes":
            if self.kubernetes is None:
                self.kubernetes = KubernetesRuntimeConfig()
            provider_type = (self.kubernetes.workload_provider or "").lower()
            if provider_type == "agent-sandbox":
                if self.agent_sandbox is None:
                    self.agent_sandbox = AgentSandboxRuntimeConfig()
            elif self.agent_sandbox is not None:
                raise ValueError(
                    "agent_sandbox block requires kubernetes.workload_provider = 'agent-sandbox'."
                )
        else:
            raise ValueError(f"Unsupported runtime type '{self.runtime.type}'.")
        return self


_config: AppConfig | None = None
_config_path: Path | None = None


def _resolve_config_path(path: str | Path | None = None) -> Path:
    """Resolve configuration file path from explicit value, env var, or default."""
    if path:
        return Path(path).expanduser()
    env_path = os.environ.get(CONFIG_ENV_VAR)
    if env_path:
        return Path(env_path).expanduser()
    return DEFAULT_CONFIG_PATH


def _load_toml_data(path: Path) -> dict[str, Any]:
    """Load TOML content from file, returning empty dict if file is missing."""
    if not path.exists():
        logger.info("Config file %s not found. Using default configuration.", path)
        return {}

    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
            logger.info("Loaded configuration from %s", path)
            return data
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to read config file %s: %s", path, exc)
        raise


def load_config(path: str | Path | None = None) -> AppConfig:
    """
    Load configuration from TOML file and store it globally.

    Args:
        path: Optional explicit config path. Falls back to SANDBOX_CONFIG_PATH env,
              then ~/.sandbox.toml when not provided.

    Returns:
        AppConfig: Parsed application configuration.

    Raises:
        ValidationError: If the TOML contents do not match AppConfig schema.
        Exception: For any IO or parsing errors.
    """
    global _config, _config_path

    resolved_path = _resolve_config_path(path)
    raw_data = _load_toml_data(resolved_path)

    try:
        _config = AppConfig(**raw_data)
    except ValidationError as exc:
        logger.error("Invalid configuration in %s: %s", resolved_path, exc)
        raise

    _config_path = resolved_path
    return _config


def get_config() -> AppConfig:
    """
    Retrieve the currently loaded configuration, loading defaults if necessary.

    Returns:
        AppConfig: Currently active configuration.
    """
    global _config
    if _config is None:
        _config = load_config()
    return _config


def get_config_path() -> Path:
    """Return the resolved configuration path."""
    global _config_path
    if _config_path is None:
        _config_path = _resolve_config_path()
    return _config_path


__all__ = [
    "AppConfig",
    "ServerConfig",
    "RuntimeConfig",
    "IngressConfig",
    "GatewayConfig",
    "GatewayRouteModeConfig",
    "INGRESS_MODE_DIRECT",
    "INGRESS_MODE_GATEWAY",
    "DockerConfig",
    "StorageConfig",
    "KubernetesRuntimeConfig",
    "EgressConfig",
    "SecureRuntimeConfig",
    "DEFAULT_CONFIG_PATH",
    "CONFIG_ENV_VAR",
    "get_config",
    "get_config_path",
    "load_config",
]
