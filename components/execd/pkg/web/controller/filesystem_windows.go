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

//go:build windows
// +build windows

package controller

import (
	"fmt"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"

	"github.com/gin-gonic/gin"

	"github.com/alibaba/opensandbox/execd/pkg/util/glob"
	"github.com/alibaba/opensandbox/execd/pkg/web/model"
)

// FilesystemController 文件系统控制器
//
// FilesystemController 处理文件系统相关的 API 请求，
// 提供文件查询、上传、下载、删除、重命名等功能。
type FilesystemController struct {
	// basicController 基础控制器嵌入
	*basicController
}

// NewFilesystemController 创建文件系统控制器实例
//
// 参数:
//   - ctx: Gin 上下文
//
// 返回值:
//   - *FilesystemController: 新创建的控制器实例
func NewFilesystemController(ctx *gin.Context) *FilesystemController {
	return &FilesystemController{basicController: newBasicController(ctx)}
}

// handleFileError 处理文件操作错误
//
// 本方法根据错误类型返回相应的 HTTP 响应：
//   - 文件不存在：返回 404 Not Found
//   - 其他错误：返回 500 Internal Server Error
//
// 参数:
//   - err: 文件操作错误
func (c *FilesystemController) handleFileError(err error) {
	if os.IsNotExist(err) {
		c.RespondError(
			http.StatusNotFound,
			model.ErrorCodeFileNotFound,
			fmt.Sprintf("file not found. %v", err),
		)
	} else {
		c.RespondError(
			http.StatusInternalServerError,
			model.ErrorCodeRuntimeError,
			fmt.Sprintf("error accessing file: %v", err),
		)
	}
}

// GetFilesInfo 获取多个文件的元数据
//
// 本接口根据查询参数 path 获取指定文件的详细信息，
// 包括大小、修改时间、创建时间和权限。
func (c *FilesystemController) GetFilesInfo() {
	paths := c.ctx.QueryArray("path")
	if len(paths) == 0 {
		c.RespondSuccess(make(map[string]model.FileInfo))
		return
	}

	resp := make(map[string]model.FileInfo)
	for _, filePath := range paths {
		fileInfo, err := GetFileInfo(filePath)
		if err != nil {
			c.handleFileError(err)
			return
		}
		resp[filePath] = fileInfo
	}

	c.RespondSuccess(resp)
}

// RemoveFiles 删除多个文件
//
// 本接口根据查询参数 path 删除指定的文件。
// 文件不存在时不返回错误。
func (c *FilesystemController) RemoveFiles() {
	paths := c.ctx.QueryArray("path")
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

// ChmodFiles 修改多个文件的权限
//
// 本接口根据请求体中的文件路径和权限设置，
// 批量修改文件的权限模式。
func (c *FilesystemController) ChmodFiles() {
	var request map[string]model.Permission
	if err := c.bindJSON(&request); err != nil {
		c.RespondError(
			http.StatusBadRequest,
			model.ErrorCodeInvalidRequest,
			fmt.Sprintf("error parsing request, MAYBE invalid body format. %v", err),
		)
		return
	}

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

// RenameFiles 重命名或移动多个文件
//
// 本接口根据请求体中的源路径和目标路径，
// 批量重命名或移动文件。
func (c *FilesystemController) RenameFiles() {
	var request []model.RenameFileItem
	if err := c.bindJSON(&request); err != nil {
		c.RespondError(
			http.StatusBadRequest,
			model.ErrorCodeInvalidRequest,
			fmt.Sprintf("error parsing request, MAYBE invalid body format. %v", err),
		)
		return
	}

	for _, renameItem := range request {
		if err := RenameFile(renameItem); err != nil {
			c.handleFileError(err)
			return
		}
	}

	c.RespondSuccess(nil)
}

// MakeDirs 创建多个目录
//
// 本接口根据请求体中的目录路径和权限设置，
// 批量创建目录（包括父目录）。
func (c *FilesystemController) MakeDirs() {
	var request map[string]model.Permission
	if err := c.bindJSON(&request); err != nil {
		c.RespondError(
			http.StatusBadRequest,
			model.ErrorCodeInvalidRequest,
			fmt.Sprintf("error parsing request, MAYBE invalid body format. %v", err),
		)
		return
	}

	for dir, perm := range request {
		if err := MakeDir(dir, perm); err != nil {
			c.handleFileError(err)
			return
		}
	}

	c.RespondSuccess(nil)
}

// RemoveDirs 递归删除多个目录
//
// 本接口根据查询参数 path 删除指定的目录及其内容。
func (c *FilesystemController) RemoveDirs() {
	paths := c.ctx.QueryArray("path")
	for _, dir := range paths {
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

// SearchFiles 搜索匹配模式的文件
//
// 本接口在指定目录下搜索匹配 glob 模式的文件，
// 返回匹配文件的详细信息列表。
//
// 查询参数：
//   - path: 搜索起始目录
//   - pattern: glob 模式（可选，默认为 "**"）
func (c *FilesystemController) SearchFiles() {
	path := c.ctx.Query("path")
	if path == "" {
		c.RespondError(
			http.StatusBadRequest,
			model.ErrorCodeMissingQuery,
			"missing query parameter 'path'",
		)
		return
	}

	path, err := filepath.Abs(path)
	if err != nil {
		c.RespondError(
			http.StatusInternalServerError,
			model.ErrorCodeRuntimeError,
			fmt.Sprintf("error converting path %s to absolute. %v", path, err),
		)
		return
	}

	_, err = os.Stat(path)
	if err != nil {
		c.handleFileError(err)
		return
	}

	pattern := c.ctx.Query("pattern")
	if pattern == "" {
		pattern = "**"
	}

	files := make([]model.FileInfo, 0, 16)
	err = filepath.Walk(path, func(filePath string, info os.FileInfo, err error) error {
		if os.IsNotExist(err) {
			return nil
		}
		if err != nil {
			return fmt.Errorf("error accessing path %s: %w", filePath, err)
		}
		if info.IsDir() {
			return nil
		}

		match, err := glob.PathMatch(pattern, info.Name())
		if err != nil {
			return fmt.Errorf("invalid pattern %s: %w", pattern, err)
		}

		if match {
			files = append(files, model.FileInfo{
				Path:       filePath,
				Size:       info.Size(),
				ModifiedAt: info.ModTime(),
				CreatedAt:  getFileCreateTime(info),
				Permission: model.Permission{
					Owner: "",
					Group: "",
					Mode: func() int {
						mode := strconv.FormatInt(int64(info.Mode().Perm()), 8)
						i, _ := strconv.Atoi(mode)
						return i
					}(),
				},
			})
		}

		return nil
	})

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

// ReplaceContent 替换文件中的文本内容
//
// 本接口根据请求体中的文件路径和替换内容，
// 批量替换文件中的指定文本。
func (c *FilesystemController) ReplaceContent() {
	var request map[string]model.ReplaceFileContentItem
	if err := c.bindJSON(&request); err != nil {
		c.RespondError(
			http.StatusBadRequest,
			model.ErrorCodeInvalidRequest,
			fmt.Sprintf("error parsing request, MAYBE invalid body format. %v", err),
		)
		return
	}

	for file, item := range request {
		file, err := filepath.Abs(file)
		if err != nil {
			c.handleFileError(err)
			return
		}

		if _, err = os.Stat(file); err != nil {
			c.handleFileError(err)
			return
		}

		content, err := os.ReadFile(file)
		if err != nil {
			c.handleFileError(err)
			return
		}

		fileInfo, err := os.Stat(file)
		if err != nil {
			c.handleFileError(err)
			return
		}
		mode := fileInfo.Mode()

		newContent := strings.ReplaceAll(string(content), item.Old, item.New)

		err = os.WriteFile(file, []byte(newContent), mode)
		if err != nil {
			c.handleFileError(err)
			return
		}
	}

	c.RespondSuccess(nil)
}
