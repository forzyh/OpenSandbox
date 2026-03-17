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

"""共享测试夹具（fixtures）模块。

本模块定义了 pytest 测试中可复用的夹具，包括：
1. runner: Click 命令行测试运行器
2. mock_manager: 模拟的沙盒管理器
3. mock_sandbox: 模拟的沙盒对象
4. mock_client_context: 模拟的 CLI 上下文对象

这些夹具用于避免真实的 SDK/HTTP 调用，提高测试速度和可靠性。

使用示例：
    def test_my_command(runner, mock_client_context):
        result = runner.invoke(cli, ["my-command"])
        assert result.exit_code == 0
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

from opensandbox_cli.output import OutputFormatter


@pytest.fixture()
def runner() -> CliRunner:
    """创建 Click 命令行测试运行器。

    CliRunner 用于模拟命令行调用，捕获输出和退出码。

    返回：
        CliRunner: Click 测试运行器实例

    使用示例：
        def test_help(runner):
            result = runner.invoke(cli, ["--help"])
            assert result.exit_code == 0
    """
    return CliRunner()


@pytest.fixture()
def mock_manager() -> MagicMock:
    """创建模拟的沙盒管理器。

    返回：
        MagicMock: 模拟的 SandboxManagerSync 实例

    使用示例：
        def test_list(mock_manager):
            mock_manager.list_sandbox_infos.return_value = [...]
            # 执行测试
    """
    return MagicMock()


@pytest.fixture()
def mock_sandbox() -> MagicMock:
    """创建模拟的沙盒对象。

    返回：
        MagicMock: 模拟的 SandboxSync 实例

    使用示例：
        def test_run(mock_sandbox):
            mock_sandbox.commands.run.return_value = ...
            # 执行测试
    """
    return MagicMock()


@pytest.fixture()
def mock_client_context(
    mock_manager: MagicMock, mock_sandbox: MagicMock
) -> MagicMock:
    """创建模拟的 CLI 上下文对象。

    该夹具创建一个模拟的 ClientContext，避免真实的 SDK/HTTP 调用。
    配置为 JSON 输出格式，便于测试中断言输出内容。

    参数：
        mock_manager: 模拟的沙盒管理器
        mock_sandbox: 模拟的沙盒对象

    返回：
        MagicMock: 模拟的 ClientContext 实例

    使用示例：
        def test_command(mock_client_context):
            # mock_client_context.get_manager() 返回 mock_manager
            # mock_client_context.connect_sandbox() 返回 mock_sandbox
            pass
    """
    ctx = MagicMock()
    ctx.resolved_config = {
        "api_key": "test-key",
        "domain": "localhost:8080",
        "protocol": "http",
        "request_timeout": 30,
        "output_format": "json",
        "color": False,
        "default_image": None,
        "default_timeout": None,
    }
    ctx.output = OutputFormatter("json", color=False)
    ctx.get_manager.return_value = mock_manager
    ctx.connect_sandbox.return_value = mock_sandbox
    ctx.connection_config = MagicMock()
    ctx.close = MagicMock()
    return ctx
