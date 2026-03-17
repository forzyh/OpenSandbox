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

package model

import "time"

// FileInfo 表示文件元数据
//
// FileInfo 封装了文件的完整信息，包括路径、大小、
// 修改时间、创建时间和权限信息。
type FileInfo struct {
	// Path 文件路径
	Path string `json:"path,omitempty"`

	// Size 文件大小（字节）
	Size int64 `json:"size"`

	// ModifiedAt 最后修改时间
	ModifiedAt time.Time `json:"modified_at,omitempty"`

	// CreatedAt 创建时间
	CreatedAt time.Time `json:"created_at,omitempty"`

	// Permission 权限信息（内联）
	Permission `json:",inline"`
}

// FileMetadata 文件元数据结构
//
// FileMetadata 用于文件操作请求中，包含文件路径和权限信息。
type FileMetadata struct {
	// Path 文件路径
	Path string `json:"path,omitempty"`

	// Permission 权限信息（内联）
	Permission `json:",inline"`
}

// Permission 表示文件所有权和权限模式
//
// Permission 封装了文件的权限信息，包括所有者、所属组和权限模式。
type Permission struct {
	// Owner 文件所有者
	Owner string `json:"owner"`

	// Group 文件所属组
	Group string `json:"group"`

	// Mode 权限模式（八进制表示，如 0755）
	Mode int `json:"mode"`
}

// RenameFileItem 表示文件重命名操作
//
// RenameFileItem 用于批量重命名操作的请求项，
// 包含源路径和目标路径。
type RenameFileItem struct {
	// Src 源文件路径
	Src string `json:"src,omitempty"`

	// Dest 目标文件路径
	Dest string `json:"dest,omitempty"`
}

// ReplaceFileContentItem 表示文件内容替换操作
//
// ReplaceFileContentItem 用于文件内容编辑操作，
// 指定要被替换的旧内容和新的内容。
type ReplaceFileContentItem struct {
	// Old 要被替换的旧内容
	Old string `json:"old,omitempty"`

	// New 替换后的新内容
	New string `json:"new,omitempty"`
}
