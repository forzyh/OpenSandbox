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

"""命令执行相关命令的实现模块。

本模块实现了在沙盒中执行命令的相关 CLI 命令，包括：
1. command run / exec: 在沙盒中运行命令（支持前台/后台模式）
2. command status: 获取命令执行状态
3. command logs: 获取后台命令的日志输出
4. command interrupt: 中断正在运行的命令

主要特点：
- 前台命令：实时流式输出 stdout/stderr 到终端
- 后台命令：返回 execution_id，可后续查询状态和日志
- 支持设置工作目录、超时时间等选项
"""

from __future__ import annotations

import shlex
import sys
from datetime import timedelta

import click

from opensandbox.models.execd import OutputMessage, RunCommandOpts
from opensandbox.models.execd_sync import ExecutionHandlersSync

from opensandbox_cli.client import ClientContext
from opensandbox_cli.utils import DURATION, handle_errors


@click.group("command", invoke_without_command=True)
@click.pass_context
def command_group(ctx: click.Context) -> None:
    """命令执行命令组入口。

    当没有指定子命令时，显示帮助信息。

    使用示例：
        osb command --help          # 查看帮助
        osb command run sb-1 ls -la # 运行命令
        osb command status sb-1 exec-123  # 查看状态
    """
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


# ---- run ------------------------------------------------------------------

def _run_command(
    obj: ClientContext,
    sandbox_id: str,
    command: tuple[str, ...],
    background: bool,
    workdir: str | None,
    timeout: timedelta | None,
) -> None:
    """运行命令的共享实现函数。

    该函数被 `command run` 和顶层的 `exec` 命令共享，处理命令执行的共同逻辑。

    参数：
        obj: CLI 上下文对象，包含配置和输出工具
        sandbox_id: 目标沙盒 ID
        command: 要执行的命令及其参数元组
        background: 是否在后台运行
        workdir: 工作目录路径
        timeout: 命令超时时间

    后台模式：
        返回 execution_id，不等待命令完成，适合长时间运行的任务

    前台模式：
        实时流式输出 stdout/stderr，命令结束后返回退出码
    """
    # 将命令参数转义并拼接为字符串
    cmd_str = " ".join(shlex.quote(arg) for arg in command)
    sandbox = obj.connect_sandbox(sandbox_id)

    try:
        opts = RunCommandOpts(
            background=background,
            working_directory=workdir,
            timeout=timeout,
        )

        if background:
            # 后台模式：立即返回 execution_id
            execution = sandbox.commands.run(cmd_str, opts=opts)
            obj.output.print_dict(
                {
                    "execution_id": execution.id,
                    "sandbox_id": sandbox_id,
                    "background": True,
                },
                title="Background Command",
            )
            return

        # 前台模式：实时流式输出
        def on_stdout(msg: OutputMessage) -> None:
            sys.stdout.write(msg.text)
            sys.stdout.flush()

        def on_stderr(msg: OutputMessage) -> None:
            sys.stderr.write(msg.text)
            sys.stderr.flush()

        handlers = ExecutionHandlersSync(on_stdout=on_stdout, on_stderr=on_stderr)
        execution = sandbox.commands.run(cmd_str, opts=opts, handlers=handlers)

        if execution.error:
            click.secho(
                f"\nExecution error: {execution.error.name}: {execution.error.value}",
                fg="red",
                err=True,
            )
            sys.exit(1)
    finally:
        sandbox.close()


@click.command("run")
@click.argument("sandbox_id")
@click.argument("command", nargs=-1, required=True)
@click.option("-d", "--background", is_flag=True, default=False, help="在后台运行命令。")
@click.option("-w", "--workdir", default=None, help="工作目录路径。")
@click.option("-t", "--timeout", type=DURATION, default=None, help="命令超时时间（如 30s, 5m）。")
@click.pass_obj
@handle_errors
def command_run(
    obj: ClientContext,
    sandbox_id: str,
    command: tuple[str, ...],
    background: bool,
    workdir: str | None,
    timeout: timedelta | None,
) -> None:
    """在沙盒中运行命令。

    支持前台和后台两种模式：
    - 前台模式（默认）：实时输出命令结果，等待命令完成后返回
    - 后台模式（-d）：立即返回 execution_id，可在后续查询状态和日志

    参数：
        sandbox_id: 目标沙盒 ID
        command: 要执行的命令及参数

    使用示例：
        # 前台运行
        osb command run sb-1 ls -la

        # 后台运行
        osb command run sb-1 -d sleep 300
        osb command status sb-1 <execution_id>

        # 指定工作目录和超时
        osb command run sb-1 -w /app -t 60s ./run.sh
    """
    _run_command(obj, sandbox_id, command, background, workdir, timeout)


# ---- status ---------------------------------------------------------------

@click.group("status")
@click.argument("sandbox_id")
@click.argument("execution_id")
@click.pass_obj
@handle_errors
def command_status(obj: ClientContext, sandbox_id: str, execution_id: str) -> None:
    """获取命令执行状态。

    查询后台运行命令的当前状态（如 running, completed, failed 等）。

    参数：
        sandbox_id: 沙盒 ID
        execution_id: 命令执行 ID

    使用示例：
        osb command status sb-1 exec-123
    """
    sandbox = obj.connect_sandbox(sandbox_id)
    try:
        status = sandbox.commands.get_command_status(execution_id)
        obj.output.print_model(status, title="Command Status")
    finally:
        sandbox.close()


# ---- logs -----------------------------------------------------------------

@click.command("logs")
@click.argument("sandbox_id")
@click.argument("execution_id")
@click.option("--cursor", type=int, default=None, help="增量读取的游标位置。")
@click.pass_obj
@handle_errors
def command_logs(
    obj: ClientContext, sandbox_id: str, execution_id: str, cursor: int | None
) -> None:
    """获取后台命令的日志输出。

    读取后台运行命令的 stdout/stderr 日志。支持使用 cursor 参数进行增量读取。

    参数：
        sandbox_id: 沙盒 ID
        execution_id: 命令执行 ID
        cursor: 日志游标，用于增量读取（可选）

    使用示例：
        # 获取全部日志
        osb command logs sb-1 exec-123

        # 增量读取（从上次的 cursor 位置开始）
        osb command logs sb-1 exec-123 --cursor 1024
    """
    sandbox = obj.connect_sandbox(sandbox_id)
    try:
        logs = sandbox.commands.get_background_command_logs(execution_id, cursor=cursor)
        if obj.output.fmt in ("json", "yaml"):
            obj.output.print_model(logs, title="Command Logs")
        else:
            click.echo(logs.content)
    finally:
        sandbox.close()


# ---- interrupt ------------------------------------------------------------

@click.command("interrupt")
@click.argument("sandbox_id")
@click.argument("execution_id")
@click.pass_obj
@handle_errors
def command_interrupt(obj: ClientContext, sandbox_id: str, execution_id: str) -> None:
    """中断正在运行的命令。

    向指定 execution_id 的命令发送中断信号（SIGINT），停止其执行。

    参数：
        sandbox_id: 沙盒 ID
        execution_id: 要中断的命令执行 ID

    使用示例：
        osb command interrupt sb-1 exec-123
    """
    sandbox = obj.connect_sandbox(sandbox_id)
    try:
        sandbox.commands.interrupt(execution_id)
        click.echo(f"Interrupted: {execution_id}")
    finally:
        sandbox.close()


# ---- top-level exec alias ------------------------------------------------

@click.command("exec")
@click.argument("sandbox_id")
@click.argument("command", nargs=-1, required=True)
@click.option("-d", "--background", is_flag=True, default=False, help="在后台运行命令。")
@click.option("-w", "--workdir", default=None, help="工作目录路径。")
@click.option("-t", "--timeout", type=DURATION, default=None, help="命令超时时间（如 30s, 5m）。")
@click.pass_obj
@handle_errors
def exec_cmd(
    obj: ClientContext,
    sandbox_id: str,
    command: tuple[str, ...],
    background: bool,
    workdir: str | None,
    timeout: timedelta | None,
) -> None:
    """执行命令的快捷别名（等同于 'command run'）。

    提供较短的命令形式，方便日常使用。功能和参数与 `command run` 完全相同。

    参数：
        sandbox_id: 沙盒 ID
        command: 要执行的命令及参数

    使用示例：
        # 等同于：osb command run sb-1 ls -la
        osb exec sb-1 ls -la

        # 后台运行
        osb exec sb-1 -d ./long_running_script.sh
    """
    _run_command(obj, sandbox_id, command, background, workdir, timeout)
