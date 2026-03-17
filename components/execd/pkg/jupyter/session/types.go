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

// Package session 提供管理 Jupyter 会话的功能
//
// 本包定义了与 Jupyter 会话相关的数据结构和接口，包括：
//   - Session: 会话信息结构体
//   - KernelInfo: 内核信息结构体
//   - SessionCreateRequest: 创建会话请求
//   - SessionUpdateRequest: 更新会话请求
//   - SessionOptions: 会话创建/更新选项
//
// Jupyter 会话是用户与内核交互的上下文环境，每个会话关联一个内核实例。
// 通过会话管理 API，可以创建、查询、修改和删除会话。
package session

import (
	"time"
)

// Session 表示一个 Jupyter 会话
//
// Session 结构体封装了会话的所有属性信息，包括会话 ID、路径、名称、
// 类型、关联的内核信息以及时间戳等。
//
// JSON 标签说明：
//   - id: 会话唯一标识符
//   - path: 会话关联的路径（通常是 notebook 文件路径）
//   - name: 会话名称
//   - type: 会话类型（notebook、console 等）
//   - kernel: 关联的内核信息
//   - created: 创建时间（可选）
//   - last_modified: 最后修改时间（可选）
type Session struct {
	// ID 会话的唯一标识符
	ID string `json:"id"`

	// Path 会话关联的路径，通常是 notebook 文件的路径
	Path string `json:"path"`

	// Name 会话的名称
	Name string `json:"name"`

	// Type 会话类型，如 "notebook"（笔记本）、"console"（控制台）等
	Type string `json:"type"`

	// Kernel 与会话关联的内核信息
	Kernel *KernelInfo `json:"kernel"`

	// CreatedAt 会话创建的时间戳
	// omitempty 表示空值时在 JSON 中省略
	CreatedAt time.Time `json:"created,omitempty"`

	// LastModified 会话最后修改的时间戳
	// omitempty 表示空值时在 JSON 中省略
	LastModified time.Time `json:"last_modified,omitempty"`
}

// KernelInfo 包含内核的基本信息
//
// KernelInfo 结构体提供了内核的状态信息，包括内核 ID、名称、
// 最后活动时间、连接数和执行状态等。
type KernelInfo struct {
	// ID 内核的唯一标识符
	ID string `json:"id"`

	// Name 内核名称，如 "python3"、"ir"（R 语言内核）等
	Name string `json:"name"`

	// LastActivity 内核最后活动的时间戳
	LastActivity time.Time `json:"last_activity,omitempty"`

	// Connections 当前连接到内核的客户端数量
	Connections int `json:"connections,omitempty"`

	// ExecutionState 内核的执行状态
	// 常见值："idle"（空闲）、"busy"（忙碌）、"starting"（启动中）
	ExecutionState string `json:"execution_state,omitempty"`
}

// SessionCreateRequest 创建新会话的请求结构
//
// SessionCreateRequest 用于向 Jupyter 服务器发送创建会话的请求，
// 包含会话的基本属性和要启动的内核规格。
type SessionCreateRequest struct {
	// Path 会话关联的路径，通常是 notebook 文件路径
	Path string `json:"path"`

	// Name 会话名称（可选）
	Name string `json:"name,omitempty"`

	// Type 会话类型，默认为 "notebook"（可选）
	Type string `json:"type,omitempty"`

	// Kernel 要启动的内核规格（可选）
	Kernel *KernelSpec `json:"kernel,omitempty"`
}

// KernelSpec 包含内核规格信息
//
// KernelSpec 用于指定要创建或重用的内核，可以通过 Name 指定内核类型，
// 或通过 ID 指定重用已有的内核实例。
type KernelSpec struct {
	// Name 内核名称，如 "python3"、"ir" 等
	Name string `json:"name"`

	// ID 内核的唯一标识符（可选）
	// 当提供 ID 时，表示重用已有的内核实例，而不是创建新内核
	ID string `json:"id,omitempty"`
}

// SessionUpdateRequest 更新现有会话的请求结构
//
// SessionUpdateRequest 用于修改会话的属性，所有字段均为可选，
// 只修改提供的字段，未提供的字段保持不变。
type SessionUpdateRequest struct {
	// Path 新的会话路径（可选）
	Path string `json:"path,omitempty"`

	// Name 新的会话名称（可选）
	Name string `json:"name,omitempty"`

	// Type 新的会话类型（可选）
	Type string `json:"type,omitempty"`

	// Kernel 新的内核规格（可选）
	Kernel *KernelSpec `json:"kernel,omitempty"`
}

// SessionListResponse 表示列出会话的响应类型
//
// SessionListResponse 是 Session 指针切片的别名，
// 用于表示从服务器获取的所有活动会话列表。
type SessionListResponse []*Session

// SessionOptions 包含创建或更新会话的选项
//
// SessionOptions 提供了更灵活的会话配置选项，支持
// 指定会话名称、路径、类型以及内核选择等。
type SessionOptions struct {
	// Name 会话名称
	Name string

	// Path 会话关联的路径
	Path string

	// Type 会话类型，默认为 "notebook"
	Type string

	// KernelName 要使用的内核名称，如 "python3"、"ir" 等
	KernelName string

	// KernelID 要重用的现有内核 ID（如果提供，将忽略 KernelName）
	// 此选项用于将新会话关联到已有的内核实例
	KernelID string
}

// DefaultSessionType 默认会话类型常量
//
// 当创建会话时未指定类型时，使用此默认值 "notebook"。
const DefaultSessionType = "notebook"
