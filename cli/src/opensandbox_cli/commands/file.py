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

"""文件操作相关命令的实现模块。

本模块实现了在沙盒中进行文件操作的相關 CLI 命令，包括：
1. cat: 读取文件内容
2. write: 写入文件内容
3. upload: 上传本地文件到沙盒
4. download: 从沙盒下载文件到本地
5. rm: 删除文件
6. mv: 移动/重命名文件
7. mkdir: 创建目录
8. rmdir: 删除目录
9. search: 搜索文件
10. info: 获取文件/目录信息
11. chmod: 设置文件权限
12. replace: 替换文件内容

这些命令提供了完整的文件系统操作能力，方便用户管理沙盒中的文件。
"""

from __future__ import annotations

import sys
from pathlib import Path

import click

from opensandbox_cli.client import ClientContext
from opensandbox_cli.utils import handle_errors


@click.group("file", invoke_without_command=True)
@click.pass_context
def file_group(ctx: click.Context) -> None:
    """文件操作命令组入口。

    当没有指定子命令时，显示帮助信息。

    使用示例：
        osb file --help              # 查看帮助
        osb file cat sb-1 /etc/hosts # 查看文件内容
        osb file upload sb-1 ./local.txt /remote.txt  # 上传文件
    """
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


# ---- cat (read) -----------------------------------------------------------

@click.command("cat")
@click.argument("sandbox_id")
@click.argument("path")
@click.option("--encoding", default="utf-8", help="文件编码格式。")
@click.pass_obj
@handle_errors
def file_cat(obj: ClientContext, sandbox_id: str, path: str, encoding: str) -> None:
    """读取沙盒中的文件内容。

    将指定文件的内容输出到标准输出。

    参数：
        sandbox_id: 沙盒 ID
        path: 文件路径
        encoding: 文件编码（默认 utf-8）

    使用示例：
        osb file cat sb-1 /etc/hostname
        osb file cat sb-1 /app/config.json --encoding utf-8
    """
    sandbox = obj.connect_sandbox(sandbox_id)
    try:
        content = sandbox.files.read_file(path, encoding=encoding)
        click.echo(content, nl=False)
    finally:
        sandbox.close()


# ---- write ----------------------------------------------------------------

@click.command("write")
@click.argument("sandbox_id")
@click.argument("path")
@click.option("--content", "-c", default=None, help="要写入的内容。如未提供则从 stdin 读取。")
@click.option("--encoding", default="utf-8", help="文件编码格式。")
@click.option("--mode", default=None, help="文件权限模式（如 0644）。")
@click.option("--owner", default=None, help="文件所有者。")
@click.option("--group", default=None, help="文件所属组。")
@click.pass_obj
@handle_errors
def file_write(
    obj: ClientContext,
    sandbox_id: str,
    path: str,
    content: str | None,
    encoding: str,
    mode: str | None,
    owner: str | None,
    group: str | None,
) -> None:
    """向沙盒中的文件写入内容。

    创建新文件或覆盖已有文件的内容。支持设置文件权限、所有者等属性。

    参数：
        sandbox_id: 沙盒 ID
        path: 目标文件路径
        content: 要写入的内容（可选，默认从 stdin 读取）
        encoding: 文件编码（默认 utf-8）
        mode: 权限模式（可选）
        owner: 所有者（可选）
        group: 所属组（可选）

    使用示例：
        # 直接指定内容
        osb file write sb-1 /tmp/test.txt -c "hello world"

        # 从 stdin 读取内容
        echo "hello" | osb file write sb-1 /tmp/test.txt

        # 设置权限
        osb file write sb-1 /app/script.sh -c "#!/bin/bash" --mode 0755
    """
    if content is None:
        if sys.stdin.isatty():
            click.echo("Reading from stdin (Ctrl+D to finish):", err=True)
        content = sys.stdin.read()

    sandbox = obj.connect_sandbox(sandbox_id)
    try:
        kwargs: dict = {"encoding": encoding}
        if mode is not None:
            kwargs["mode"] = mode
        if owner is not None:
            kwargs["owner"] = owner
        if group is not None:
            kwargs["group"] = group
        sandbox.files.write_file(path, content, **kwargs)
        click.echo(f"Written: {path}")
    finally:
        sandbox.close()


# ---- upload ---------------------------------------------------------------

@click.command("upload")
@click.argument("sandbox_id")
@click.argument("local_path", type=click.Path(exists=True))
@click.argument("remote_path")
@click.pass_obj
@handle_errors
def file_upload(
    obj: ClientContext, sandbox_id: str, local_path: str, remote_path: str
) -> None:
    """上传本地文件到沙盒。

    将本地文件复制到沙盒中的指定路径。

    参数：
        sandbox_id: 沙盒 ID
        local_path: 本地文件路径（必须存在）
        remote_path: 沙盒中的目标路径

    使用示例：
        osb file upload sb-1 ./config.json /app/config.json
        osb file upload sb-1 /home/user/data.csv /workspace/data.csv
    """
    data = Path(local_path).read_bytes()
    sandbox = obj.connect_sandbox(sandbox_id)
    try:
        sandbox.files.write_file(remote_path, data)
        click.echo(f"Uploaded: {local_path} -> {remote_path}")
    finally:
        sandbox.close()


# ---- download -------------------------------------------------------------

@click.command("download")
@click.argument("sandbox_id")
@click.argument("remote_path")
@click.argument("local_path", type=click.Path())
@click.pass_obj
@handle_errors
def file_download(
    obj: ClientContext, sandbox_id: str, remote_path: str, local_path: str
) -> None:
    """从沙盒下载文件到本地。

    将沙盒中的文件复制到本地指定路径。

    参数：
        sandbox_id: 沙盒 ID
        remote_path: 沙盒中的源文件路径
        local_path: 本地目标路径

    使用示例：
        osb file download sb-1 /app/output.txt ./output.txt
        osb file download sb-1 /workspace/result.zip /tmp/result.zip
    """
    sandbox = obj.connect_sandbox(sandbox_id)
    try:
        content = sandbox.files.read_bytes(remote_path)
        Path(local_path).write_bytes(content)
        click.echo(f"Downloaded: {remote_path} -> {local_path}")
    finally:
        sandbox.close()


# ---- rm (delete) ----------------------------------------------------------

@click.command("rm")
@click.argument("sandbox_id")
@click.argument("paths", nargs=-1, required=True)
@click.pass_obj
@handle_errors
def file_rm(obj: ClientContext, sandbox_id: str, paths: tuple[str, ...]) -> None:
    """删除沙盒中的文件。

    支持一次删除多个文件。

    参数：
        sandbox_id: 沙盒 ID
        paths: 要删除的文件路径列表

    使用示例：
        # 删除单个文件
        osb file rm sb-1 /tmp/test.txt

        # 删除多个文件
        osb file rm sb-1 /tmp/a.txt /tmp/b.txt /tmp/c.txt
    """
    sandbox = obj.connect_sandbox(sandbox_id)
    try:
        sandbox.files.delete_files(list(paths))
        for p in paths:
            click.echo(f"Deleted: {p}")
    finally:
        sandbox.close()


# ---- mv (move) ------------------------------------------------------------

@click.command("mv")
@click.argument("sandbox_id")
@click.argument("source")
@click.argument("destination")
@click.pass_obj
@handle_errors
def file_mv(
    obj: ClientContext, sandbox_id: str, source: str, destination: str
) -> None:
    """移动或重命名沙盒中的文件。

    将文件从源路径移动到目标路径，可用于移动文件或重命名文件。

    参数：
        sandbox_id: 沙盒 ID
        source: 源文件路径
        destination: 目标文件路径

    使用示例：
        # 移动文件
        osb file mv sb-1 /tmp/old.txt /app/new.txt

        # 重命名文件
        osb file mv sb-1 /app/config.json /app/config.json.bak
    """
    from opensandbox.models.filesystem import MoveEntry

    sandbox = obj.connect_sandbox(sandbox_id)
    try:
        sandbox.files.move_files([MoveEntry(source=source, destination=destination)])
        click.echo(f"Moved: {source} -> {destination}")
    finally:
        sandbox.close()


# ---- mkdir ----------------------------------------------------------------

@click.command("mkdir")
@click.argument("sandbox_id")
@click.argument("paths", nargs=-1, required=True)
@click.option("--mode", default=None, help="目录权限模式。")
@click.option("--owner", default=None, help="目录所有者。")
@click.option("--group", default=None, help="目录所属组。")
@click.pass_obj
@handle_errors
def file_mkdir(
    obj: ClientContext,
    sandbox_id: str,
    paths: tuple[str, ...],
    mode: str | None,
    owner: str | None,
    group: str | None,
) -> None:
    """在沙盒中创建目录。

    支持一次创建多个目录，可指定权限、所有者等属性。

    参数：
        sandbox_id: 沙盒 ID
        paths: 要创建的目录路径列表
        mode: 权限模式（可选）
        owner: 所有者（可选）
        group: 所属组（可选）

    使用示例：
        # 创建单个目录
        osb file mkdir sb-1 /app/logs

        # 创建多个目录
        osb file mkdir sb-1 /app/logs /app/data /app/config

        # 指定权限
        osb file mkdir sb-1 /app/data --mode 0755
    """
    from opensandbox.models.filesystem import WriteEntry

    sandbox = obj.connect_sandbox(sandbox_id)
    try:
        entries = []
        for p in paths:
            kwargs: dict = {"path": p}
            if mode is not None:
                kwargs["mode"] = mode
            if owner is not None:
                kwargs["owner"] = owner
            if group is not None:
                kwargs["group"] = group
            entries.append(WriteEntry(**kwargs))
        sandbox.files.create_directories(entries)
        for p in paths:
            click.echo(f"Created: {p}")
    finally:
        sandbox.close()


# ---- rmdir ----------------------------------------------------------------

@click.command("rmdir")
@click.argument("sandbox_id")
@click.argument("paths", nargs=-1, required=True)
@click.pass_obj
@handle_errors
def file_rmdir(obj: ClientContext, sandbox_id: str, paths: tuple[str, ...]) -> None:
    """删除沙盒中的目录。

    支持一次删除多个目录。目录必须为空才能删除。

    参数：
        sandbox_id: 沙盒 ID
        paths: 要删除的目录路径列表

    使用示例：
        osb file rmdir sb-1 /tmp/empty_dir
        osb file rmdir sb-1 /app/old_logs /app/old_data
    """
    sandbox = obj.connect_sandbox(sandbox_id)
    try:
        sandbox.files.delete_directories(list(paths))
        for p in paths:
            click.echo(f"Removed: {p}")
    finally:
        sandbox.close()


# ---- search ---------------------------------------------------------------

@click.command("search")
@click.argument("sandbox_id")
@click.argument("path")
@click.option("--pattern", "-p", required=True, help="要搜索的 glob 模式。")
@click.pass_obj
@handle_errors
def file_search(
    obj: ClientContext, sandbox_id: str, path: str, pattern: str
) -> None:
    """在沙盒中搜索文件。

    使用 glob 模式在指定目录下搜索匹配的文件。

    参数：
        sandbox_id: 沙盒 ID
        path: 搜索的起始目录
        pattern: glob 搜索模式（如 *.py, **/*.txt）

    使用示例：
        # 搜索所有 Python 文件
        osb file search sb-1 /app -p "*.py"

        # 递归搜索所有文本文件
        osb file search sb-1 /workspace -p "**/*.txt"
    """
    from opensandbox.models.filesystem import SearchEntry

    sandbox = obj.connect_sandbox(sandbox_id)
    try:
        results = sandbox.files.search(SearchEntry(path=path, pattern=pattern))
        if obj.output.fmt in ("json", "yaml"):
            obj.output.print_models(results, columns=["path", "size", "mode", "owner", "modified_at"])
        else:
            for entry in results:
                click.echo(f"{entry.size:>10}  {entry.owner:<8}  {entry.path}")
    finally:
        sandbox.close()


# ---- info (stat) ----------------------------------------------------------

@click.command("info")
@click.argument("sandbox_id")
@click.argument("paths", nargs=-1, required=True)
@click.pass_obj
@handle_errors
def file_info(obj: ClientContext, sandbox_id: str, paths: tuple[str, ...]) -> None:
    """获取文件/目录的详细信息。

    显示文件或目录的元数据，包括大小、权限、所有者、修改时间等。

    参数：
        sandbox_id: 沙盒 ID
        paths: 要查询的路径列表

    使用示例：
        osb file info sb-1 /etc/hosts
        osb file info sb-1 /app /workspace
    """
    sandbox = obj.connect_sandbox(sandbox_id)
    try:
        info_map = sandbox.files.get_file_info(list(paths))
        for path, entry in info_map.items():
            obj.output.print_dict(
                {"path": path, **entry.model_dump(mode="json")},
                title=path,
            )
    finally:
        sandbox.close()


# ---- chmod ----------------------------------------------------------------

@click.command("chmod")
@click.argument("sandbox_id")
@click.argument("path")
@click.option("--mode", required=True, help="权限模式（如 0755）。")
@click.option("--owner", default=None, help="文件所有者。")
@click.option("--group", default=None, help="文件所属组。")
@click.pass_obj
@handle_errors
def file_chmod(
    obj: ClientContext,
    sandbox_id: str,
    path: str,
    mode: str,
    owner: str | None,
    group: str | None,
) -> None:
    """设置文件权限。

    修改文件的权限模式、所有者或所属组。

    参数：
        sandbox_id: 沙盒 ID
        path: 文件路径
        mode: 权限模式（如 0644, 0755）
        owner: 新所有者（可选）
        group: 新所属组（可选）

    使用示例：
        # 设置执行权限
        osb file chmod sb-1 /app/script.sh --mode 0755

        # 设置读写权限
        osb file chmod sb-1 /app/config.json --mode 0644

        # 同时修改所有者
        osb file chmod sb-1 /app/data --mode 0644 --owner root --group root
    """
    from opensandbox.models.filesystem import SetPermissionEntry

    sandbox = obj.connect_sandbox(sandbox_id)
    try:
        sandbox.files.set_permissions(
            [SetPermissionEntry(path=path, mode=mode, owner=owner, group=group)]
        )
        click.echo(f"Permissions set: {path}")
    finally:
        sandbox.close()


# ---- replace --------------------------------------------------------------

@click.command("replace")
@click.argument("sandbox_id")
@click.argument("path")
@click.option("--old", required=True, help="要搜索的文本。")
@click.option("--new", required=True, help="替换文本。")
@click.pass_obj
@handle_errors
def file_replace(
    obj: ClientContext, sandbox_id: str, path: str, old: str, new: str
) -> None:
    """替换文件中的内容。

    在指定文件中搜索并替换文本内容。

    参数：
        sandbox_id: 沙盒 ID
        path: 文件路径
        old: 要搜索的原文本
        new: 替换后的新文本

    使用示例：
        # 替换配置文件中的地址
        osb file replace sb-1 /app/config.json --old "localhost" --new "example.com"

        # 修复代码中的拼写错误
        osb file replace sb-1 /app/main.py --old "fucntion" --new "function"
    """
    from opensandbox.models.filesystem import ContentReplaceEntry

    sandbox = obj.connect_sandbox(sandbox_id)
    try:
        sandbox.files.replace_contents(
            [ContentReplaceEntry(path=path, old_content=old, new_content=new)]
        )
        click.echo(f"Replaced in: {path}")
    finally:
        sandbox.close()
