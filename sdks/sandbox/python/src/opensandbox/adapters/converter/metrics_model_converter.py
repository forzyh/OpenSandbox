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
指标模型转换器模块 - Metrics Model Converter

本模块提供了 MetricsModelConverter 类，用于在 API 模型和领域模型之间转换指标数据。

设计目的：
    - 将 openapi-python-client 生成的 API 模型转换为 SDK 领域模型
    - 处理字段名称的映射和转换

核心功能：
    - to_sandbox_metrics: 将 API Metrics 转换为 SandboxMetrics

字段映射：
    - cpu_count -> cpu_count (直接映射)
    - cpu_used_pct -> cpu_used_percentage (重命名)
    - mem_total_mib -> memory_total_in_mib (重命名)
    - mem_used_mib -> memory_used_in_mib (重命名)
    - timestamp -> timestamp (直接映射)

使用示例：
    ```python
    from opensandbox.adapters.converter.metrics_model_converter import MetricsModelConverter
    from opensandbox.api.execd.models import Metrics

    api_metrics = Metrics(
        cpu_count=4,
        cpu_used_pct=25.5,
        mem_total_mib=8192,
        mem_used_mib=2048,
        timestamp=1234567890
    )

    domain_metrics = MetricsModelConverter.to_sandbox_metrics(api_metrics)
    print(f"CPU: {domain_metrics.cpu_used_percentage}%")
    print(f"Memory: {domain_metrics.memory_used_in_mib}/{domain_metrics.memory_total_in_mib} MB")
    ```
"""

from opensandbox.api.execd.models import Metrics
from opensandbox.models.sandboxes import SandboxMetrics


class MetricsModelConverter:
    """
    指标模型转换器工具类

    本类提供了静态方法，用于在 API 模型和领域模型之间转换指标数据。
    API 模型由 openapi-python-client 生成并使用 attrs，领域模型使用标准类。

    字段映射说明：
        API 字段           -> 领域模型字段
        cpu_count         -> cpu_count (直接映射)
        cpu_used_pct      -> cpu_used_percentage (重命名，更清晰)
        mem_total_mib     -> memory_total_in_mib (重命名，更清晰)
        mem_used_mib      -> memory_used_in_mib (重命名，更清晰)
        timestamp         -> timestamp (直接映射)

    使用示例：
        ```python
        from opensandbox.adapters.converter.metrics_model_converter import MetricsModelConverter

        domain_metrics = MetricsModelConverter.to_sandbox_metrics(api_metrics)
        ```
    """

    @staticmethod
    def to_sandbox_metrics(api_metrics: Metrics) -> SandboxMetrics:
        """
        将 API Metrics 转换为领域模型 SandboxMetrics

        此方法负责将 openapi-python-client 生成的 Metrics 对象转换为
        SDK 的 SandboxMetrics 对象。处理字段名称的映射。

        参数：
            api_metrics (Metrics): API 指标对象
                - cpu_count: CPU 核心数
                - cpu_used_pct: CPU 使用率百分比
                - mem_total_mib: 总内存（MiB）
                - mem_used_mib: 已用内存（MiB）
                - timestamp: 时间戳

        返回：
            SandboxMetrics: 领域模型指标对象
                - cpu_count: CPU 核心数
                - cpu_used_percentage: CPU 使用率百分比
                - memory_total_in_mib: 总内存（MiB）
                - memory_used_in_mib: 已用内存（MiB）
                - timestamp: 时间戳

        使用示例：
            ```python
            from opensandbox.api.execd.api.metric import get_metrics

            api_response = await get_metrics.asyncio_detailed(client=client)
            api_metrics = api_response.parsed
            domain_metrics = MetricsModelConverter.to_sandbox_metrics(api_metrics)

            print(f"CPU: {domain_metrics.cpu_used_percentage}%")
            print(f"Memory: {domain_metrics.memory_used_in_mib}MB")
            ```
        """
        return SandboxMetrics(
            cpu_count=api_metrics.cpu_count,              # CPU 核心数
            cpu_used_percentage=api_metrics.cpu_used_pct, # CPU 使用率百分比
            memory_total_in_mib=api_metrics.mem_total_mib,  # 总内存（MiB）
            memory_used_in_mib=api_metrics.mem_used_mib,    # 已用内存（MiB）
            timestamp=api_metrics.timestamp,              # 时间戳
        )
