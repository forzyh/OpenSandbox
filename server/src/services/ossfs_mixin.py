# Copyright 2025 Alibaba Group Holding Ltd.
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

"""
OSSFS（阿里云对象存储文件系统）特定的 Docker 运行时行为模块。

本模块提供了 OSSFS 卷挂载的完整实现，包括：
- OSSFS 路径解析：将卷配置解析为实际的挂载路径
- OSSFS 命令构建：构建 ossfs 和 ossfs2 的挂载命令
- OSSFS 挂载管理：管理挂载生命周期，支持引用计数
- OSSFS 验证：验证 OSSFS 卷配置的有效性

OSSFS 允许将阿里云 OSS Bucket 挂载为本地文件系统，使得容器
可以像访问本地文件一样访问对象存储中的数据。

支持两个版本的 OSSFS：
- 1.0 版本：使用传统的 ossfs 命令
- 2.0 版本：使用新一代 ossfs2 命令，支持配置文件方式
"""

from __future__ import annotations

import logging
import os
import posixpath
import subprocess
import tempfile
from typing import Any, Optional
from uuid import uuid4

from fastapi import HTTPException, status

from src.services.constants import SandboxErrorCodes
from src.services.helpers import normalize_external_endpoint_url

logger = logging.getLogger(__name__)


class OSSFSMixin:
    """
    OSSFS 混合类，提供 OSSFS 卷挂载相关的工具方法。

    该类设计为 mixin 模式，可以被其他服务类继承以获取 OSSFS 功能。

    主要功能：
    - OSSFS 选项标准化
    - OSSFS 路径解析
    - OSSFS v1 和 v2 命令构建
    - OSSFS 挂载和卸载操作
    - OSSFS 引用计数管理
    - OSSFS 卷验证

    Attributes:
        app_config: 应用配置，包含 storage.ossfs_mount_root 等设置
        _ossfs_mount_ref_counts: OSSFS 挂载引用计数字典
        _ossfs_mount_lock: OSSFS 挂载操作的线程锁
    """

    @staticmethod
    def _normalize_ossfs_option(raw_option: str) -> str:
        """
        标准化 OSSFS 选项字符串。

        移除选项前后的空白字符，返回空字符串如果选项为空。

        Args:
            raw_option: 原始选项字符串

        Returns:
            str: 标准化后的选项字符串，空选项返回空字符串
        """
        option = str(raw_option).strip()
        if not option:
            return ""
        return option

    def _resolve_ossfs_paths(self, volume) -> tuple[str, str]:
        """
        解析 OSSFS 基础挂载路径和绑定路径。

        对于 OSSFS，``volume.subPath`` 表示 Bucket 前缀。
        后端挂载路径和绑定路径是相同的：
        - path = ossfs_mount_root/<bucket>/<subPath?>

        Args:
            volume: 卷配置对象，包含 ossfs 和 sub_path 属性

        Returns:
            tuple[str, str]: (backend_path, bind_path) 元组
                            backend_path 和 bind_path 相同

        Raises:
            HTTPException: 如果 ossfs_mount_root 未配置为绝对路径
                          或解析后的路径逃逸了 Bucket 根目录

        路径解析示例：
            ossfs_mount_root = "/mnt/ossfs"
            bucket = "my-bucket"
            subPath = "data/logs"
            结果：/mnt/ossfs/my-bucket/data/logs
        """
        # 获取并验证 OSSFS 挂载根路径
        mount_root = (self.app_config.storage.ossfs_mount_root or "").strip()
        if not mount_root.startswith("/"):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={
                    "code": SandboxErrorCodes.INVALID_OSSFS_MOUNT_ROOT,
                    "message": (
                        "storage.ossfs_mount_root 必须配置为绝对路径。"
                    ),
                },
            )

        # 规范化路径（移除多余的分隔符等）
        mount_root = posixpath.normpath(mount_root)
        # 构建 Bucket 根路径
        bucket_root = posixpath.normpath(posixpath.join(mount_root, volume.ossfs.bucket))
        # 获取前缀（subPath）
        prefix = (volume.sub_path or "").lstrip("/")
        # 构建后端路径
        backend_path = posixpath.normpath(posixpath.join(bucket_root, prefix))

        # 安全验证：确保解析后的路径没有逃逸 Bucket 根目录
        bucket_prefix = bucket_root if bucket_root.endswith("/") else bucket_root + "/"
        if backend_path != bucket_root and not backend_path.startswith(bucket_prefix):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": SandboxErrorCodes.INVALID_SUB_PATH,
                    "message": (
                        f"卷 '{volume.name}': 解析的 OSSFS 前缀逃逸了 Bucket 根目录。"
                    ),
                },
            )

        return backend_path, backend_path

    def _build_ossfs_v1_command(
        self,
        volume,
        source: str,
        backend_path: str,
        endpoint_url: str,
        passwd_file: str,
    ) -> list[str]:
        """
        构建 OSSFS v1 版本的挂载命令。

        v1 版本使用命令行参数方式传递配置。

        Args:
            volume: 卷配置对象
            source: OSSFS 源路径（bucket:/prefix 格式）
            backend_path: 后端挂载路径
            endpoint_url: OSS 端点 URL
            passwd_file: 密码文件路径（包含访问凭证）

        Returns:
            list[str]: ossfs 命令参数列表

        命令格式示例：
            ossfs my-bucket:/path /mnt/ossfs/my-bucket/path \\
                -o url=https://oss-cn-hangzhou.aliyuncs.com \\
                -o passwd_file=/tmp/xxx \\
                -o allow_other
        """
        cmd: list[str] = [
            "ossfs",
            source,
            backend_path,
            "-o",
            f"url={endpoint_url}",
            "-o",
            f"passwd_file={passwd_file}",
        ]
        # 添加用户指定的选项
        if volume.ossfs.options:
            for raw_opt in volume.ossfs.options:
                opt = self._normalize_ossfs_option(raw_opt)
                if opt:
                    cmd.extend(["-o", opt])
        return cmd

    def _build_ossfs_v2_config_lines(
        self,
        volume,
        endpoint_url: str,
        prefix: str,
    ) -> list[str]:
        """
        构建 OSSFS v2 版本的配置文件行。

        v2 版本使用配置文件方式传递配置，命令行为 ossfs2 mount。

        Args:
            volume: 卷配置对象
            endpoint_url: OSS 端点 URL
            prefix: OSS 路径前缀

        Returns:
            list[str]: 配置文件行列表

        配置文件格式示例：
            --oss_endpoint=https://oss-cn-hangzhou.aliyuncs.com
            --oss_bucket=my-bucket
            --oss_access_key_id=xxx
            --oss_access_key_secret=xxx
            --oss_bucket_prefix=path/to/prefix/
            --allow_other
        """
        conf_lines: list[str] = [
            f"--oss_endpoint={endpoint_url}",
            f"--oss_bucket={volume.ossfs.bucket}",
            f"--oss_access_key_id={volume.ossfs.access_key_id}",
            f"--oss_access_key_secret={volume.ossfs.access_key_secret}",
        ]
        # 如果指定了前缀，添加 bucket_prefix 配置
        if prefix:
            normalized_prefix = prefix if prefix.endswith("/") else f"{prefix}/"
            conf_lines.append(f"--oss_bucket_prefix={normalized_prefix}")
        # 添加用户指定的选项
        if volume.ossfs.options:
            for raw_opt in volume.ossfs.options:
                opt = self._normalize_ossfs_option(raw_opt)
                if opt:
                    conf_lines.append(f"--{opt}")
        return conf_lines

    @staticmethod
    def _build_ossfs_v2_mount_command(backend_path: str, conf_file: str) -> list[str]:
        """
        构建 OSSFS v2 版本的挂载命令。

        Args:
            backend_path: 后端挂载路径
            conf_file: 配置文件路径

        Returns:
            list[str]: ossfs2 mount 命令参数列表

        命令格式：
            ossfs2 mount <backend_path> -c <conf_file>
        """
        return ["ossfs2", "mount", backend_path, "-c", conf_file]

    @staticmethod
    def _run_ossfs_mount_command(cmd: list[str], volume_name: str) -> None:
        """
        执行 OSSFS 挂载命令。

        Args:
            cmd: 命令参数列表
            volume_name: 卷名称（用于错误消息）

        Raises:
            HTTPException: 如果命令执行失败
        """
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,  # 30 秒超时
            check=False,
        )
        if result.returncode != 0:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={
                    "code": SandboxErrorCodes.OSSFS_MOUNT_FAILED,
                    "message": (
                        f"卷 '{volume_name}': 挂载 OSSFS 后端失败。"
                        f"stderr={result.stderr.strip() or '未知错误'}"
                    ),
                },
            )

    def _mount_ossfs_backend_path(self, volume, backend_path: str) -> None:
        """
        使用版本特定的 OSSFS 参数将 OSS Bucket/路径挂载到 backend_path。

        支持两个版本的 OSSFS：
        - v1.0：使用 ossfs 命令，通过 passwd_file 传递凭证
        - v2.0：使用 ossfs2 命令，通过配置文件传递凭证

        Args:
            volume: 卷配置对象
            backend_path: 后端挂载路径

        Raises:
            HTTPException: 如果凭证无效、版本不支持或挂载失败
        """
        # 获取 OSSFS 凭证
        access_key_id = volume.ossfs.access_key_id
        access_key_secret = volume.ossfs.access_key_secret
        if not access_key_id or not access_key_secret:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": SandboxErrorCodes.INVALID_OSSFS_CREDENTIALS,
                    "message": (
                        "OSSFS 需要内联凭证："
                        "必须提供 accessKeyId 和 accessKeySecret。"
                    ),
                },
            )
        # 创建挂载点目录
        os.makedirs(backend_path, exist_ok=True)

        bucket = volume.ossfs.bucket
        prefix = (volume.sub_path or "").strip("/")
        # 构建 OSSFS 源路径（bucket:/prefix 格式）
        source = f"{bucket}:/{prefix}" if prefix else bucket
        endpoint = volume.ossfs.endpoint
        endpoint_url = normalize_external_endpoint_url(endpoint)

        passwd_file: Optional[str] = None
        conf_file: Optional[str] = None
        version = volume.ossfs.version or "2.0"  # 默认使用 v2.0
        try:
            if version == "1.0":
                # v1.0：使用 passwd_file 方式
                passwd_file = os.path.join(
                    tempfile.gettempdir(),
                    f"opensandbox-ossfs-inline-{uuid4().hex}",
                )
                # passwd_file 格式：bucket:accessKeyId:accessKeySecret
                with open(passwd_file, "w", encoding="utf-8") as f:
                    f.write(f"{bucket}:{access_key_id}:{access_key_secret}")
                os.chmod(passwd_file, 0o600)  # 设置只读权限
                cmd = self._build_ossfs_v1_command(
                    volume=volume,
                    source=source,
                    backend_path=backend_path,
                    endpoint_url=endpoint_url,
                    passwd_file=passwd_file,
                )
            elif version == "2.0":
                # v2.0：使用配置文件方式
                conf_lines = self._build_ossfs_v2_config_lines(
                    volume=volume,
                    endpoint_url=endpoint_url,
                    prefix=prefix,
                )
                conf_file = os.path.join(
                    tempfile.gettempdir(),
                    f"opensandbox-ossfs2-{uuid4().hex}.conf",
                )
                with open(conf_file, "w", encoding="utf-8") as f:
                    f.write("\n".join(conf_lines) + "\n")
                os.chmod(conf_file, 0o600)  # 设置只读权限
                cmd = self._build_ossfs_v2_mount_command(backend_path, conf_file)
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "code": SandboxErrorCodes.INVALID_OSSFS_VERSION,
                        "message": (
                            f"卷 '{volume.name}': 不支持的 OSSFS 版本 '{version}'。"
                        ),
                    },
                )
            # 执行挂载命令
            self._run_ossfs_mount_command(cmd, volume.name)
        except OSError as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={
                    "code": SandboxErrorCodes.OSSFS_MOUNT_FAILED,
                    "message": (
                        f"卷 '{volume.name}': 执行 ossfs 命令失败：{exc}"
                    ),
                },
            ) from exc
        finally:
            # 清理临时文件
            if passwd_file:
                try:
                    os.remove(passwd_file)
                except OSError:
                    pass
            if conf_file:
                try:
                    os.remove(conf_file)
                except OSError:
                    pass

    def _ensure_ossfs_mounted(self, volume_or_mount_key) -> str:
        """
        确保 OSSFS 后端路径已挂载，返回挂载键。

        本方法使用引用计数管理挂载：
        - 如果挂载已存在，增加引用计数
        - 如果挂载不存在，执行挂载操作

        Args:
            volume_or_mount_key: 卷对象或挂载键字符串

        Returns:
            str: 挂载键（backend_path）

        Raises:
            HTTPException: 如果挂载失败
        """
        if isinstance(volume_or_mount_key, str):
            # 如果传入的是字符串，直接作为挂载键
            mount_key = volume_or_mount_key
            backend_path = volume_or_mount_key
            volume = None
        else:
            # 如果传入的是卷对象，解析路径
            volume = volume_or_mount_key
            backend_path, _ = self._resolve_ossfs_paths(volume)
            mount_key = backend_path

        with self._ossfs_mount_lock:
            current = self._ossfs_mount_ref_counts.get(mount_key, 0)
            if current > 0:
                # 挂载已存在，增加引用计数
                self._ossfs_mount_ref_counts[mount_key] = current + 1
                return mount_key

            # 检查是否已挂载（可能被外部挂载）
            if not os.path.ismount(backend_path):
                if volume is None:
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail={
                            "code": SandboxErrorCodes.OSSFS_MOUNT_FAILED,
                            "message": (
                                f"挂载 OSSFS 路径 '{mount_key}' 失败："
                                "缺少卷上下文。"
                            ),
                        },
                    )
                # 执行挂载
                self._mount_ossfs_backend_path(volume, backend_path)

            # 初始化引用计数为 1
            self._ossfs_mount_ref_counts[mount_key] = 1
            return mount_key

    def _release_ossfs_mount(self, mount_key: str) -> None:
        """
        释放一个引用计数，当引用计数归零时卸载挂载。

        Args:
            mount_key: 挂载键

        Raises:
            HTTPException: 如果卸载失败
        """
        with self._ossfs_mount_lock:
            current = self._ossfs_mount_ref_counts.get(mount_key, 0)
            if current <= 0:
                logger.warning(
                    "跳过未跟踪的 OSSFS 挂载键 '%s' 的卸载操作。",
                    mount_key,
                )
                return
            if current == 1:
                # 引用计数归零，移除记录并执行卸载
                self._ossfs_mount_ref_counts.pop(mount_key, None)
                should_unmount = True
            else:
                # 仍有其他引用，只减少计数
                self._ossfs_mount_ref_counts[mount_key] = current - 1
                should_unmount = False

        if not should_unmount or not os.path.ismount(mount_key):
            return

        # 尝试两种卸载命令（fusermount 用于 FUSE，umount 用于普通挂载）
        errors: list[str] = []
        for cmd in (["fusermount", "-u", mount_key], ["umount", mount_key]):
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
            if result.returncode == 0:
                return
            errors.append(result.stderr.strip() or "未知错误")

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": SandboxErrorCodes.OSSFS_UNMOUNT_FAILED,
                "message": f"卸载 OSSFS 路径 '{mount_key}' 失败：{'; '.join(errors)}",
            },
        )

    def _release_ossfs_mounts(self, mount_keys: list[str]) -> None:
        """
        批量释放多个 OSSFS 挂载。

        Args:
            mount_keys: 挂载键列表

        注意：如果某个挂载释放失败，只记录警告日志，继续处理其他挂载。
        """
        for key in mount_keys:
            try:
                self._release_ossfs_mount(key)
            except HTTPException as exc:
                logger.warning("释放 OSSFS 挂载 %s 失败：%s", key, exc.detail)

    def _prepare_ossfs_mounts(self, volumes: Optional[list]) -> list[str]:
        """
        准备 OSSFS 挂载，返回挂载键列表。

        Args:
            volumes: 卷列表（可选）

        Returns:
            list[str]: 挂载键列表

        Raises:
            HTTPException: 如果挂载失败

        注意：如果挂载失败，会自动回滚已准备的挂载。
        """
        if not volumes:
            return []
        key_to_volume: dict[str, Any] = {}
        prepared_mount_keys: list[str] = []
        for volume in volumes:
            if volume.ossfs is not None:
                mount_key, _ = self._resolve_ossfs_paths(volume)
                if mount_key not in key_to_volume:
                    key_to_volume[mount_key] = volume
        try:
            for mount_key, volume in key_to_volume.items():
                self._ensure_ossfs_mounted(volume)
                prepared_mount_keys.append(mount_key)
            return list(key_to_volume.keys())
        except Exception:
            # 回滚已准备的挂载
            self._release_ossfs_mounts(prepared_mount_keys)
            raise

    def _validate_ossfs_volume(self, volume) -> None:
        """
        Docker 特定的 OSSFS 后端验证。

        确保内联凭证和路径语义有效。

        Args:
            volume: 卷配置对象

        Raises:
            HTTPException: 如果验证失败

        验证内容：
            1. 操作系统必须是 Linux（需要 FUSE 支持）
            2. 必须提供访问凭证（accessKeyId 和 accessKeySecret）
            3. 路径解析必须有效
        """
        # OSSFS 需要 FUSE 支持，Windows 不支持
        if os.name == "nt":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": SandboxErrorCodes.INVALID_PARAMETER,
                    "message": (
                        "Docker 运行时下的 OSSFS 后端需要 Linux 主机和 FUSE 支持。"
                        "在 Windows 上运行 OpenSandbox Server 不支持 OSSFS 挂载。"
                    ),
                },
            )

        # 验证凭证
        if not volume.ossfs.access_key_id or not volume.ossfs.access_key_secret:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": SandboxErrorCodes.INVALID_OSSFS_CREDENTIALS,
                    "message": (
                        "OSSFS 需要内联凭证："
                        "必须提供 accessKeyId 和 accessKeySecret。"
                    ),
                },
            )

        # 验证路径解析
        self._resolve_ossfs_paths(volume)
