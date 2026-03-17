// Copyright 2025 Alibaba Group Holding Ltd.
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

//go:build !windows
// +build !windows

/*
Package controller 提供 HTTP 控制器层。

本文件（filesystem.go）提供文件系统操作相关的 HTTP 控制器方法。

注意：此文件仅在非 Windows 系统上编译（通过 build 标签控制）。

主要功能：
1. 文件信息获取（GetFilesInfo）
2. 文件删除（RemoveFiles）
3. 文件权限修改（ChmodFiles）
4. 文件重命名/移动（RenameFiles）
5. 目录创建（MakeDirs）
6. 目录删除（RemoveDirs）
7. 文件搜索（SearchFiles）
8. 文件内容替换（ReplaceContent）
9. 文件上传（UploadFile）- 在其他文件中定义
10. 文件下载（DownloadFile）- 在其他文件中定义

安全考虑：
- 所有路径操作都应进行合法性校验
- 防止路径遍历攻击（如 ../../../etc/passwd）
- 权限检查确保用户只能访问授权的文件
*/
package controller

import (
	"fmt"
	"net/http"
	"os"
	"os/user"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"

	"github.com/gin-gonic/gin"

	"github.com/alibaba/opensandbox/execd/pkg/util/glob" // 文件路径匹配工具
	"github.com/alibaba/opensandbox/execd/pkg/web/model" // 数据模型
)

// FilesystemController 文件系统控制器，处理所有文件操作相关的 HTTP 请求。
//
// 该控制器提供完整的文件系统操作能力：
//   - 文件/目录的增删改查
//   - 权限管理
//   - 内容搜索和替换
//   - 文件上传下载
//
// 结构体字段：
//   - basicController: 基础控制器，提供通用的 HTTP 处理方法
type FilesystemController struct {
	*basicController
}

// NewFilesystemController 创建新的文件系统控制器实例。
//
// 参数 ctx: Gin HTTP 上下文，包含请求和响应信息
// 返回值：初始化好的控制器实例
func NewFilesystemController(ctx *gin.Context) *FilesystemController {
	return &FilesystemController{basicController: newBasicController(ctx)}
}

// handleFileError 统一处理文件操作错误。
//
// 根据错误类型返回不同的 HTTP 状态码：
//   - 文件不存在：返回 404
//   - 其他错误：返回 500
//
// 参数 err: 文件操作返回的错误
func (c *FilesystemController) handleFileError(err error) {
	// 判断是否为文件不存在错误
	if os.IsNotExist(err) {
		// 返回 404 Not Found
		c.RespondError(
			http.StatusNotFound,
			model.ErrorCodeFileNotFound,
			fmt.Sprintf("file not found. %v", err),
		)
	} else {
		// 其他错误返回 500 Internal Server Error
		c.RespondError(
			http.StatusInternalServerError,
			model.ErrorCodeRuntimeError,
			fmt.Sprintf("error accessing file: %v", err),
		)
	}
}

// GetFilesInfo 获取文件的元信息。
//
// 支持批量获取多个文件的信息。
//
// 查询参数：
//   - path: 文件路径（可重复，获取多个文件）
//
// 响应格式：
//   {
//     "/path/to/file1": {
//       "path": "/path/to/file1",
//       "size": 1024,
//       "modifiedAt": "2025-01-01T00:00:00Z",
//       "createdAt": "2025-01-01T00:00:00Z",
//       "permission": {
//         "owner": "user",
//         "group": "group",
//         "mode": 755
//       }
//     },
//     ...
//   }
func (c *FilesystemController) GetFilesInfo() {
	// 获取所有 path 查询参数
	// 例如：?path=/file1&path=/file2
	paths := c.ctx.QueryArray("path")

	// 如果没有提供任何路径，返回空对象
	if len(paths) == 0 {
		c.RespondSuccess(make(map[string]model.FileInfo))
		return
	}

	// 构建响应映射
	resp := make(map[string]model.FileInfo)

	// 遍历每个路径，获取文件信息
	for _, filePath := range paths {
		fileInfo, err := GetFileInfo(filePath)
		if err != nil {
			// 遇到错误立即返回
			c.handleFileError(err)
			return
		}
		resp[filePath] = fileInfo
	}

	c.RespondSuccess(resp)
}

// RemoveFiles 删除文件。
//
// 支持批量删除多个文件。
// 注意：此方法只能删除文件，不能删除目录。
//
// 查询参数：
//   - path: 文件路径（可重复，删除多个文件）
func (c *FilesystemController) RemoveFiles() {
	// 获取所有 path 查询参数
	paths := c.ctx.QueryArray("path")

	// 遍历并删除每个文件
	for _, filePath := range paths {
		if err := DeleteFile(filePath); err != nil {
			c.RespondError(
				http.StatusInternalServerError,
				model.ErrorCodeRuntimeError,
				fmt.Sprintf("error removing file %s. %v", filePath, err),
			)
			return
		}
	}

	c.RespondSuccess(nil)
}

// ChmodFiles 修改文件权限。
//
// 支持批量修改多个文件的权限。
//
// 请求体格式（JSON）：
//   {
//     "/path/to/file1": {
//       "owner": "user",
//       "group": "group",
//       "mode": 755
//     },
//     "/path/to/file2": { ... }
//   }
func (c *FilesystemController) ChmodFiles() {
	// 解析请求体
	// 键为文件路径，值为权限信息
	var request map[string]model.Permission
	if err := c.bindJSON(&request); err != nil {
		c.RespondError(
			http.StatusBadRequest,
			model.ErrorCodeInvalidRequest,
			fmt.Sprintf("error parsing request, MAYBE invalid body format. %v", err),
		)
		return
	}

	// 遍历并修改每个文件的权限
	for file, item := range request {
		err := ChmodFile(file, item)
		if err != nil {
			c.RespondError(
				http.StatusInternalServerError,
				model.ErrorCodeRuntimeError,
				fmt.Sprintf("error changing permissions for %s. %v", file, err),
			)
			return
		}
	}

	c.RespondSuccess(nil)
}

// RenameFiles 重命名或移动文件。
//
// 支持批量操作多个文件。
//
// 请求体格式（JSON 数组）：
//   [
//     {
//       "from": "/path/to/old",
//       "to": "/path/to/new"
//     },
//     ...
//   ]
func (c *FilesystemController) RenameFiles() {
	// 解析请求体
	var request []model.RenameFileItem
	if err := c.bindJSON(&request); err != nil {
		c.RespondError(
			http.StatusBadRequest,
			model.ErrorCodeInvalidRequest,
			fmt.Sprintf("error parsing request, MAYBE invalid body format. %v", err),
		)
		return
	}

	// 遍历并执行每个重命名操作
	for _, renameItem := range request {
		if err := RenameFile(renameItem); err != nil {
			c.handleFileError(err)
			return
		}
	}

	c.RespondSuccess(nil)
}

// MakeDirs 创建目录。
//
// 支持批量创建多个目录，可为每个目录指定权限。
//
// 请求体格式（JSON）：
//   {
//     "/path/to/dir1": {
//       "owner": "user",
//       "group": "group",
//       "mode": 755
//     },
//     "/path/to/dir2": { ... }
//   }
func (c *FilesystemController) MakeDirs() {
	// 解析请求体
	// 键为目录路径，值为权限信息
	var request map[string]model.Permission
	if err := c.bindJSON(&request); err != nil {
		c.RespondError(
			http.StatusBadRequest,
			model.ErrorCodeInvalidRequest,
			fmt.Sprintf("error parsing request, MAYBE invalid body format. %v", err),
		)
		return
	}

	// 遍历并创建每个目录
	for dir, perm := range request {
		if err := MakeDir(dir, perm); err != nil {
			c.handleFileError(err)
			return
		}
	}

	c.RespondSuccess(nil)
}

// RemoveDirs 删除目录。
//
// 支持批量删除多个目录。
// 此方法会递归删除目录及其所有内容（类似 rm -rf）。
//
// 查询参数：
//   - path: 目录路径（可重复，删除多个目录）
func (c *FilesystemController) RemoveDirs() {
	// 获取所有 path 查询参数
	paths := c.ctx.QueryArray("path")

	// 遍历并删除每个目录
	for _, dir := range paths {
		// os.RemoveAll 会递归删除目录及其中的所有内容
		if err := os.RemoveAll(dir); err != nil {
			c.RespondError(
				http.StatusInternalServerError,
				model.ErrorCodeRuntimeError,
				fmt.Sprintf("error removing directory %s. %v", dir, err),
			)
			return
		}
	}

	c.RespondSuccess(nil)
}

// SearchFiles 搜索文件。
//
// 在指定目录下搜索匹配模式的文件。
// 支持 glob 风格的通配符匹配（如 *.go, **/*.py）。
//
// 查询参数：
//   - path: 搜索的根目录（必需）
//   - pattern: 匹配模式（可选，默认为 "**" 匹配所有文件）
//
// 响应格式（JSON 数组）：
//   [
//     {
//       "path": "/path/to/file.go",
//       "size": 1024,
//       "modifiedAt": "...",
//       "createdAt": "...",
//       "permission": { ... }
//     },
//     ...
//   ]
func (c *FilesystemController) SearchFiles() {
	// 获取搜索路径参数
	path := c.ctx.Query("path")

	// 验证路径参数
	if path == "" {
		c.RespondError(
			http.StatusBadRequest,
			model.ErrorCodeMissingQuery,
			"missing query parameter 'path'",
		)
		return
	}

	// 将路径转换为绝对路径
	// 确保路径解析的一致性，避免相对路径带来的问题
	path, err := filepath.Abs(path)
	if err != nil {
		c.RespondError(
			http.StatusInternalServerError,
			model.ErrorCodeRuntimeError,
			fmt.Sprintf("error converting path %s to absolute. %v", path, err),
		)
		return
	}

	// 检查路径是否存在
	_, err = os.Stat(path)
	if err != nil {
		c.handleFileError(err)
		return
	}

	// 获取匹配模式参数，默认为 "**"（匹配所有文件）
	pattern := c.ctx.Query("pattern")
	if pattern == "" {
		pattern = "**"
	}

	// 初始化结果切片，预分配容量以提高性能
	files := make([]model.FileInfo, 0, 16)

	// 递归遍历目录树
	// filepath.Walk 会深度优先遍历目录，对每个文件/目录调用回调函数
	err = filepath.Walk(path, func(filePath string, info os.FileInfo, err error) error {
		// 处理路径不存在的情况（可能是遍历过程中被删除）
		if os.IsNotExist(err) {
			return nil // 忽略此错误，继续遍历
		}
		if err != nil {
			return fmt.Errorf("error accessing path %s: %w", filePath, err)
		}

		// 跳过目录，只处理文件
		if info.IsDir() {
			return nil
		}

		// 检查文件名是否匹配模式
		match, err := glob.PathMatch(pattern, info.Name())
		if err != nil {
			return fmt.Errorf("invalid pattern %s: %w", pattern, err)
		}

		// 如果匹配，收集文件信息
		if match {
			// 获取系统特定的文件信息（用于获取 UID/GID）
			// Sys() 返回 interface{}，需要类型断言
			sys := info.Sys().(*syscall.Stat_t)

			// 根据 UID 查找用户名
			owner, err := user.LookupId(strconv.FormatUint(uint64(sys.Uid), 10))
			if err != nil {
				return fmt.Errorf("error lookup owner for file %s: %w", filePath, err)
			}

			// 根据 GID 查找组名
			group, err := user.LookupGroupId(strconv.FormatUint(uint64(sys.Gid), 10))
			if err != nil {
				return fmt.Errorf("error lookup group for file %s: %w", filePath, err)
			}

			// 构建文件信息对象
			files = append(files, model.FileInfo{
				Path:       filePath,                           // 完整路径
				Size:       info.Size(),                        // 文件大小（字节）
				ModifiedAt: info.ModTime(),                     // 最后修改时间
				CreatedAt:  getFileCreateTime(info),            // 创建时间（通过辅助函数获取）
				Permission: model.Permission{
					Owner: owner.Username, // 所有者用户名
					Group: group.Name,     // 所属组名
					Mode: func() int {
						// 将权限模式转换为八进制表示（如 755）
						mode := strconv.FormatInt(int64(info.Mode().Perm()), 8)
						i, _ := strconv.Atoi(mode)
						return i
					}(),
				},
			})
		}

		return nil
	})

	// 检查遍历是否出错
	if err != nil {
		c.RespondError(
			http.StatusInternalServerError,
			model.ErrorCodeRuntimeError,
			fmt.Sprintf("error searching files. %v", err),
		)
		return
	}

	c.RespondSuccess(files)
}

// ReplaceContent 替换文件内容。
//
// 批量替换多个文件中的指定文本内容。
// 使用简单的字符串替换，不支持正则表达式。
//
// 请求体格式（JSON）：
//   {
//     "/path/to/file1": {
//       "old": "old text",
//       "new": "new text"
//     },
//     "/path/to/file2": { ... }
//   }
func (c *FilesystemController) ReplaceContent() {
	// 解析请求体
	var request map[string]model.ReplaceFileContentItem
	if err := c.bindJSON(&request); err != nil {
		c.RespondError(
			http.StatusBadRequest,
			model.ErrorCodeInvalidRequest,
			fmt.Sprintf("error parsing request, MAYBE invalid body format. %v", err),
		)
		return
	}

	// 遍历并处理每个文件
	for file, item := range request {
		// 转换为绝对路径
		file, err := filepath.Abs(file)
		if err != nil {
			c.handleFileError(err)
			return
		}

		// 检查文件是否存在
		if _, err = os.Stat(file); err != nil {
			c.handleFileError(err)
			return
		}

		// 读取文件内容
		content, err := os.ReadFile(file)
		if err != nil {
			c.handleFileError(err)
			return
		}

		// 获取文件权限模式（用于写入时保持原权限）
		fileInfo, err := os.Stat(file)
		if err != nil {
			c.handleFileError(err)
			return
		}
		mode := fileInfo.Mode()

		// 执行字符串替换
		// strings.ReplaceAll 会替换所有出现的旧字符串
		newContent := strings.ReplaceAll(string(content), item.Old, item.New)

		// 写回文件，保持原权限
		err = os.WriteFile(file, []byte(newContent), mode)
		if err != nil {
			c.handleFileError(err)
			return
		}
	}

	c.RespondSuccess(nil)
}
