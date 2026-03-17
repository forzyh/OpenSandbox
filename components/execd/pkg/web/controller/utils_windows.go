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
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"time"

	"github.com/alibaba/opensandbox/execd/pkg/web/model"
)

// DeleteFile 删除指定文件（Windows 版本）
//
// 本函数删除指定路径的文件。如果文件不存在，不返回错误。
// 如果路径是目录，返回错误。
//
// 参数:
//   - filePath: 文件路径
//
// 返回值:
//   - error: 删除错误（如有）
func DeleteFile(filePath string) error {
	absPath, err := filepath.Abs(filePath)
	if err != nil {
		return fmt.Errorf("invalid path: %w", err)
	}

	fileInfo, err := os.Stat(absPath)
	if err != nil {
		if os.IsNotExist(err) {
			return nil
		}
		return err
	}

	if fileInfo.IsDir() {
		return fmt.Errorf("path is a directory: %s", filePath)
	}

	if err := os.Remove(absPath); err != nil {
		return fmt.Errorf("failed to remove file: %w", err)
	}

	return nil
}

// ChmodFile 修改文件权限（Windows 版本）
//
// 本函数设置文件的权限模式。在 Windows 上，所有权设置被忽略。
//
// 参数:
//   - file: 文件路径
//   - perms: 权限设置
//
// 返回值:
//   - error: 设置错误（如有）
func ChmodFile(file string, perms model.Permission) error {
	abs, err := filepath.Abs(file)
	if err != nil {
		return err
	}

	if perms.Mode != 0 {
		mode, err := strconv.ParseUint(strconv.Itoa(perms.Mode), 8, 32)
		if err != nil {
			return err
		}
		err = os.Chmod(abs, os.FileMode(mode))
		if err != nil {
			return err
		}
	}
	return SetFileOwnership(abs, perms.Owner, perms.Group)
}

// SetFileOwnership 设置文件所有权（Windows 版本）
//
// Windows 不支持 POSIX 所有权模型，此函数是占位符实现。
// 如需完整的 Windows ACL 支持，需要额外实现。
//
// 参数:
//   - _: 文件路径（未使用）
//   - _: 所有者（未使用）
//   - _: 组（未使用）
//
// 返回值:
//   - error: 始终返回 nil
func SetFileOwnership(_ string, _ string, _ string) error {
	// TODO: 如需支持 Windows ACL，可在此处添加实现
	return nil
}

// RenameFile 重命名/移动文件（Windows 版本）
//
// 本函数将文件从源路径移动到目标路径。
// 如果目标目录不存在，会自动创建。
//
// 参数:
//   - item: 重命名操作项
//
// 返回值:
//   - error: 重命名错误（如有）
func RenameFile(item model.RenameFileItem) error {
	srcPath, err := filepath.Abs(item.Src)
	if err != nil {
		return fmt.Errorf("invalid source path: %w", err)
	}

	dstPath, err := filepath.Abs(item.Dest)
	if err != nil {
		return fmt.Errorf("invalid destination path: %w", err)
	}

	if _, err := os.Stat(srcPath); os.IsNotExist(err) {
		return fmt.Errorf("source path not found: %s", item.Src)
	}

	dstDir := filepath.Dir(dstPath)

	if err := os.MkdirAll(dstDir, 0755); err != nil {
		return fmt.Errorf("failed to create destination directory: %w", err)
	}

	if _, err := os.Stat(dstPath); err == nil {
		return fmt.Errorf("destination path already exists: %s", item.Dest)
	}

	if err := os.Rename(srcPath, dstPath); err != nil {
		return fmt.Errorf("failed to rename file: %w", err)
	}

	return nil
}

// MakeDir 创建目录（Windows 版本）
//
// 本函数创建指定目录及其父目录，并设置权限。
//
// 参数:
//   - dir: 目录路径
//   - perm: 权限设置
//
// 返回值:
//   - error: 创建错误（如有）
func MakeDir(dir string, perm model.Permission) error {
	abs, err := filepath.Abs(dir)
	if err != nil {
		return err
	}
	err = os.MkdirAll(abs, os.ModePerm)
	if err != nil {
		return err
	}

	return ChmodFile(abs, perm)
}

// GetFileInfo 获取文件信息（Windows 版本）
//
// 本函数获取文件的详细信息，包括大小、时间和权限。
// Windows 版本返回空的 Owner 和 Group 字段。
//
// 参数:
//   - filePath: 文件路径
//
// 返回值:
//   - model.FileInfo: 文件信息
//   - error: 获取错误（如有）
func GetFileInfo(filePath string) (model.FileInfo, error) {
	absPath, err := filepath.Abs(filePath)
	if err != nil {
		return model.FileInfo{}, fmt.Errorf("invalid path %s: %w", filePath, err)
	}

	fileInfo, err := os.Stat(absPath)
	if err != nil {
		if os.IsNotExist(err) {
			return model.FileInfo{}, fmt.Errorf("file not found: %s", filePath)
		}
		return model.FileInfo{}, fmt.Errorf("error accessing file %s: %w", filePath, err)
	}

	// Windows 使用 Win32FileAttributeData 获取创建时间
	createdAt := getFileCreateTime(fileInfo)
	if data, ok := fileInfo.Sys().(*syscall.Win32FileAttributeData); ok && data != nil {
		createdAt = time.Unix(0, data.CreationTime.Nanoseconds())
	}

	mode := strconv.FormatInt(int64(fileInfo.Mode().Perm()), 8)

	return model.FileInfo{
		Path:       absPath,
		Size:       fileInfo.Size(),
		ModifiedAt: fileInfo.ModTime(),
		CreatedAt:  createdAt,
		Permission: model.Permission{
			Owner: "",
			Group: "",
			Mode: func() int {
				i, _ := strconv.Atoi(mode)
				return i
			}(),
		},
	}, nil
}

// SearchFileMetadata 在元数据映射中搜索文件
//
// 本函数通过文件名（而非完整路径）在元数据映射中搜索匹配项。
//
// 参数:
//   - metadata: 元数据映射
//   - filePath: 要搜索的文件路径
//
// 返回值:
//   - string: 匹配的路径
//   - model.FileMetadata: 元数据
//   - bool: 是否找到
func SearchFileMetadata(metadata map[string]model.FileMetadata, filePath string) (string, model.FileMetadata, bool) {
	base := filepath.Base(filePath)
	for path, info := range metadata {
		if filepath.Base(path) == base {
			return path, info, true
		}
	}

	return "", model.FileMetadata{}, false
}

// httpRange 表示 HTTP Range 请求的范围
type httpRange struct {
	start, length int64
}

// ParseRange 解析 HTTP Range 请求头
//
// 本函数解析 Range 请求头，支持以下格式：
//   - bytes=start-end: 指定起始和结束位置
//   - bytes=start-: 从 start 到文件末尾
//   - bytes=-n: 文件末尾的 n 个字节
//
// 参数:
//   - s: Range 请求头字符串
//   - size: 文件大小
//
// 返回值:
//   - []httpRange: 解析后的范围列表
//   - error: 解析错误（如有）
func ParseRange(s string, size int64) ([]httpRange, error) {
	if !strings.HasPrefix(s, "bytes=") {
		return nil, errors.New("invalid range")
	}

	ranges := strings.Split(s[6:], ",")
	result := make([]httpRange, 0, len(ranges))

	for _, ra := range ranges {
		ra = strings.TrimSpace(ra)
		if ra == "" {
			continue
		}
		i := strings.Index(ra, "-")
		if i < 0 {
			return nil, errors.New("invalid range")
		}
		start, end := strings.TrimSpace(ra[:i]), strings.TrimSpace(ra[i+1:])
		var r httpRange

		if start == "" {
			// suffix-length 格式：-n
			n, err := strconv.ParseInt(end, 10, 64)
			if err != nil || n < 0 {
				return nil, errors.New("invalid range")
			}
			if n > size {
				n = size
			}
			r.start = size - n
			r.length = size - r.start
		} else {
			// start-end 或 start- 格式
			i, err := strconv.ParseInt(start, 10, 64)
			if err != nil || i < 0 {
				return nil, errors.New("invalid range")
			}
			if end == "" {
				// start- 格式
				r.start = i
				r.length = size - i
			} else {
				// start-end 格式
				j, err := strconv.ParseInt(end, 10, 64)
				if err != nil || j < i {
					return nil, errors.New("invalid range")
				}
				r.start = i
				r.length = j - i + 1
			}
		}
		if r.start >= size {
			continue
		}
		if r.start+r.length > size {
			r.length = size - r.start
		}
		result = append(result, r)
	}
	return result, nil
}
