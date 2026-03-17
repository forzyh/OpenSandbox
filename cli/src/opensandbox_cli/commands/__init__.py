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

"""OpenSandbox CLI 命令包入口。

本模块是 commands 子包的初始化文件，将各个命令模块组织在一起。
当前包含以下命令组：
- command: 命令执行相关（run, status, logs, interrupt）
- code: 代码执行相关（run, context 管理）
- config: 配置管理相关（init, show, set）
- file: 文件操作相关（cat, write, upload, download 等）
- sandbox: 沙盒生命周期管理（create, list, get, kill 等）

各命令组在 main.py 中注册到主 CLI 入口。
"""
