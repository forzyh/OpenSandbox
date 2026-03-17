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

"""CLI 命令功能测试模块。

本模块测试 CLI 命令的实际功能，使用模拟对象避免真实的 SDK/HTTP 调用。

测试策略：
1. 使用 mock 对象模拟 ClientContext 和 SDK 调用
2. 使用 patch 装饰器替换实际的配置解析和客户端创建
3. 验证命令调用了正确的 SDK 方法
4. 验证输出内容符合预期

测试覆盖：
- config 命令（init, show, set）
- sandbox 命令（list, kill, pause, resume）
- file 命令（cat, write, rm, mv, mkdir, rmdir）
- command 命令（run, interrupt）
- exec 快捷命令
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from opensandbox_cli.main import cli
from opensandbox_cli.output import OutputFormatter


@pytest.fixture()
def runner() -> CliRunner:
    """创建 Click 测试运行器。

    返回：
        CliRunner: Click 命令行测试运行器
    """
    return CliRunner()


def _build_mock_client_context(
    *,
    manager: MagicMock | None = None,
    sandbox: MagicMock | None = None,
    output_format: str = "json",
) -> MagicMock:
    """构建模拟的 ClientContext 对象。

    创建用于测试的模拟上下文，配置为返回指定的模拟管理器和沙盒。

    参数：
        manager: 模拟的沙盒管理器（可选）
        sandbox: 模拟的沙盒对象（可选）
        output_format: 输出格式（默认 json，便于测试断言）

    返回：
        MagicMock: 模拟的 ClientContext 实例
    """
    ctx = MagicMock()
    ctx.resolved_config = {
        "api_key": "test-key",
        "domain": "localhost:8080",
        "protocol": "http",
        "request_timeout": 30,
        "output_format": output_format,
        "color": False,
        "default_image": None,
        "default_timeout": None,
    }
    ctx.output = OutputFormatter(output_format, color=False)
    ctx.get_manager.return_value = manager or MagicMock()
    ctx.connect_sandbox.return_value = sandbox or MagicMock()
    ctx.connection_config = MagicMock()
    ctx.close = MagicMock()
    return ctx


def _invoke(
    runner: CliRunner,
    args: list[str],
    *,
    manager: MagicMock | None = None,
    sandbox: MagicMock | None = None,
    output_format: str = "json",
) -> object:
    """使用模拟的 ClientContext 调用 CLI 命令。

    该函数设置必要的 patch，使 CLI 命令使用模拟对象而非真实的 SDK。

    参数：
        runner: Click 测试运行器
        args: 命令行参数列表
        manager: 模拟的沙盒管理器
        sandbox: 模拟的沙盒对象
        output_format: 输出格式

    返回：
        Result: Click 命令执行结果
    """
    mock_ctx = _build_mock_client_context(
        manager=manager, sandbox=sandbox, output_format=output_format
    )

    with patch("opensandbox_cli.main.resolve_config") as mock_resolve, \
         patch("opensandbox_cli.main.ClientContext", return_value=mock_ctx), \
         patch("opensandbox_cli.main.OutputFormatter", side_effect=lambda fmt, **kw: OutputFormatter(fmt, **kw)):
        mock_resolve.return_value = mock_ctx.resolved_config
        result = runner.invoke(cli, args, catch_exceptions=False)
    return result


# ---------------------------------------------------------------------------
# config 命令测试（不需要 SDK 模拟）
# ---------------------------------------------------------------------------


class TestConfigInit:
    """config init 命令测试类。

    测试配置文件初始化功能。
    """

    def test_init_creates_file(self, runner: CliRunner, tmp_path: Path) -> None:
        """测试创建配置文件。

        验证 config init 命令能在指定路径创建配置文件。
        """
        cfg_path = tmp_path / "config.toml"
        result = runner.invoke(cli, ["config", "init", "--path", str(cfg_path)])
        assert result.exit_code == 0
        assert "Config file created" in result.output

    def test_init_refuses_overwrite(self, runner: CliRunner, tmp_path: Path) -> None:
        """测试拒绝覆盖已存在的文件。

        验证当文件已存在时，init 命令会拒绝覆盖。
        """
        cfg_path = tmp_path / "config.toml"
        cfg_path.write_text("existing")
        result = runner.invoke(cli, ["config", "init", "--path", str(cfg_path)])
        assert "already exists" in result.output

    def test_init_force_overwrites(self, runner: CliRunner, tmp_path: Path) -> None:
        """测试强制覆盖已存在的文件。

        验证使用 --force 标志可以覆盖已存在的文件。
        """
        cfg_path = tmp_path / "config.toml"
        cfg_path.write_text("old")
        result = runner.invoke(
            cli, ["config", "init", "--path", str(cfg_path), "--force"]
        )
        assert result.exit_code == 0
        assert "Config file created" in result.output


class TestConfigShow:
    """config show 命令测试类。

    测试配置显示功能。
    """

    def test_show_json_output(self, runner: CliRunner) -> None:
        """测试 JSON 格式输出。

        验证 -o json 选项能输出 JSON 格式的配置。
        """
        result = runner.invoke(cli, ["-o", "json", "config", "show"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "api_key" in data

    def test_show_table_output(self, runner: CliRunner) -> None:
        """测试表格格式输出。

        验证默认情况下输出表格格式的配置。
        """
        result = runner.invoke(cli, ["config", "show"])
        assert result.exit_code == 0
        assert "api_key" in result.output


class TestConfigSet:
    """config set 命令测试类。

    测试配置项设置功能。
    """

    def test_set_updates_existing_field(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """测试更新已存在的配置项。

        验证 set 命令能更新配置文件中的字段。
        """
        cfg_path = tmp_path / "config.toml"
        runner.invoke(cli, ["config", "init", "--path", str(cfg_path)])
        result = runner.invoke(
            cli,
            ["config", "set", "connection.domain", "new.host", "--path", str(cfg_path)],
        )
        assert result.exit_code == 0
        assert "Set connection.domain = new.host" in result.output

    def test_set_rejects_flat_key(self, runner: CliRunner, tmp_path: Path) -> None:
        """测试拒绝扁平的键名格式。

        验证 set 命令要求键名必须是 section.field 格式。
        """
        cfg_path = tmp_path / "config.toml"
        cfg_path.write_text("[connection]\n")
        result = runner.invoke(
            cli, ["config", "set", "flat_key", "value", "--path", str(cfg_path)]
        )
        assert "section.field" in result.output


# ---------------------------------------------------------------------------
# sandbox 命令测试
# ---------------------------------------------------------------------------


class TestSandboxList:
    """sandbox list 命令测试类。

    测试沙盒列表功能。
    """

    def test_list_invokes_manager(self, runner: CliRunner) -> None:
        """测试调用管理器的 list 方法。

        验证 list 命令正确调用了 SDK 的 list_sandbox_infos 方法。
        """
        mock_mgr = MagicMock()
        mock_result = MagicMock()
        mock_result.sandbox_infos = []
        mock_mgr.list_sandbox_infos.return_value = mock_result

        result = _invoke(runner, ["-o", "json", "sandbox", "list"], manager=mock_mgr)
        assert result.exit_code == 0
        mock_mgr.list_sandbox_infos.assert_called_once()


class TestSandboxKill:
    """sandbox kill 命令测试类。

    测试沙盒终止功能。
    """

    def test_kill_multiple(self, runner: CliRunner) -> None:
        """测试终止多个沙盒。

        验证 kill 命令能正确终止多个沙盒。
        """
        mock_mgr = MagicMock()
        result = _invoke(runner, ["sandbox", "kill", "id1", "id2"], manager=mock_mgr)
        assert result.exit_code == 0
        assert mock_mgr.kill_sandbox.call_count == 2
        assert "Killed: id1" in result.output
        assert "Killed: id2" in result.output


class TestSandboxPause:
    """sandbox pause 命令测试类。

    测试沙盒暂停功能。
    """

    def test_pause_calls_manager(self, runner: CliRunner) -> None:
        """测试调用管理器的 pause 方法。

        验证 pause 命令正确调用了 SDK 的 pause_sandbox 方法。
        """
        mock_mgr = MagicMock()
        result = _invoke(
            runner, ["sandbox", "pause", "sb-123"], manager=mock_mgr
        )
        assert result.exit_code == 0
        mock_mgr.pause_sandbox.assert_called_once_with("sb-123")
        assert "Paused: sb-123" in result.output


class TestSandboxResume:
    """sandbox resume 命令测试类。

    测试沙盒恢复功能。
    """

    def test_resume_calls_manager(self, runner: CliRunner) -> None:
        """测试调用管理器的 resume 方法。

        验证 resume 命令正确调用了 SDK 的 resume_sandbox 方法。
        """
        mock_mgr = MagicMock()
        result = _invoke(
            runner, ["sandbox", "resume", "sb-123"], manager=mock_mgr
        )
        assert result.exit_code == 0
        mock_mgr.resume_sandbox.assert_called_once_with("sb-123")
        assert "Resumed: sb-123" in result.output


# ---------------------------------------------------------------------------
# file 命令测试
# ---------------------------------------------------------------------------


class TestFileCat:
    """file cat 命令测试类。

    测试文件读取功能。
    """

    def test_cat_outputs_content(self, runner: CliRunner) -> None:
        """测试输出文件内容。

        验证 cat 命令能正确读取并输出文件内容。
        """
        mock_sb = MagicMock()
        mock_sb.files.read_file.return_value = "hello world"
        result = _invoke(
            runner, ["file", "cat", "sb-1", "/etc/hostname"], sandbox=mock_sb
        )
        assert result.exit_code == 0
        assert "hello world" in result.output
        mock_sb.files.read_file.assert_called_once_with(
            "/etc/hostname", encoding="utf-8"
        )


class TestFileWrite:
    """file write 命令测试类。

    测试文件写入功能。
    """

    def test_write_with_content_flag(self, runner: CliRunner) -> None:
        """测试使用 -c 选项写入内容。

        验证 write 命令能正确写入指定内容。
        """
        mock_sb = MagicMock()
        result = _invoke(
            runner,
            ["file", "write", "sb-1", "/tmp/test.txt", "-c", "content here"],
            sandbox=mock_sb,
        )
        assert result.exit_code == 0
        assert "Written" in result.output
        mock_sb.files.write_file.assert_called_once()


class TestFileRm:
    """file rm 命令测试类。

    测试文件删除功能。
    """

    def test_rm_deletes_files(self, runner: CliRunner) -> None:
        """测试删除文件。

        验证 rm 命令能正确调用 SDK 删除文件。
        """
        mock_sb = MagicMock()
        result = _invoke(
            runner, ["file", "rm", "sb-1", "/tmp/a", "/tmp/b"], sandbox=mock_sb
        )
        assert result.exit_code == 0
        mock_sb.files.delete_files.assert_called_once_with(["/tmp/a", "/tmp/b"])


class TestFileMv:
    """file mv 命令测试类。

    测试文件移动功能。
    """

    def test_mv_moves_file(self, runner: CliRunner) -> None:
        """测试移动文件。

        验证 mv 命令能正确移动文件。
        """
        mock_sb = MagicMock()
        result = _invoke(
            runner, ["file", "mv", "sb-1", "/tmp/old", "/tmp/new"], sandbox=mock_sb
        )
        assert result.exit_code == 0
        assert "Moved: /tmp/old -> /tmp/new" in result.output


class TestFileMkdir:
    """file mkdir 命令测试类。

    测试目录创建功能。
    """

    def test_mkdir_creates_dirs(self, runner: CliRunner) -> None:
        """测试创建目录。

        验证 mkdir 命令能正确创建多个目录。
        """
        mock_sb = MagicMock()
        result = _invoke(
            runner,
            ["file", "mkdir", "sb-1", "/tmp/dir1", "/tmp/dir2"],
            sandbox=mock_sb,
        )
        assert result.exit_code == 0
        assert "Created: /tmp/dir1" in result.output
        assert "Created: /tmp/dir2" in result.output


class TestFileRmdir:
    """file rmdir 命令测试类。

    测试目录删除功能。
    """

    def test_rmdir_removes_dirs(self, runner: CliRunner) -> None:
        """测试删除目录。

        验证 rmdir 命令能正确删除目录。
        """
        mock_sb = MagicMock()
        result = _invoke(
            runner, ["file", "rmdir", "sb-1", "/workspace/old"], sandbox=mock_sb
        )
        assert result.exit_code == 0
        assert "Removed: /workspace/old" in result.output


# ---------------------------------------------------------------------------
# command 命令测试
# ---------------------------------------------------------------------------


class TestCommandRun:
    """command run 命令测试类。

    测试命令执行功能。
    """

    def test_background_run(self, runner: CliRunner) -> None:
        """测试后台运行命令。

        验证 -d 选项能正确执行后台命令并返回 execution_id。
        """
        mock_sb = MagicMock()
        mock_execution = MagicMock()
        mock_execution.id = "exec-123"
        mock_sb.commands.run.return_value = mock_execution

        result = _invoke(
            runner,
            ["-o", "json", "command", "run", "sb-1", "-d", "echo", "hello"],
            sandbox=mock_sb,
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["execution_id"] == "exec-123"
        assert data["background"] is True


class TestExecShortcut:
    """exec 快捷命令测试类。

    测试 exec 快捷命令功能。
    """

    def test_exec_passes_to_run(self, runner: CliRunner) -> None:
        """测试 exec 命令调用 run 逻辑。

        验证 exec 命令正确调用了 SDK 的 commands.run 方法。
        """
        mock_sb = MagicMock()
        mock_execution = MagicMock()
        mock_execution.id = "exec-456"
        mock_sb.commands.run.return_value = mock_execution

        result = _invoke(
            runner,
            ["-o", "json", "exec", "sb-1", "-d", "--", "ls", "-la"],
            sandbox=mock_sb,
        )
        assert result.exit_code == 0
        mock_sb.commands.run.assert_called_once()


class TestCommandInterrupt:
    """command interrupt 命令测试类。

    测试命令中断功能。
    """

    def test_interrupt_calls_sdk(self, runner: CliRunner) -> None:
        """测试调用 SDK 的中断方法。

        验证 interrupt 命令正确调用了 SDK 的 interrupt 方法。
        """
        mock_sb = MagicMock()
        result = _invoke(
            runner, ["command", "interrupt", "sb-1", "exec-789"], sandbox=mock_sb
        )
        assert result.exit_code == 0
        mock_sb.commands.interrupt.assert_called_once_with("exec-789")
        assert "Interrupted: exec-789" in result.output
