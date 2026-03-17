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
沙箱模型转换器模块 - Sandbox Model Converter

本模块提供了 SandboxModelConverter 类，用于在 API 模型和领域模型之间转换沙箱相关数据。

设计目的：
    - 将 openapi-python-client 生成的 API 模型转换为 SDK 领域模型
    - 将领域模型转换为 API 请求体
    - 处理字段名称的映射和类型转换
    - 遵循 Kotlin SDK 的 SandboxModelConverter 模式

核心功能：
    - to_api_image_spec: SandboxImageSpec -> ImageSpec
    - to_api_volume: Volume -> API Volume
    - to_api_create_sandbox_request: 创建沙箱请求参数 -> CreateSandboxRequest
    - to_api_renew_request: datetime -> RenewSandboxExpirationRequest
    - to_sandbox_create_response: CreateSandboxResponse -> SandboxCreateResponse
    - to_sandbox_info: Sandbox -> SandboxInfo
    - to_paged_sandbox_infos: ListSandboxesResponse -> PagedSandboxInfos
    - to_sandbox_endpoint: Endpoint -> SandboxEndpoint

模型差异处理：
    - API 模型使用 attrs，领域模型使用标准类
    - API 使用 'uri'，领域使用 'image'
    - API 使用 UNSET 表示可选字段缺失

使用示例：
    ```python
    from opensandbox.adapters.converter.sandbox_model_converter import SandboxModelConverter
    from opensandbox.models.sandboxes import SandboxImageSpec

    # 领域模型 -> API 模型
    api_spec = SandboxModelConverter.to_api_image_spec(domain_spec)

    # API 模型 -> 领域模型
    sandbox_info = SandboxModelConverter.to_sandbox_info(api_sandbox)
    ```
"""

from datetime import datetime, timedelta, timezone

from opensandbox.api.lifecycle.models import (
    CreateSandboxResponse,
    Endpoint,
    ListSandboxesResponse,
    RenewSandboxExpirationRequest,
    RenewSandboxExpirationResponse,
    Sandbox,
)
from opensandbox.api.lifecycle.models import (
    PaginationInfo as ApiPaginationInfo,
)
from opensandbox.api.lifecycle.models import (
    SandboxStatus as ApiSandboxStatus,
)
from opensandbox.api.lifecycle.models.create_sandbox_request import CreateSandboxRequest
from opensandbox.api.lifecycle.models.image_spec import ImageSpec
from opensandbox.models.sandboxes import (
    NetworkPolicy,
    PagedSandboxInfos,
    PaginationInfo,
    SandboxCreateResponse,
    SandboxEndpoint,
    SandboxImageSpec,
    SandboxInfo,
    SandboxRenewResponse,
    SandboxStatus,
    Volume,
)


class SandboxModelConverter:
    """
    沙箱模型转换器工具类

    本类提供了静态方法，用于在 API 模型和领域模型之间转换沙箱相关数据。
    遵循 Kotlin SDK 的模式。API 模型由 openapi-python-client 生成并使用 attrs，
    领域模型使用标准 Python 类。

    转换方法分类：
        1. 领域 -> API: to_api_* 方法
        2. API -> 领域：to_sandbox_* 方法
        3. 内部辅助：_convert_* 方法

    使用示例：
        ```python
        from opensandbox.adapters.converter.sandbox_model_converter import SandboxModelConverter

        # 创建沙箱请求转换
        api_request = SandboxModelConverter.to_api_create_sandbox_request(
            spec=image_spec,
            entrypoint=["/bin/bash"],
            env={"KEY": "value"},
            metadata={"team": "dev"},
            timeout=timedelta(hours=1),
            resource={"cpu": "1", "memory": "1Gi"},
            network_policy=None,
            extensions={},
            volumes=None
        )
        ```
    """

    @staticmethod
    def to_api_image_spec(spec: SandboxImageSpec) -> ImageSpec:
        """
        将领域模型 SandboxImageSpec 转换为 API ImageSpec

        此方法负责将 SDK 的镜像规格对象转换为 openapi-python-client 生成的
        ImageSpec 对象。处理字段名称映射和认证信息转换。

        参数：
            spec (SandboxImageSpec): 领域模型镜像规格
                - image: 镜像 URI
                - auth: 镜像认证信息（可选）

        返回：
            ImageSpec: API 镜像规格对象
                - uri: 镜像 URI（API 使用 'uri' 而非 'image'）
                - auth: 镜像认证信息（可选）

        字段映射：
            spec.image -> api_spec.uri
            spec.auth -> api_spec.auth

        使用示例：
            ```python
            image_spec = SandboxImageSpec("python:3.11")
            api_spec = SandboxModelConverter.to_api_image_spec(image_spec)
            ```
        """
        from opensandbox.api.lifecycle.models.image_spec_auth import ImageSpecAuth
        from opensandbox.api.lifecycle.types import UNSET

        # 转换认证信息
        auth = UNSET
        if spec.auth:
            auth = ImageSpecAuth(
                username=spec.auth.username,
                password=spec.auth.password,
            )

        # 创建 API 对象
        # 注意：API 使用 'uri' 字段，领域模型使用 'image'
        return ImageSpec(
            uri=spec.image,  # API 使用 'uri'，领域使用 'image'
            auth=auth,
        )

    @staticmethod
    def to_api_volume(volume: Volume) -> Any:
        """
        将领域模型 Volume 转换为 API Volume

        此方法负责将 SDK 的卷配置对象转换为 openapi-python-client 生成的
        Volume 对象。处理 Host 和 PVC 子对象的转换。

        参数：
            volume (Volume): 领域模型卷配置
                - name: 卷名称
                - mount_path: 挂载路径
                - read_only: 是否只读
                - host: Host 卷配置（可选）
                - pvc: PVC 卷配置（可选）
                - sub_path: 子路径（可选）

        返回：
            API Volume: 卷配置对象
                - 可以直接传递给 CreateSandboxRequest

        字段映射：
            - volume.host -> ApiHost(path=...)
            - volume.pvc -> ApiPVC(claim_name=...)
            - volume.sub_path -> 直接映射（可选）

        使用示例：
            ```python
            volume = Volume(
                name="data",
                mount_path="/data",
                host=Host(path="/host/data")
            )
            api_volume = SandboxModelConverter.to_api_volume(volume)
            ```
        """
        from opensandbox.api.lifecycle.models.host import (
            Host as ApiHost,
        )
        from opensandbox.api.lifecycle.models.pvc import (
            PVC as ApiPVC,
        )
        from opensandbox.api.lifecycle.models.volume import Volume as ApiVolume
        from opensandbox.api.lifecycle.types import UNSET

        # 转换 Host 卷配置
        api_host = UNSET
        if volume.host is not None:
            api_host = ApiHost(path=volume.host.path)

        # 转换 PVC 卷配置
        api_pvc = UNSET
        if volume.pvc is not None:
            api_pvc = ApiPVC(claim_name=volume.pvc.claim_name)

        # 转换子路径
        api_sub_path = UNSET
        if volume.sub_path is not None:
            api_sub_path = volume.sub_path

        # 创建 API Volume 对象
        return ApiVolume(
            name=volume.name,
            mount_path=volume.mount_path,
            read_only=volume.read_only,
            host=api_host,
            pvc=api_pvc,
            sub_path=api_sub_path,
        )

    @staticmethod
    def to_api_create_sandbox_request(
        spec: SandboxImageSpec,
        entrypoint: list[str],
        env: dict[str, str],
        metadata: dict[str, str],
        timeout: timedelta | None,
        resource: dict[str, str],
        network_policy: NetworkPolicy | None,
        extensions: dict[str, str],
        volumes: list[Volume] | None,
    ) -> CreateSandboxRequest:
        """
        将领域模型参数转换为 API CreateSandboxRequest

        此方法是创建沙箱的核心转换方法，负责将所有领域模型参数转换为
        openapi-python-client 生成的 CreateSandboxRequest 对象。

        参数：
            spec (SandboxImageSpec): 镜像规格
            entrypoint (list[str]): 入口点命令列表
            env (dict[str, str]): 环境变量字典
            metadata (dict[str, str]): 元数据字典
            timeout (timedelta | None): 超时时间
            resource (dict[str, str]): 资源限制字典
            network_policy (NetworkPolicy | None): 网络策略
            extensions (dict[str, str]): 扩展配置字典
            volumes (list[Volume] | None): 卷配置列表

        返回：
            CreateSandboxRequest: API 创建沙箱请求对象
                - 可以直接传递给 post_sandboxes API

        转换说明：
            - env/metadata/extensions: 字典 -> 对应的 API 模型
            - resource: 字典 -> ResourceLimits
            - network_policy: NetworkPolicy -> ApiNetworkPolicy
            - volumes: list[Volume] -> list[ApiVolume]
            - timeout: timedelta -> int (秒数)

        使用示例：
            ```python
            request = SandboxModelConverter.to_api_create_sandbox_request(
                spec=SandboxImageSpec("python:3.11"),
                entrypoint=["/bin/bash"],
                env={"PYTHONPATH": "/app"},
                metadata={"team": "dev"},
                timeout=timedelta(hours=1),
                resource={"cpu": "1", "memory": "1Gi"},
                network_policy=None,
                extensions={},
                volumes=None
            )
            ```
        """
        from opensandbox.api.lifecycle.models.create_sandbox_request_env import (
            CreateSandboxRequestEnv,
        )
        from opensandbox.api.lifecycle.models.create_sandbox_request_extensions import (
            CreateSandboxRequestExtensions,
        )
        from opensandbox.api.lifecycle.models.create_sandbox_request_metadata import (
            CreateSandboxRequestMetadata,
        )
        from opensandbox.api.lifecycle.models.network_policy import (
            NetworkPolicy as ApiNetworkPolicy,
        )
        from opensandbox.api.lifecycle.models.network_policy_default_action import (
            NetworkPolicyDefaultAction,
        )
        from opensandbox.api.lifecycle.models.network_rule import (
            NetworkRule as ApiNetworkRule,
        )
        from opensandbox.api.lifecycle.models.network_rule_action import (
            NetworkRuleAction,
        )
        from opensandbox.api.lifecycle.models.resource_limits import ResourceLimits
        from opensandbox.api.lifecycle.types import UNSET

        # 转换环境变量的字典到 API 模型
        api_env = UNSET
        if env:
            api_env = CreateSandboxRequestEnv.from_dict(env)

        # 转换元数据字典到 API 模型
        api_metadata = UNSET
        if metadata:
            api_metadata = CreateSandboxRequestMetadata.from_dict(metadata)

        # 转换资源限制字典到 API 模型
        api_resource_limits = ResourceLimits.from_dict(resource)

        # 转换网络策略
        api_network_policy = UNSET
        if network_policy is not None:
            # 类型检查
            if not isinstance(network_policy, NetworkPolicy):
                raise TypeError(
                    "network_policy must be a NetworkPolicy or None, "
                    f"got {type(network_policy).__name__}"
                )

            # 转换默认动作
            api_default_action = UNSET
            if network_policy.default_action:
                api_default_action = NetworkPolicyDefaultAction(
                    network_policy.default_action
                )

            # 转换出站规则列表
            api_egress = UNSET
            if network_policy.egress is not None:
                api_egress = [
                    ApiNetworkRule(
                        action=NetworkRuleAction(rule.action),
                        target=rule.target,
                    )
                    for rule in network_policy.egress
                ]

            # 创建 API 网络策略对象
            api_network_policy = ApiNetworkPolicy(
                default_action=api_default_action,
                egress=api_egress,
            )

        # 转换扩展配置
        api_extensions = (
            CreateSandboxRequestExtensions.from_dict(extensions) if extensions else UNSET
        )

        # 转换卷配置列表
        api_volumes = UNSET
        if volumes is not None and len(volumes) > 0:
            api_volumes = [
                SandboxModelConverter.to_api_volume(v) for v in volumes
            ]

        # 创建 CreateSandboxRequest 对象
        request = CreateSandboxRequest(
            image=SandboxModelConverter.to_api_image_spec(spec),
            entrypoint=entrypoint,
            env=api_env,
            metadata=api_metadata,
            resource_limits=api_resource_limits,
            network_policy=api_network_policy,
            extensions=api_extensions,
            volumes=api_volumes,
        )

        # 设置超时时间（转换为秒数）
        if timeout is not None:
            request.timeout = int(timeout.total_seconds())

        return request

    @staticmethod
    def to_api_renew_request(
        new_expiration_time: datetime,
    ) -> RenewSandboxExpirationRequest:
        """
        将 datetime 转换为 API RenewSandboxExpirationRequest

        此方法负责将过期时间转换为续期请求对象。

        参数：
            new_expiration_time (datetime): 新的过期时间
                - 可以是时区感知或时区 naive 的 datetime

        返回：
            RenewSandboxExpirationRequest: API 续期请求对象

        时区处理：
            - 如果提供的 datetime 是 naive（无时区信息），则视为 UTC 时间
            - 确保序列化时使用明确的时区信息

        使用示例：
            ```python
            from datetime import datetime, timedelta

            new_expiration = datetime.now() + timedelta(hours=1)
            request = SandboxModelConverter.to_api_renew_request(new_expiration)
            ```
        """
        from opensandbox.api.lifecycle.models.renew_sandbox_expiration_request import (
            RenewSandboxExpirationRequest,
        )

        # 确保时区感知
        # 如果提供的是 naive datetime，将其视为 UTC
        if new_expiration_time.tzinfo is None:
            new_expiration_time = new_expiration_time.replace(tzinfo=timezone.utc)

        return RenewSandboxExpirationRequest(
            expires_at=new_expiration_time,
        )

    @staticmethod
    def to_sandbox_renew_response(
        api_response: RenewSandboxExpirationResponse,
    ) -> SandboxRenewResponse:
        """
        将 API RenewSandboxExpirationResponse 转换为领域模型 SandboxRenewResponse

        注意：我们有意让公共 SDK 使用领域模型而不是生成的 OpenAPI 客户端模型。

        参数：
            api_response (RenewSandboxExpirationResponse): API 续期响应

        返回：
            SandboxRenewResponse: 领域模型续期响应
                - expires_at: 新的过期时间

        异常：
            TypeError: 如果传入的类型不正确
        """
        # 类型检查
        if not isinstance(api_response, RenewSandboxExpirationResponse):
            raise TypeError(
                f"Expected RenewSandboxExpirationResponse, got {type(api_response).__name__}"
            )

        return SandboxRenewResponse(expires_at=api_response.expires_at)

    @staticmethod
    def to_sandbox_create_response(
        api_response: CreateSandboxResponse,
    ) -> SandboxCreateResponse:
        """
        将 API CreateSandboxResponse 转换为领域模型 SandboxCreateResponse

        参数：
            api_response (CreateSandboxResponse): API 创建沙箱响应

        返回：
            SandboxCreateResponse: 领域模型创建沙箱响应
                - id: 沙箱 ID（字符串）
        """
        return SandboxCreateResponse(
            id=str(api_response.id)  # 转换为字符串
        )

    @staticmethod
    def to_sandbox_info(api_sandbox: Sandbox) -> SandboxInfo:
        """
        将 API Sandbox 转换为领域模型 SandboxInfo

        此方法负责将 openapi-python-client 生成的 Sandbox 对象转换为
        SDK 的 SandboxInfo 对象。处理复杂的嵌套对象和可选字段。

        参数：
            api_sandbox (Sandbox): API 沙箱对象
                - 包含沙箱的所有信息

        返回：
            SandboxInfo: 领域模型沙箱信息
                - id: 沙箱 ID
                - status: 沙箱状态
                - image: 镜像规格（可选）
                - created_at: 创建时间
                - expires_at: 过期时间（可选）
                - entrypoint: 入口点
                - metadata: 元数据字典

        处理说明：
            - 镜像规格：处理 auth 嵌套对象
            - 元数据：从 additional_properties 提取
            - 状态：使用 _convert_sandbox_status 转换
            - Unset 类型：检查并转换为 None
        """
        from opensandbox.api.lifecycle.types import Unset
        from opensandbox.models.sandboxes import (
            SandboxImageAuth,
            SandboxImageSpec,
            SandboxInfo,
        )

        # 转换镜像规格
        domain_image_spec = None
        if hasattr(api_sandbox, "image") and not isinstance(api_sandbox.image, Unset):
            auth = None
            # 检查并提取认证信息
            if hasattr(api_sandbox.image, "auth") and not isinstance(
                api_sandbox.image.auth, Unset
            ):
                auth_obj = api_sandbox.image.auth
                username_val = getattr(auth_obj, "username", None)
                password_val = getattr(auth_obj, "password", None)
                if isinstance(username_val, str) and isinstance(password_val, str):
                    auth = SandboxImageAuth(username=username_val, password=password_val)

            # 创建领域镜像规格
            domain_image_spec = SandboxImageSpec(
                image=api_sandbox.image.uri,
                auth=auth,
            )

        # 提取元数据
        metadata: dict[str, str] = {}
        if hasattr(api_sandbox, "metadata") and not isinstance(api_sandbox.metadata, Unset):
            metadata_obj = api_sandbox.metadata
            # 从 additional_properties 提取
            if hasattr(metadata_obj, "additional_properties") and not isinstance(
                getattr(metadata_obj, "additional_properties", None), Unset
            ):
                props = metadata_obj.additional_properties
                if isinstance(props, dict):
                    metadata = dict(props)
            # 或者直接是字典
            elif isinstance(metadata_obj, dict):
                metadata = metadata_obj

        # 处理过期时间
        expires_at = api_sandbox.expires_at
        if isinstance(expires_at, Unset):
            expires_at = None

        # 创建领域沙箱信息
        return SandboxInfo(
            id=api_sandbox.id,
            status=SandboxModelConverter._convert_sandbox_status(api_sandbox.status),
            image=domain_image_spec,
            created_at=api_sandbox.created_at,
            expires_at=expires_at,
            entrypoint=api_sandbox.entrypoint,
            metadata=metadata,
        )

    @staticmethod
    def to_paged_sandbox_infos(
        api_response: ListSandboxesResponse,
    ) -> PagedSandboxInfos:
        """
        将 API ListSandboxesResponse 转换为领域模型 PagedSandboxInfos

        此方法负责将沙箱列表响应转换为分页的领域模型。

        参数：
            api_response (ListSandboxesResponse): API 列表沙箱响应

        返回：
            PagedSandboxInfos: 领域模型分页沙箱信息
                - sandbox_infos: 沙箱信息列表
                - pagination: 分页信息
        """
        # 提取沙箱列表
        items = api_response.items if hasattr(api_response, "items") else []

        return PagedSandboxInfos(
            sandbox_infos=[SandboxModelConverter.to_sandbox_info(s) for s in items],
            pagination=SandboxModelConverter._convert_pagination_info(
                api_response.pagination
            ),
        )

    @staticmethod
    def to_sandbox_endpoint(api_endpoint: Endpoint) -> SandboxEndpoint:
        """
        将 API Endpoint 转换为领域模型 SandboxEndpoint

        此方法负责将端点信息转换为领域模型，提取端点地址和请求头。

        参数：
            api_endpoint (Endpoint): API 端点对象

        返回：
            SandboxEndpoint: 领域模型端点
                - endpoint: 端点地址
                - headers: 请求头字典
        """
        from opensandbox.api.lifecycle.types import Unset

        # 提取请求头
        headers: dict[str, str] = {}
        if not isinstance(api_endpoint.headers, Unset):
            headers = dict(api_endpoint.headers.additional_properties)

        return SandboxEndpoint(
            endpoint=api_endpoint.endpoint,
            headers=headers,
        )

    @staticmethod
    def _convert_sandbox_status(
        api_status: ApiSandboxStatus | None,
    ) -> SandboxStatus:
        """
        将 API SandboxStatus 转换为领域模型 SandboxStatus

        内部辅助方法，处理沙箱状态的转换。

        参数：
            api_status (ApiSandboxStatus | None): API 沙箱状态

        返回：
            SandboxStatus: 领域模型沙箱状态
                - state: 状态字符串
                - reason: 原因（可选）
                - message: 消息（可选）
                - last_transition_at: 最后转换时间（可选）
        """
        from opensandbox.models.sandboxes import SandboxStatus

        # 空状态处理
        if api_status is None:
            return SandboxStatus(
                state="Unknown",
                reason=None,
                message=None,
                last_transition_at=None,
            )

        # 提取原因字段
        reason: str | None = None
        if hasattr(api_status, "reason"):
            reason_val = api_status.reason
            if isinstance(reason_val, str):
                reason = reason_val

        # 提取消息字段
        message: str | None = None
        if hasattr(api_status, "message"):
            message_val = api_status.message
            if isinstance(message_val, str):
                message = message_val

        # 提取最后转换时间
        last_transition_at: datetime | None = None
        if hasattr(api_status, "last_transition_at"):
            lta_val = api_status.last_transition_at
            if isinstance(lta_val, datetime):
                last_transition_at = lta_val
            elif isinstance(lta_val, Unset) or lta_val is None:
                last_transition_at = None

        return SandboxStatus(
            state=api_status.state,
            reason=reason,
            message=message,
            last_transition_at=last_transition_at,
        )

    @staticmethod
    def _convert_pagination_info(
        api_pagination: ApiPaginationInfo | None,
    ) -> PaginationInfo:
        """
        将 API PaginationInfo 转换为领域模型 PaginationInfo

        内部辅助方法，处理分页信息的转换。

        参数：
            api_pagination (ApiPaginationInfo | None): API 分页信息

        返回：
            PaginationInfo: 领域模型分页信息
                - page: 当前页码
                - page_size: 每页数量
                - total_pages: 总页数
                - total_items: 总项目数
                - has_next_page: 是否有下一页

        默认值：
            - 如果 api_pagination 为 None，返回默认分页信息
            - page 默认为 1
            - page_size 默认为 10
        """
        # 空分页信息处理
        if api_pagination is None:
            return PaginationInfo(
                page=1,
                page_size=10,
                total_pages=0,
                total_items=0,
                has_next_page=False,
            )

        # 提取并设置默认值
        return PaginationInfo(
            page=api_pagination.page or 1,
            page_size=api_pagination.page_size or 10,
            total_pages=api_pagination.total_pages or 0,
            total_items=api_pagination.total_items or 0,
            has_next_page=api_pagination.has_next_page or False,
        )
