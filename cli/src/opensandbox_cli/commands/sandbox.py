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

"""沙盒生命周期管理命令的实现模块。

本模块实现了沙盒生命周期管理的相關 CLI 命令，包括：
1. create: 创建新沙盒
2. list: 列出沙盒
3. get: 获取沙盒详情
4. kill: 终止沙盒
5. pause: 暂停沙盒
6. resume: 恢复沙盒
7. renew: 续期沙盒
8. endpoint: 获取沙盒端口映射
9. health: 健康检查
10. metrics: 获取资源使用指标

这些命令提供了完整的沙盒管理能力，从创建到销毁的全生命周期控制。
"""

from __future__ import annotations

import json
from datetime import timedelta

import click

from opensandbox.models.sandboxes import NetworkPolicy, SandboxFilter

from opensandbox_cli.client import ClientContext
from opensandbox_cli.utils import DURATION, KEY_VALUE, handle_errors


@click.group("sandbox", invoke_without_command=True)
@click.pass_context
def sandbox_group(ctx: click.Context) -> None:
    """沙盒管理命令组入口。

    当没有指定子命令时，显示帮助信息。

    使用示例：
        osb sandbox --help           # 查看帮助
        osb sandbox create -i python:3.11  # 创建沙盒
        osb sandbox list             # 列出沙盒
    """
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


# 别名：osb sb ...
sandbox_group.name = "sandbox"


# ---- create ---------------------------------------------------------------

@click.command("create")
@click.option("--image", "-i", required=True, help="容器镜像（如 python:3.11）。")
@click.option("--timeout", "-t", "timeout", type=DURATION, default=None, help="沙盒生命周期（如 10m, 1h）。")
@click.option("--env", "-e", "envs", multiple=True, type=KEY_VALUE, help="环境变量（KEY=VALUE），可重复指定。")
@click.option("--metadata", "-m", "metadata_kv", multiple=True, type=KEY_VALUE, help="元数据（KEY=VALUE），可重复指定。")
@click.option("--resource", "resources_kv", multiple=True, type=KEY_VALUE, help="资源限制（如 cpu=1 memory=2Gi），可重复指定。")
@click.option("--entrypoint", default=None, help="入口命令（JSON 数组或 shell 字符串）。")
@click.option("--network-policy-file", type=click.Path(exists=True), default=None, help="网络策略 JSON 文件路径。")
@click.option("--skip-health-check", is_flag=True, default=False, help="跳过沙盒就绪等待。")
@click.option("--ready-timeout", type=DURATION, default=None, help="沙盒就绪最大等待时间（如 30s）。")
@click.pass_obj
@handle_errors
def sandbox_create(
    obj: ClientContext,
    image: str,
    timeout: timedelta | None,
    envs: tuple[tuple[str, str], ...],
    metadata_kv: tuple[tuple[str, str], ...],
    resources_kv: tuple[tuple[str, str], ...],
    entrypoint: str | None,
    network_policy_file: str | None,
    skip_health_check: bool,
    ready_timeout: timedelta | None,
) -> None:
    """创建新的沙盒。

    根据指定配置创建并启动一个新的沙盒实例。

    参数：
        image: 容器镜像名称
        timeout: 沙盒生命周期（超时后自动销毁）
        envs: 环境变量列表
        metadata_kv: 元数据键值对
        resources_kv: 资源限制配置
        entrypoint: 容器入口命令
        network_policy_file: 网络策略配置文件
        skip_health_check: 是否跳过健康检查
        ready_timeout: 等待沙盒就绪的超时时间

    使用示例：
        # 创建简单沙盒
        osb sandbox create -i python:3.11

        # 带超时和环境变量
        osb sandbox create -i python:3.11 -t 1h -e KEY=value -e FOO=bar

        # 带资源限制
        osb sandbox create -i python:3.11 --resource cpu=1 --resource memory=2Gi

        # 带元数据
        osb sandbox create -i python:3.11 -m project=myproj -m env=dev
    """
    from opensandbox.sync.sandbox import SandboxSync

    kwargs: dict = {
        "connection_config": obj.connection_config,
        "skip_health_check": skip_health_check,
    }
    if timeout is not None:
        kwargs["timeout"] = timeout
    if ready_timeout is not None:
        kwargs["ready_timeout"] = ready_timeout
    if envs:
        kwargs["env"] = dict(envs)
    if metadata_kv:
        kwargs["metadata"] = dict(metadata_kv)
    if resources_kv:
        kwargs["resource"] = dict(resources_kv)
    if entrypoint:
        try:
            # 尝试解析为 JSON 数组
            kwargs["entrypoint"] = json.loads(entrypoint)
        except json.JSONDecodeError:
            # 否则作为 shell 命令处理
            kwargs["entrypoint"] = ["sh", "-c", entrypoint]
    if network_policy_file:
        with open(network_policy_file) as f:
            kwargs["network_policy"] = NetworkPolicy(**json.load(f))

    sandbox = SandboxSync.create(image, **kwargs)
    obj.output.print_dict(
        {"id": sandbox.id, "status": "created"},
        title="Sandbox Created",
    )


# ---- list -----------------------------------------------------------------

@click.command("list")
@click.option("--state", "-s", "states", multiple=True, help="按状态过滤（Pending, Running, Paused 等），可重复指定。")
@click.option("--metadata", "-m", "metadata_kv", multiple=True, type=KEY_VALUE, help="按元数据过滤（KEY=VALUE），可重复指定。")
@click.option("--page", type=int, default=None, help="页码（从 0 开始）。")
@click.option("--page-size", type=int, default=None, help="每页项目数。")
@click.pass_obj
@handle_errors
def sandbox_list(
    obj: ClientContext,
    states: tuple[str, ...],
    metadata_kv: tuple[tuple[str, str], ...],
    page: int | None,
    page_size: int | None,
) -> None:
    """列出沙盒。

    查询并列出所有符合条件的沙盒信息，支持分页和过滤。

    参数：
        states: 按状态过滤
        metadata_kv: 按元数据过滤
        page: 页码（0 起始）
        page_size: 每页数量

    使用示例：
        # 列出所有沙盒
        osb sandbox list

        # 按状态过滤
        osb sandbox list -s Running -s Pending

        # 按元数据过滤
        osb sandbox list -m project=myproj

        # 分页查询
        osb sandbox list --page 0 --page-size 20
    """
    mgr = obj.get_manager()
    filt = SandboxFilter(
        states=list(states) if states else None,
        metadata=dict(metadata_kv) if metadata_kv else None,
        page=page,
        page_size=page_size,
    )
    result = mgr.list_sandbox_infos(filt)
    obj.output.print_models(
        result.sandbox_infos,
        columns=["id", "status", "image", "created_at", "expires_at"],
        title="Sandboxes",
    )


# ---- get ------------------------------------------------------------------

@click.command("get")
@click.argument("sandbox_id")
@click.pass_obj
@handle_errors
def sandbox_get(obj: ClientContext, sandbox_id: str) -> None:
    """获取沙盒详细信息。

    查询指定沙盒的完整信息，包括状态、配置、资源使用等。

    参数：
        sandbox_id: 沙盒 ID

    使用示例：
        osb sandbox get sb-123
    """
    mgr = obj.get_manager()
    info = mgr.get_sandbox_info(sandbox_id)
    obj.output.print_model(info, title="Sandbox Info")


# ---- kill -----------------------------------------------------------------

@click.command("kill")
@click.argument("sandbox_ids", nargs=-1, required=True)
@click.pass_obj
@handle_errors
def sandbox_kill(obj: ClientContext, sandbox_ids: tuple[str, ...]) -> None:
    """终止一个或多个沙盒。

    立即终止并删除指定的沙盒，释放所有资源。

    参数：
        sandbox_ids: 要终止的沙盒 ID 列表

    使用示例：
        # 终止单个沙盒
        osb sandbox kill sb-123

        # 终止多个沙盒
        osb sandbox kill sb-1 sb-2 sb-3
    """
    mgr = obj.get_manager()
    for sid in sandbox_ids:
        mgr.kill_sandbox(sid)
        click.echo(f"Killed: {sid}")


# ---- pause ----------------------------------------------------------------

@click.command("pause")
@click.argument("sandbox_id")
@click.pass_obj
@handle_errors
def sandbox_pause(obj: ClientContext, sandbox_id: str) -> None:
    """暂停运行中的沙盒。

    暂停沙盒的执行，保留当前状态但暂停 CPU 时间片分配。
    暂停期间沙盒仍然存在，但不会消耗计算资源。

    参数：
        sandbox_id: 沙盒 ID

    使用示例：
        osb sandbox pause sb-123
    """
    mgr = obj.get_manager()
    mgr.pause_sandbox(sandbox_id)
    click.echo(f"Paused: {sandbox_id}")


# ---- resume ---------------------------------------------------------------

@click.command("resume")
@click.argument("sandbox_id")
@click.pass_obj
@handle_errors
def sandbox_resume(obj: ClientContext, sandbox_id: str) -> None:
    """恢复已暂停的沙盒。

    恢复之前被暂停的沙盒，使其继续正常运行。

    参数：
        sandbox_id: 沙盒 ID

    使用示例：
        osb sandbox resume sb-123
    """
    mgr = obj.get_manager()
    mgr.resume_sandbox(sandbox_id)
    click.echo(f"Resumed: {sandbox_id}")


# ---- renew ----------------------------------------------------------------

@click.command("renew")
@click.argument("sandbox_id")
@click.option("--timeout", "-t", required=True, type=DURATION, help="新的有效期时长（如 30m, 2h）。")
@click.pass_obj
@handle_errors
def sandbox_renew(obj: ClientContext, sandbox_id: str, timeout: timedelta) -> None:
    """续期沙盒。

    延长沙盒的过期时间，防止其被自动清理。

    参数：
        sandbox_id: 沙盒 ID
        timeout: 新的有效期时长

    使用示例：
        osb sandbox renew sb-123 -t 1h
        osb sandbox renew sb-123 --timeout 30m
    """
    mgr = obj.get_manager()
    resp = mgr.renew_sandbox(sandbox_id, timeout)
    obj.output.print_dict(
        {"sandbox_id": sandbox_id, "expires_at": str(resp.expires_at)},
        title="Sandbox Renewed",
    )


# ---- endpoint -------------------------------------------------------------

@click.command("endpoint")
@click.argument("sandbox_id")
@click.option("--port", "-p", required=True, type=int, help="端口号。")
@click.pass_obj
@handle_errors
def sandbox_endpoint(obj: ClientContext, sandbox_id: str, port: int) -> None:
    """获取沙盒端口的公开访问地址。

    查询沙盒指定端口的对外映射地址，用于从外部访问沙盒内的服务。

    参数：
        sandbox_id: 沙盒 ID
        port: 沙盒内端口号

    使用示例：
        osb sandbox endpoint sb-123 -p 8080
    """
    sandbox = obj.connect_sandbox(sandbox_id)
    try:
        ep = sandbox.get_endpoint(port)
        obj.output.print_model(ep, title="Sandbox Endpoint")
    finally:
        sandbox.close()


# ---- health ---------------------------------------------------------------

@click.command("health")
@click.argument("sandbox_id")
@click.pass_obj
@handle_errors
def sandbox_health(obj: ClientContext, sandbox_id: str) -> None:
    """检查沙盒健康状态。

    执行健康检查，确认沙盒是否正常运行。

    参数：
        sandbox_id: 沙盒 ID

    使用示例：
        osb sandbox health sb-123
    """
    sandbox = obj.connect_sandbox(sandbox_id)
    try:
        healthy = sandbox.is_healthy()
        obj.output.print_dict(
            {"sandbox_id": sandbox_id, "healthy": healthy},
            title="Health Check",
        )
    finally:
        sandbox.close()


# ---- metrics --------------------------------------------------------------

@click.command("metrics")
@click.argument("sandbox_id")
@click.pass_obj
@handle_errors
def sandbox_metrics(obj: ClientContext, sandbox_id: str) -> None:
    """获取沙盒资源使用指标。

    查询沙盒的 CPU、内存等资源使用情况。

    参数：
        sandbox_id: 沙盒 ID

    使用示例：
        osb sandbox metrics sb-123
    """
    sandbox = obj.connect_sandbox(sandbox_id)
    try:
        m = sandbox.get_metrics()
        obj.output.print_model(m, title="Sandbox Metrics")
    finally:
        sandbox.close()
