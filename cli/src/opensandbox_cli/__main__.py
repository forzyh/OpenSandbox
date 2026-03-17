# Copyright 2026 Alibaba Group Holding Ltd.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or preferred to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""OpenSandbox CLI 版本定义模块。

本模块负责获取和定义 CLI 工具的版本号：
1. 优先从已安装的包元数据中读取版本号（使用 importlib.metadata）
2. 如果无法获取（如开发模式），则返回默认的开发版本号 "0.0.0-dev"

该版本号用于：
- CLI --version 命令显示
- 调试和日志记录
- 版本兼容性检查
"""

try:
    from importlib.metadata import version

    # 从已安装的包元数据中获取版本号
    __version__ = version("opensandbox-cli")
except Exception:
    # 开发模式或无法获取版本号时的默认值
    __version__ = "0.0.0-dev"
