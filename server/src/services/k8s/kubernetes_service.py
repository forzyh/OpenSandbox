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
基于 Kubernetes 的 Sandbox 服务实现模块。

本模块提供了 KubernetesSandboxService 类，是 SandboxService 接口在
Kubernetes 运行时下的具体实现。它使用 Kubernetes 资源（如 Pod 或 CRD）
来管理 sandbox 的生命周期。

主要功能：
- 创建 sandbox（使用 Kubernetes 工作负载提供者）
- 获取/删除/列出 sandbox
- 更新过期时间
- 获取 sandbox 端点信息
- 等待 sandbox 就绪
- 支持网络策略（egress 侧车）
- 支持镜像拉取认证
- 支持卷挂载

架构说明：
    KubernetesSandboxService 通过 WorkloadProvider 抽象与底层
    Kubernetes 资源交互。当前支持的提供者：
    - BatchSandboxProvider：使用 BatchSandbox CRD
    - AgentSandboxProvider：使用 Agent-sandbox CRD

使用示例：
    >>> service = KubernetesSandboxService(app_config)
    >>> response = service.create_sandbox(request)
    >>> sandbox = service.get_sandbox(response.id)
"""

import logging
import time
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from fastapi import HTTPException, status

from src.api.schema import (
    CreateSandboxRequest,
    CreateSandboxResponse,
    Endpoint,
    ImageSpec,
    ListSandboxesRequest,
    ListSandboxesResponse,
    PaginationInfo,
    RenewSandboxExpirationRequest,
    RenewSandboxExpirationResponse,
    Sandbox,
    SandboxStatus,
)
from src.config import AppConfig, get_config
from src.services.constants import (
    SANDBOX_ID_LABEL,
    SandboxErrorCodes,
)
from src.services.helpers import matches_filter
from src.services.sandbox_service import SandboxService
from src.services.validators import (
    calculate_expiration_or_raise,
    ensure_entrypoint,
    ensure_egress_configured,
    ensure_future_expiration,
    ensure_metadata_labels,
    ensure_timeout_within_limit,
    ensure_volumes_valid,
)
from src.services.k8s.client import K8sClient
from src.services.k8s.provider_factory import create_workload_provider

logger = logging.getLogger(__name__)


class KubernetesSandboxService(SandboxService):
    """
    基于 Kubernetes 的 SandboxService 实现。

    该类使用 Kubernetes 资源实现 sandbox 生命周期管理。

    特性：
    - 使用 WorkloadProvider 抽象支持不同的 Kubernetes 资源类型
    - 支持模板模式和池模式（取决于提供者）
    - 支持安全运行时（RuntimeClass）
    - 支持网络策略（egress 侧车）
    - 支持镜像拉取认证
    - 支持卷挂载（PVC、hostPath）
    - 自动等待 sandbox 就绪

    Attributes:
        app_config: 应用配置
        ingress_config: Ingress 配置
        namespace: Kubernetes 命名空间
        execd_image: execd 守护进程镜像
        k8s_client: Kubernetes 客户端
        workload_provider: 工作负载提供者

    Examples:
        >>> service = KubernetesSandboxService(app_config)
        >>> response = service.create_sandbox(request)
    """

    def __init__(self, config: Optional[AppConfig] = None):
        """
        初始化 Kubernetes sandbox 服务。

        Args:
            config: 应用配置

        Raises:
            HTTPException: 如果初始化失败
            ValueError: 如果配置不兼容
        """
        self.app_config = config or get_config()
        runtime_config = self.app_config.runtime

        if runtime_config.type != "kubernetes":
            raise ValueError("KubernetesSandboxService 需要 runtime.type = 'kubernetes'")

        if not self.app_config.kubernetes:
            raise ValueError("Kubernetes 配置是必需的")

        # Ingress 配置（直接/gateway）
        self.ingress_config = self.app_config.ingress

        self.namespace = self.app_config.kubernetes.namespace
        self.execd_image = runtime_config.execd_image

        # 初始化 Kubernetes 客户端
        try:
            self.k8s_client = K8sClient(self.app_config.kubernetes)
            logger.info("Kubernetes 客户端初始化成功")
        except Exception as e:
            logger.error(f"初始化 Kubernetes 客户端失败：{e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": SandboxErrorCodes.K8S_INITIALIZATION_ERROR,
                    "message": f"初始化 Kubernetes 客户端失败：{str(e)}",
                },
            ) from e

        # 初始化工作负载提供者
        provider_type = self.app_config.kubernetes.workload_provider
        try:
            self.workload_provider = create_workload_provider(
                provider_type=provider_type,
                k8s_client=self.k8s_client,
                app_config=self.app_config,
            )
            logger.info(
                f"初始化工作负载提供者：{self.workload_provider.__class__.__name__}"
            )
        except ValueError as e:
            logger.error(f"创建工作负载提供者失败：{e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": SandboxErrorCodes.K8S_INITIALIZATION_ERROR,
                    "message": f"工作负载提供者配置无效：{str(e)}",
                },
            ) from e

        logger.info(
            "KubernetesSandboxService 初始化完成：namespace=%s, execd_image=%s",
            self.namespace,
            self.execd_image,
        )

    def _wait_for_sandbox_ready(
        self,
        sandbox_id: str,
        timeout_seconds: int = 60,
        poll_interval_seconds: float = 1.0,
    ) -> Dict[str, Any]:
        """
        等待 Pod 进入 Running 状态并具有 IP 地址。

        该方法轮询 sandbox 状态，直到：
        - Pod 状态为 Running 或 Allocated（已分配 IP）
        - 超时

        Args:
            sandbox_id: Sandbox 唯一标识符
            timeout_seconds: 最大等待时间（秒）
            poll_interval_seconds: 轮询间隔（秒）

        Returns:
            Dict[str, Any]: 当 Pod 处于 Running 状态且有 IP 时返回工作负载字典

        Raises:
            HTTPException: 如果超时或 Pod 状态失败

        状态流转：
            Pending -> Allocated (已分配 IP) -> Running (Pod 就绪)
        """
        logger.info(
            f"等待 sandbox {sandbox_id} 进入 Running 状态且有 IP（超时：{timeout_seconds}秒）"
        )

        start_time = time.time()
        last_state = None
        last_message = None

        while time.time() - start_time < timeout_seconds:
            try:
                # 获取当前工作负载状态
                workload = self.workload_provider.get_workload(
                    sandbox_id=sandbox_id,
                    namespace=self.namespace,
                )

                if not workload:
                    logger.debug(f"sandbox {sandbox_id} 的工作负载还未找到")
                    time.sleep(poll_interval_seconds)
                    continue

                # 获取状态
                status_info = self.workload_provider.get_status(workload)
                current_state = status_info["state"]
                current_message = status_info["message"]

                # 记录状态变化
                if current_state != last_state or current_message != last_message:
                    logger.info(
                        f"Sandbox {sandbox_id} 状态：{current_state} - {current_message}"
                    )
                    last_state = current_state
                    last_message = current_message

                # 检查是否 Running 或 Allocated（已分配 IP）
                if current_state in ("Running", "Allocated"):
                    return workload

            except HTTPException:
                raise
            except Exception as e:
                logger.warning(
                    f"检查 sandbox {sandbox_id} 状态时出错：{e}",
                    exc_info=True
                )

            # 等待下次轮询
            time.sleep(poll_interval_seconds)

        # 超时
        elapsed = time.time() - start_time
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail={
                "code": SandboxErrorCodes.K8S_POD_READY_TIMEOUT,
                "message": (
                    f"等待 sandbox {sandbox_id} 进入 Running 状态且有 IP 超时。"
                    f"已用时间：{elapsed:.1f}秒，最后状态：{last_state}"
                ),
            },
        )

    def _ensure_network_policy_support(self, request: CreateSandboxRequest) -> None:
        """
        验证在当前运行时配置下可以满足网络策略要求。

        这验证了在提供 network_policy 时是否配置了 egress.image。
        """
        # 通用验证：必须配置 egress.image
        ensure_egress_configured(request.network_policy, self.app_config.egress)

    def _ensure_image_auth_support(self, request: CreateSandboxRequest) -> None:
        """
        验证当前工作负载提供者是否支持镜像认证。

        如果提供者不支持按请求的镜像认证，抛出 HTTP 400 错误。
        """
        if request.image.auth is None:
            return
        if self.workload_provider.supports_image_auth():
            return
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": SandboxErrorCodes.INVALID_PARAMETER,
                "message": (
                    "当前工作负载提供者不支持 image.auth。"
                    "请通过 Kubernetes ServiceAccount 或 sandbox 模板使用 imagePullSecrets。"
                ),
            },
        )

    def create_sandbox(self, request: CreateSandboxRequest) -> CreateSandboxResponse:
        """
        使用 Kubernetes Pod 创建新的 sandbox。

        在返回之前等待 Pod 进入 Running 状态并具有 IP 地址。

        Args:
            request: Sandbox 创建请求

        Returns:
            CreateSandboxResponse: 创建的 sandbox 信息，状态为 Running

        Raises:
            HTTPException: 如果创建失败、超时或参数无效
        """
        # 验证请求
        ensure_entrypoint(request.entrypoint)
        ensure_metadata_labels(request.metadata)
        ensure_timeout_within_limit(
            request.timeout,
            self.app_config.server.max_sandbox_timeout_seconds,
        )
        self._ensure_network_policy_support(request)
        self._ensure_image_auth_support(request)

        # 生成 sandbox ID
        sandbox_id = self.generate_sandbox_id()

        # 计算过期时间
        created_at = datetime.now(timezone.utc)
        expires_at = None
        if request.timeout is not None:
            expires_at = calculate_expiration_or_raise(created_at, request.timeout)
        elif not self.workload_provider.supports_manual_cleanup():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": SandboxErrorCodes.INVALID_PARAMETER,
                    "message": (
                        "当前 Kubernetes 工作负载提供者不支持手动清理模式。"
                    ),
                },
            )

        # 构建标签
        labels = {
            SANDBOX_ID_LABEL: sandbox_id,
        }

        # 添加用户元数据作为标签
        if request.metadata:
            labels.update(request.metadata)

        # 提取资源限制
        resource_limits = {}
        if request.resource_limits and request.resource_limits.root:
            resource_limits = request.resource_limits.root

        try:
            # 如果提供了网络策略，获取 egress 镜像
            egress_image = None
            if request.network_policy:
                egress_image = self.app_config.egress.image if self.app_config.egress else None

            # 在创建工作负载之前验证卷
            ensure_volumes_valid(
                request.volumes,
                self.app_config.storage.allowed_host_paths or None,
            )

            # 创建工作负载
            workload_info = self.workload_provider.create_workload(
                sandbox_id=sandbox_id,
                namespace=self.namespace,
                image_spec=request.image,
                entrypoint=request.entrypoint,
                env=request.env or {},
                resource_limits=resource_limits,
                labels=labels,
                expires_at=expires_at,
                execd_image=self.execd_image,
                extensions=request.extensions,
                network_policy=request.network_policy,
                egress_image=egress_image,
                volumes=request.volumes,
            )

            logger.info(
                "创建了 sandbox：id=%s, workload=%s",
                sandbox_id,
                workload_info.get("name"),
            )

            # 等待 Pod 进入 Running 状态且有 IP
            try:
                workload = self._wait_for_sandbox_ready(
                    sandbox_id=sandbox_id,
                    timeout_seconds=self.app_config.kubernetes.sandbox_create_timeout_seconds,
                    poll_interval_seconds=self.app_config.kubernetes.sandbox_create_poll_interval_seconds,
                )

                # 获取最终状态
                status_info = self.workload_provider.get_status(workload)

                # 构建并返回 Running 状态的响应
                return CreateSandboxResponse(
                    id=sandbox_id,
                    status=SandboxStatus(
                        state=status_info["state"],
                        reason=status_info["reason"],
                        message=status_info["message"],
                        last_transition_at=status_info["last_transition_at"],
                    ),
                    created_at=created_at,
                    expires_at=expires_at,
                    metadata=request.metadata,
                    image=request.image,
                    entrypoint=request.entrypoint,
                )

            except HTTPException:
                # 失败时清理
                try:
                    logger.warning(f"创建失败，清理 sandbox：{sandbox_id}")
                    self.workload_provider.delete_workload(sandbox_id, self.namespace)
                except Exception as cleanup_ex:
                    logger.error(f"清理 sandbox {sandbox_id} 失败", exc_info=cleanup_ex)
                raise

        except HTTPException:
            raise
        except ValueError as e:
            # 处理来自提供者的参数验证错误
            logger.error(f"sandbox 创建参数无效：{e}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": SandboxErrorCodes.INVALID_PARAMETER,
                    "message": str(e),
                },
            ) from e
        except Exception as e:
            logger.error(f"创建 sandbox 时出错：{e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={
                    "code": SandboxErrorCodes.K8S_API_ERROR,
                    "message": f"创建 sandbox 失败：{str(e)}",
                },
            ) from e

    def get_sandbox(self, sandbox_id: str) -> Sandbox:
        """
        按 ID 获取 sandbox。

        Args:
            sandbox_id: Sandbox 唯一标识符

        Returns:
            Sandbox: Sandbox 信息

        Raises:
            HTTPException: 如果 sandbox 未找到
        """
        try:
            workload = self.workload_provider.get_workload(
                sandbox_id=sandbox_id,
                namespace=self.namespace,
            )

            if not workload:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={
                        "code": SandboxErrorCodes.K8S_SANDBOX_NOT_FOUND,
                        "message": f"Sandbox '{sandbox_id}' 未找到",
                    },
                )

            return self._build_sandbox_from_workload(workload)

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"获取 sandbox {sandbox_id} 时出错：{e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={
                    "code": SandboxErrorCodes.K8S_API_ERROR,
                    "message": f"获取 sandbox 失败：{str(e)}",
                },
            ) from e

    def list_sandboxes(self, request: ListSandboxesRequest) -> ListSandboxesResponse:
        """
        列出 sandbox，支持过滤和分页。

        Args:
            request: 包含过滤器和分页信息的列表请求

        Returns:
            ListSandboxesResponse: 分页的 sandbox 列表
        """
        try:
            # 构建标签选择器
            label_selector = SANDBOX_ID_LABEL

            # 列出所有工作负载
            workloads = self.workload_provider.list_workloads(
                namespace=self.namespace,
                label_selector=label_selector,
            )

            # 转换为 Sandbox 对象
            sandboxes = [
                self._build_sandbox_from_workload(w) for w in workloads
            ]

            # 应用过滤器
            filtered = self._apply_filters(sandboxes, request.filter)

            # 按创建时间排序（最新的在前）
            filtered.sort(key=lambda s: s.created_at or datetime.min, reverse=True)

            # 应用分页
            total_items = len(filtered)
            page = request.pagination.page
            page_size = request.pagination.page_size

            start_idx = (page - 1) * page_size
            end_idx = start_idx + page_size
            paginated_items = filtered[start_idx:end_idx]

            total_pages = (total_items + page_size - 1) // page_size
            has_next = page < total_pages

            return ListSandboxesResponse(
                items=paginated_items,
                pagination=PaginationInfo(
                    page=page,
                    page_size=page_size,
                    total_items=total_items,
                    total_pages=total_pages,
                    has_next_page=has_next,
                ),
            )

        except Exception as e:
            logger.error(f"列出 sandbox 时出错：{e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={
                    "code": SandboxErrorCodes.K8S_API_ERROR,
                    "message": f"列出 sandbox 失败：{str(e)}",
                },
            ) from e

    def delete_sandbox(self, sandbox_id: str) -> None:
        """
        删除 sandbox。

        Args:
            sandbox_id: Sandbox 唯一标识符

        Raises:
            HTTPException: 如果删除失败
        """
        try:
            self.workload_provider.delete_workload(
                sandbox_id=sandbox_id,
                namespace=self.namespace,
            )

            logger.info(f"删除了 sandbox：{sandbox_id}")

        except Exception as e:
            if "not found" in str(e).lower():
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={
                        "code": SandboxErrorCodes.K8S_SANDBOX_NOT_FOUND,
                        "message": f"Sandbox '{sandbox_id}' 未找到",
                    },
                ) from e

            logger.error(f"删除 sandbox {sandbox_id} 时出错：{e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={
                    "code": SandboxErrorCodes.K8S_API_ERROR,
                    "message": f"删除 sandbox 失败：{str(e)}",
                },
            ) from e

    def pause_sandbox(self, sandbox_id: str) -> None:
        """
        暂停 sandbox（Kubernetes 不支持）。

        Args:
            sandbox_id: Sandbox 唯一标识符

        Raises:
            HTTPException: 始终抛出 501 Not Implemented
        """
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail={
                "code": SandboxErrorCodes.API_NOT_SUPPORTED,
                "message": "Kubernetes 运行时不支持 Pause 操作",
            },
        )

    def resume_sandbox(self, sandbox_id: str) -> None:
        """
        恢复 sandbox（Kubernetes 不支持）。

        Args:
            sandbox_id: Sandbox 唯一标识符

        Raises:
            HTTPException: 始终抛出 501 Not Implemented
        """
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail={
                "code": SandboxErrorCodes.API_NOT_SUPPORTED,
                "message": "Kubernetes 运行时不支持 Resume 操作",
            },
        )

    def renew_expiration(
        self,
        sandbox_id: str,
        request: RenewSandboxExpirationRequest,
    ) -> RenewSandboxExpirationResponse:
        """
        更新 sandbox 过期时间。

        同时更新 BatchSandbox spec.expireTime 字段和标签以保持一致性。

        Args:
            sandbox_id: Sandbox 唯一标识符
            request: 包含新过期时间的更新请求

        Returns:
            RenewSandboxExpirationResponse: 更新后的过期时间

        Raises:
            HTTPException: 如果更新失败
        """
        # 验证过期时间是未来时间
        new_expiration = ensure_future_expiration(request.expires_at)

        try:
            # 验证 sandbox 存在
            workload = self.workload_provider.get_workload(
                sandbox_id=sandbox_id,
                namespace=self.namespace,
            )

            if not workload:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={
                        "code": SandboxErrorCodes.K8S_SANDBOX_NOT_FOUND,
                        "message": f"Sandbox '{sandbox_id}' 未找到",
                    },
                )

            current_expiration = self.workload_provider.get_expiration(workload)
            if current_expiration is None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "code": SandboxErrorCodes.INVALID_EXPIRATION,
                        "message": f"Sandbox {sandbox_id} 未启用自动过期。",
                    },
                )

            # 更新 BatchSandbox spec.expireTime 字段
            self.workload_provider.update_expiration(
                sandbox_id=sandbox_id,
                namespace=self.namespace,
                expires_at=new_expiration,
            )

            logger.info(
                f"更新了 sandbox {sandbox_id} 的过期时间为 {new_expiration}"
            )

            return RenewSandboxExpirationResponse(
                expires_at=new_expiration
            )

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"为 {sandbox_id} 更新过期时间时出错：{e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={
                    "code": SandboxErrorCodes.K8S_API_ERROR,
                    "message": f"更新过期时间失败：{str(e)}",
                },
            ) from e

    def get_endpoint(
        self,
        sandbox_id: str,
        port: int,
        resolve_internal: bool = False,
    ) -> Endpoint:
        """
        获取 sandbox 访问端点。

        Args:
            sandbox_id: Sandbox 唯一标识符
            port: 端口号
            resolve_internal: 对 Kubernetes 忽略（始终返回 Pod IP）

        Returns:
            Endpoint: 端点信息

        Raises:
            HTTPException: 如果端点不可用
        """
        self.validate_port(port)

        try:
            workload = self.workload_provider.get_workload(
                sandbox_id=sandbox_id,
                namespace=self.namespace,
            )

            if not workload:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={
                        "code": SandboxErrorCodes.K8S_SANDBOX_NOT_FOUND,
                        "message": f"Sandbox '{sandbox_id}' 未找到",
                    },
                )

            endpoint = self.workload_provider.get_endpoint_info(workload, port, sandbox_id)
            if not endpoint:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={
                        "code": SandboxErrorCodes.K8S_POD_IP_NOT_AVAILABLE,
                        "message": "Pod IP 还不可用。Pod 可能还在启动中。",
                    },
                )
            return endpoint

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"获取 {sandbox_id}:{port} 端点时出错：{e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={
                    "code": SandboxErrorCodes.K8S_API_ERROR,
                    "message": f"获取端点失败：{str(e)}",
                },
            ) from e

    def _build_sandbox_from_workload(self, workload: Any) -> Sandbox:
        """
        从 Kubernetes 工作负载构建 Sandbox 对象。

        支持两种格式：
        - 字典格式（CRD）
        - 对象格式（Pod）

        Args:
            workload: Kubernetes 工作负载对象（V1Pod 或 CRD 字典）

        Returns:
            Sandbox: Sandbox 对象
        """
        # 处理字典（CRD）和对象（Pod）两种格式
        if isinstance(workload, dict):
            metadata = workload.get("metadata", {})
            spec = workload.get("spec", {})
            labels = metadata.get("labels", {})
            creation_timestamp = metadata.get("creationTimestamp")
        else:
            metadata = workload.metadata
            spec = workload.spec
            labels = metadata.labels or {}
            creation_timestamp = metadata.creation_timestamp

        sandbox_id = labels.get(SANDBOX_ID_LABEL, "")

        # 从提供者获取过期时间
        expires_at = self.workload_provider.get_expiration(workload)

        # 获取状态
        status_info = self.workload_provider.get_status(workload)

        # 提取元数据（过滤系统标签）
        user_metadata = {
            k: v for k, v in labels.items()
            if not k.startswith("opensandbox.io/")
        }

        # 从 spec 获取镜像和入口点
        image_uri = ""
        entrypoint = []

        if isinstance(workload, dict):
            # 对于 CRD，从 template 提取
            template = spec.get("template") or spec.get("podTemplate") or {}
            pod_spec = template.get("spec", {})
            containers = pod_spec.get("containers", [])
            if containers:
                container = containers[0]
                image_uri = container.get("image", "")
                entrypoint = container.get("command", [])
        else:
            # 对于 Pod 对象
            if hasattr(spec, 'containers') and spec.containers:
                container = spec.containers[0]
                image_uri = container.image or ""
                entrypoint = container.command or []

        image_spec = ImageSpec(uri=image_uri) if image_uri else ImageSpec(uri="unknown")

        return Sandbox(
            id=sandbox_id,
            status=SandboxStatus(
                state=status_info["state"],
                reason=status_info["reason"],
                message=status_info["message"],
                last_transition_at=status_info["last_transition_at"],
            ),
            created_at=creation_timestamp,
            expires_at=expires_at,
            metadata=user_metadata if user_metadata else None,
            image=image_spec,
            entrypoint=entrypoint,
        )

    def _apply_filters(self, sandboxes: list[Sandbox], filter_spec: Any) -> list[Sandbox]:
        """
        将过滤器应用到 sandbox 列表。

        Args:
            sandboxes: Sandbox 列表
            filter_spec: 过滤器规范

        Returns:
            list[Sandbox]: 过滤后的 sandbox 列表
        """
        if not filter_spec:
            return sandboxes

        filtered = []
        for sandbox in sandboxes:
            if matches_filter(sandbox, filter_spec):
                filtered.append(sandbox)

        return filtered
