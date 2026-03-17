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
Kubernetes Pod 规格的卷辅助工具模块。

本模块提供了 apply_volumes_to_pod_spec 函数，用于将用户指定的卷配置
转换为 Kubernetes 的 volume 和 volumeMount 定义，并添加到 Pod 规格中。

支持的卷后端类型：
- pvc：持久卷声明（PersistentVolumeClaim），适用于持久化存储
- host：主机路径（hostPath），适用于节点本地存储（不推荐用于生产）

使用示例：
    >>> pod_spec = {"containers": [{"name": "main", "image": "..."}]}
    >>> volumes = [Volume(name="data", mount_path="/data", pvc=PVCBackend(claim_name="my-pvc"))]
    >>> apply_volumes_to_pod_spec(pod_spec, volumes)
    >>> # pod_spec 现在包含了 volume 和 volumeMount 定义
"""

import logging
from typing import Any, Dict, List

from src.api.schema import Volume

logger = logging.getLogger(__name__)


def apply_volumes_to_pod_spec(
    pod_spec: Dict[str, Any],
    volumes: List[Volume],
) -> None:
    """
    将用户指定的卷应用到 Kubernetes Pod 规格。

    本函数将 Volume API 对象转换为 Kubernetes 的 volume 和 volumeMount
    定义，并原地修改 Pod 规格。

    目前支持的后端类型：
    - pvc：映射到 Kubernetes PersistentVolumeClaim
    - host：映射到 Kubernetes hostPath 卷

    Args:
        pod_spec: 要修改的 Pod 规格字典（原地修改）
        volumes: Volume API 对象列表

    Raises:
        ValueError: 如果指定了不支持的卷后端类型
        ValueError: 如果卷名称与内部卷冲突

    处理逻辑：
        1. 获取主容器（第一个容器）
        2. 收集现有的卷名称，防止与内部卷冲突
        3. 对每个卷：
           - 检查名称冲突
           - 根据后端类型创建 volume 定义
           - 创建对应的 volumeMount
        4. 更新 Pod 规格

    示例 Pod 规格修改前后：
        修改前：
        {
            "containers": [{"name": "main", "image": "nginx"}]
        }

        修改后（添加 PVC 卷）：
        {
            "containers": [{
                "name": "main",
                "image": "nginx",
                "volumeMounts": [{"name": "data", "mountPath": "/data", "readOnly": false}]
            }],
            "volumes": [{
                "name": "data",
                "persistentVolumeClaim": {"claimName": "my-pvc"}
            }]
        }
    """
    containers = pod_spec.get("containers", [])
    if not containers:
        logger.warning("Pod 规格中没有容器，跳过卷挂载")
        return

    main_container = containers[0]
    mounts = main_container.get("volumeMounts", [])
    pod_volumes = pod_spec.get("volumes", [])

    # 收集现有卷名称，防止与内部卷冲突
    existing_volume_names = {v.get("name") for v in pod_volumes if isinstance(v, dict)}

    for vol in volumes:
        vol_name = vol.name

        # 检查是否与内部卷冲突
        if vol_name in existing_volume_names:
            raise ValueError(
                f"卷名称 '{vol_name}' 与内部卷冲突。"
                "请使用不同的卷名称。"
            )

        if vol.pvc is not None:
            # PVC 后端：映射到 PersistentVolumeClaim
            pvc_claim_name = vol.pvc.claim_name

            pod_volumes.append({
                "name": vol_name,
                "persistentVolumeClaim": {
                    "claimName": pvc_claim_name,
                },
            })

            mount = {
                "name": vol_name,
                "mountPath": vol.mount_path,
                "readOnly": vol.read_only,
            }
            if vol.sub_path:
                mount["subPath"] = vol.sub_path
            mounts.append(mount)

            logger.info(
                "为 sandbox 添加 PVC 卷 '%s'（声明：%s），挂载到 '%s'",
                vol_name,
                pvc_claim_name,
                vol.mount_path,
            )
        elif vol.host is not None:
            # Host 后端：映射到 hostPath 卷
            # 注意：hostPath 是节点本地的，不推荐用于生产环境
            host_path = vol.host.path

            pod_volumes.append({
                "name": vol_name,
                "hostPath": {
                    "path": host_path,
                    "type": "DirectoryOrCreate",  # 如果目录不存在则创建
                },
            })

            mount = {
                "name": vol_name,
                "mountPath": vol.mount_path,
                "readOnly": vol.read_only,
            }
            if vol.sub_path:
                mount["subPath"] = vol.sub_path
            mounts.append(mount)

            logger.info(
                "为 sandbox 添加 hostPath 卷 '%s'（路径：%s），挂载到 '%s'",
                vol_name,
                host_path,
                vol.mount_path,
            )
        else:
            raise ValueError(
                f"卷 '{vol_name}' 没有指定支持的后端。"
                "支持的后端：pvc, host"
            )

    # 更新 Pod 规格
    pod_spec["volumes"] = pod_volumes
    main_container["volumeMounts"] = mounts
