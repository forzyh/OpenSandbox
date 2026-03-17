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

"""代码执行相关命令的实现模块。

本模块实现了通过代码解释器（Code Interpreter）在沙盒中执行代码的相关 CLI 命令，包括：
1. code run: 执行代码片段
2. code context create/list/delete/delete-all: 管理执行上下文
3. code interrupt: 中断正在运行的代码

支持的语言包括：Python、JavaScript、Java、Go、Bash 等。

主要特点：
- 支持有状态会话（通过 context-id）
- 实时流式输出代码执行结果
- 上下文管理支持多次执行的变量共享
"""

from __future__ import annotations

import sys

import click

from opensandbox.models.execd import OutputMessage
from opensandbox.models.execd_sync import ExecutionHandlersSync

from opensandbox_cli.client import ClientContext
from opensandbox_cli.utils import handle_errors


@click.group("code", invoke_without_command=True)
@click.pass_context
def code_group(ctx: click.Context) -> None:
    """代码执行命令组入口。

    当没有指定子命令时，显示帮助信息。

    使用示例：
        osb code --help                    # 查看帮助
        osb code run sb-1 -l python        # 执行 Python 代码
        osb code context create sb-1 -l python  # 创建上下文
    """
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


# ---- run ------------------------------------------------------------------

@click.command("run")
@click.argument("sandbox_id")
@click.option("--language", "-l", required=True, help="编程语言（python, javascript, java, go, bash 等）。")
@click.option("--code", "-c", default=None, help="要执行的代码。如未提供则从 stdin 读取。")
@click.option("--context-id", default=None, help="有状态会话的执行上下文 ID。")
@click.pass_obj
@handle_errors
def code_run(
    obj: ClientContext,
    sandbox_id: str,
    language: str,
    code: str | None,
    context_id: str | None,
) -> None:
    """在沙盒中执行代码。

    通过代码解释器在指定沙盒中运行代码片段。支持多种编程语言。

    参数：
        sandbox_id: 目标沙盒 ID
        language: 编程语言
        code: 要执行的代码内容（可选，默认从 stdin 读取）
        context-id: 执行上下文 ID，用于有状态会话（可选）

    使用示例：
        # 执行简单代码
        osb code run sb-1 -l python -c "print('hello')"

        # 从 stdin 读取代码
        echo "print('hello')" | osb code run sb-1 -l python

        # 有状态会话（变量可在多次执行间共享）
        osb code run sb-1 -l python -c "x = 1" --context-id ctx-1
        osb code run sb-1 -l python -c "print(x + 1)" --context-id ctx-1
    """
    from code_interpreter.sync.code_interpreter import CodeInterpreterSync

    # 如果没有提供代码，从 stdin 读取
    if code is None:
        if sys.stdin.isatty():
            click.echo("Reading code from stdin (Ctrl+D to finish):", err=True)
        code = sys.stdin.read()

    sandbox = obj.connect_sandbox(sandbox_id)
    try:
        interpreter = CodeInterpreterSync.create(sandbox)

        kwargs: dict = {}
        # 如果指定了上下文 ID，获取对应的上下文
        if context_id:
            ctx = interpreter.codes.get_context(context_id)
            kwargs["context"] = ctx

        # 设置输出处理器，实现实时流式输出
        def on_stdout(msg: OutputMessage) -> None:
            sys.stdout.write(msg.text)
            sys.stdout.flush()

        def on_stderr(msg: OutputMessage) -> None:
            sys.stderr.write(msg.text)
            sys.stderr.flush()

        handlers = ExecutionHandlersSync(on_stdout=on_stdout, on_stderr=on_stderr)
        execution = interpreter.codes.run(
            code, language=language, handlers=handlers, **kwargs
        )

        if execution.error:
            click.secho(
                f"\nError: {execution.error.name}: {execution.error.value}",
                fg="red",
                err=True,
            )
            sys.exit(1)
    finally:
        sandbox.close()


# ---- context group --------------------------------------------------------

@click.group("context", invoke_without_command=True)
@click.pass_context
def context_group(ctx: click.Context) -> None:
    """代码执行上下文管理命令组入口。

    当没有指定子命令时，显示帮助信息。

    上下文用于支持有状态的代码执行会话，允许在多次执行之间共享变量和状态。
    """
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@click.command("create")
@click.argument("sandbox_id")
@click.option("--language", "-l", required=True, help="上下文的编程语言。")
@click.pass_obj
@handle_errors
def context_create(obj: ClientContext, sandbox_id: str, language: str) -> None:
    """创建新的代码执行上下文。

    为指定语言创建一个新的执行上下文，返回 context_id 用于后续执行。

    参数：
        sandbox_id: 沙盒 ID
        language: 编程语言

    返回：
        context_id: 新创建的上下文 ID

    使用示例：
        osb code context create sb-1 -l python
        # 输出：Context Created: <context_id>
    """
    from code_interpreter.sync.code_interpreter import CodeInterpreterSync

    sandbox = obj.connect_sandbox(sandbox_id)
    try:
        interpreter = CodeInterpreterSync.create(sandbox)
        ctx = interpreter.codes.create_context(language)
        obj.output.print_dict(
            {"context_id": ctx.id, "language": language},
            title="Context Created",
        )
    finally:
        sandbox.close()


@click.command("list")
@click.argument("sandbox_id")
@click.option("--language", "-l", required=True, help="要列出上下文的语言。")
@click.pass_obj
@handle_errors
def context_list(obj: ClientContext, sandbox_id: str, language: str) -> None:
    """列出指定语言的所有代码执行上下文。

    参数：
        sandbox_id: 沙盒 ID
        language: 编程语言

    使用示例：
        osb code context list sb-1 -l python
    """
    from code_interpreter.sync.code_interpreter import CodeInterpreterSync

    sandbox = obj.connect_sandbox(sandbox_id)
    try:
        interpreter = CodeInterpreterSync.create(sandbox)
        contexts = interpreter.codes.list_contexts(language)
        for ctx in contexts:
            click.echo(f"{ctx.id}")
    finally:
        sandbox.close()


@click.command("delete")
@click.argument("sandbox_id")
@click.argument("context_id")
@click.pass_obj
@handle_errors
def context_delete(obj: ClientContext, sandbox_id: str, context_id: str) -> None:
    """删除指定的代码执行上下文。

    参数：
        sandbox_id: 沙盒 ID
        context_id: 要删除的上下文 ID

    使用示例：
        osb code context delete sb-1 ctx-123
    """
    from code_interpreter.sync.code_interpreter import CodeInterpreterSync

    sandbox = obj.connect_sandbox(sandbox_id)
    try:
        interpreter = CodeInterpreterSync.create(sandbox)
        interpreter.codes.delete_context(context_id)
        click.echo(f"Deleted context: {context_id}")
    finally:
        sandbox.close()


@click.command("delete-all")
@click.argument("sandbox_id")
@click.option("--language", "-l", required=True, help="要删除所有上下文的语言。")
@click.pass_obj
@handle_errors
def context_delete_all(obj: ClientContext, sandbox_id: str, language: str) -> None:
    """删除指定语言的所有代码执行上下文。

    参数：
        sandbox_id: 沙盒 ID
        language: 编程语言

    使用示例：
        osb code context delete-all sb-1 -l python
    """
    from code_interpreter.sync.code_interpreter import CodeInterpreterSync

    sandbox = obj.connect_sandbox(sandbox_id)
    try:
        interpreter = CodeInterpreterSync.create(sandbox)
        interpreter.codes.delete_contexts(language)
        click.echo(f"Deleted all {language} contexts")
    finally:
        sandbox.close()


# ---- interrupt ------------------------------------------------------------

@click.command("interrupt")
@click.argument("sandbox_id")
@click.argument("execution_id")
@click.pass_obj
@handle_errors
def code_interrupt(obj: ClientContext, sandbox_id: str, execution_id: str) -> None:
    """中断正在运行的代码执行。

    向指定 execution_id 的代码执行发送中断信号，停止其运行。

    参数：
        sandbox_id: 沙盒 ID
        execution_id: 要中断的执行 ID

    使用示例：
        osb code interrupt sb-1 exec-123
    """
    sandbox = obj.connect_sandbox(sandbox_id)
    try:
        sandbox.commands.interrupt(execution_id)
        click.echo(f"Interrupted: {execution_id}")
    finally:
        sandbox.close()
