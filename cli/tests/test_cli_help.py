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

"""CLI 命令帮助信息测试模块。

本模块测试所有 CLI 命令是否正确注册，以及 --help 选项能否正常退出。
确保 CLI 命令结构完整，帮助信息可正常显示。

测试覆盖：
1. 根命令（--help, --version）
2. sandbox 子命令组及其子命令
3. command 子命令组及其子命令
4. exec 快捷命令
5. file 子命令组及其子命令
6. code 子命令组及其子命令
7. config 子命令组及其子命令
"""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from opensandbox_cli.main import cli


@pytest.fixture()
def runner() -> CliRunner:
    """创建 Click 测试运行器。

    返回：
        CliRunner: Click 命令行测试运行器
    """
    return CliRunner()


# ---------------------------------------------------------------------------
# 根命令测试
# ---------------------------------------------------------------------------


class TestRootCLI:
    """根 CLI 命令测试类。

    测试根命令的基本功能，包括帮助信息、版本号和子命令列表。
    """

    def test_help(self, runner: CliRunner) -> None:
        """测试 --help 选项。

        验证帮助信息能正常显示且包含 CLI 名称。
        """
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "OpenSandbox CLI" in result.output

    def test_version(self, runner: CliRunner) -> None:
        """测试 --version 选项。

        验证版本号能正常显示。
        """
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert "opensandbox" in result.output

    def test_root_lists_commands(self, runner: CliRunner) -> None:
        """测试根命令列出所有子命令。

        验证所有子命令组都正确注册。
        """
        result = runner.invoke(cli, ["--help"])
        for cmd in ("sandbox", "command", "exec", "file", "code", "config"):
            assert cmd in result.output


# ---------------------------------------------------------------------------
# sandbox 子命令测试
# ---------------------------------------------------------------------------


class TestSandboxHelp:
    """sandbox 命令组帮助信息测试类。

    测试 sandbox 命令组及其所有子命令的帮助信息。
    """

    def test_sandbox_help(self, runner: CliRunner) -> None:
        """测试 sandbox --help。

        验证 sandbox 命令组显示所有子命令。
        """
        result = runner.invoke(cli, ["sandbox", "--help"])
        assert result.exit_code == 0
        for subcmd in (
            "create",
            "list",
            "get",
            "kill",
            "pause",
            "resume",
            "renew",
            "endpoint",
            "health",
            "metrics",
        ):
            assert subcmd in result.output

    @pytest.mark.parametrize(
        "subcmd",
        [
            "create",
            "list",
            "get",
            "kill",
            "pause",
            "resume",
            "renew",
            "endpoint",
            "health",
            "metrics",
        ],
    )
    def test_sandbox_subcommand_help(
        self, runner: CliRunner, subcmd: str
    ) -> None:
        """测试 sandbox 子命令的帮助信息。

        参数化测试每个子命令的 --help 选项。

        参数：
            subcmd: 子命令名称
        """
        result = runner.invoke(cli, ["sandbox", subcmd, "--help"])
        assert result.exit_code == 0
        assert subcmd in result.output.lower() or "usage" in result.output.lower()


# ---------------------------------------------------------------------------
# command 子命令测试
# ---------------------------------------------------------------------------


class TestCommandHelp:
    """command 命令组帮助信息测试类。

    测试 command 命令组及其所有子命令的帮助信息。
    """

    def test_command_help(self, runner: CliRunner) -> None:
        """测试 command --help。

        验证 command 命令组显示所有子命令。
        """
        result = runner.invoke(cli, ["command", "--help"])
        assert result.exit_code == 0
        for subcmd in ("run", "status", "logs", "interrupt"):
            assert subcmd in result.output

    @pytest.mark.parametrize("subcmd", ["run", "status", "logs", "interrupt"])
    def test_command_subcommand_help(
        self, runner: CliRunner, subcmd: str
    ) -> None:
        """测试 command 子命令的帮助信息。

        参数化测试每个子命令的 --help 选项。

        参数：
            subcmd: 子命令名称
        """
        result = runner.invoke(cli, ["command", subcmd, "--help"])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# exec 快捷命令测试
# ---------------------------------------------------------------------------


class TestExecHelp:
    """exec 快捷命令帮助信息测试类。

    测试 exec 命令（command run 的快捷方式）的帮助信息。
    """

    def test_exec_help(self, runner: CliRunner) -> None:
        """测试 exec --help。

        验证 exec 命令帮助信息显示其为快捷方式。
        """
        result = runner.invoke(cli, ["exec", "--help"])
        assert result.exit_code == 0
        assert "shortcut" in result.output.lower() or "command" in result.output.lower()


# ---------------------------------------------------------------------------
# file 子命令测试
# ---------------------------------------------------------------------------


class TestFileHelp:
    """file 命令组帮助信息测试类。

    测试 file 命令组及其所有子命令的帮助信息。
    """

    def test_file_help(self, runner: CliRunner) -> None:
        """测试 file --help。

        验证 file 命令组显示所有子命令。
        """
        result = runner.invoke(cli, ["file", "--help"])
        assert result.exit_code == 0
        for subcmd in (
            "cat",
            "write",
            "upload",
            "download",
            "rm",
            "mv",
            "mkdir",
            "rmdir",
            "search",
            "info",
            "chmod",
            "replace",
        ):
            assert subcmd in result.output

    @pytest.mark.parametrize(
        "subcmd",
        [
            "cat",
            "write",
            "upload",
            "download",
            "rm",
            "mv",
            "mkdir",
            "rmdir",
            "search",
            "info",
            "chmod",
            "replace",
        ],
    )
    def test_file_subcommand_help(
        self, runner: CliRunner, subcmd: str
    ) -> None:
        """测试 file 子命令的帮助信息。

        参数化测试每个子命令的 --help 选项。

        参数：
            subcmd: 子命令名称
        """
        result = runner.invoke(cli, ["file", subcmd, "--help"])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# code 子命令测试
# ---------------------------------------------------------------------------


class TestCodeHelp:
    """code 命令组帮助信息测试类。

    测试 code 命令组及其子命令的帮助信息。
    """

    def test_code_help(self, runner: CliRunner) -> None:
        """测试 code --help。

        验证 code 命令组显示所有子命令。
        """
        result = runner.invoke(cli, ["code", "--help"])
        assert result.exit_code == 0
        for subcmd in ("run", "context", "interrupt"):
            assert subcmd in result.output

    def test_code_context_help(self, runner: CliRunner) -> None:
        """测试 code context --help。

        验证 context 子命令显示其子命令。
        """
        result = runner.invoke(cli, ["code", "context", "--help"])
        assert result.exit_code == 0
        for subcmd in ("create", "list", "delete", "delete-all"):
            assert subcmd in result.output


# ---------------------------------------------------------------------------
# config 子命令测试
# ---------------------------------------------------------------------------


class TestConfigHelp:
    """config 命令组帮助信息测试类。

    测试 config 命令组及其所有子命令的帮助信息。
    """

    def test_config_help(self, runner: CliRunner) -> None:
        """测试 config --help。

        验证 config 命令组显示所有子命令。
        """
        result = runner.invoke(cli, ["config", "--help"])
        assert result.exit_code == 0
        for subcmd in ("init", "show", "set"):
            assert subcmd in result.output

    @pytest.mark.parametrize("subcmd", ["init", "show", "set"])
    def test_config_subcommand_help(
        self, runner: CliRunner, subcmd: str
    ) -> None:
        """测试 config 子命令的帮助信息。

        参数化测试每个子命令的 --help 选项。

        参数：
            subcmd: 子命令名称
        """
        result = runner.invoke(cli, ["config", subcmd, "--help"])
        assert result.exit_code == 0
