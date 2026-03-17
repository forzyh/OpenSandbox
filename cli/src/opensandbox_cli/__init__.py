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

"""OpenSandbox CLI 工具包入口模块。

本模块是 opensandbox_cli 包的入口点，主要功能包括：
1. 导入主 CLI 入口函数 cli
2. 支持通过 `python -m opensandbox_cli` 方式运行 CLI 工具

使用示例：
    # 直接运行
    from opensandbox_cli import cli
    cli()

    # 或通过模块方式运行
    python -m opensandbox_cli --help
"""

from opensandbox_cli.main import cli

if __name__ == "__main__":
    cli()
