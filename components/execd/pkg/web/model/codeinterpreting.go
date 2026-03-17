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

import (
	"encoding/json"
	"errors"
	"fmt"
	"strings"

	"github.com/go-playground/validator/v10"

	"github.com/alibaba/opensandbox/execd/pkg/jupyter/execute"
)

// RunCodeRequest 表示代码执行请求
//
// RunCodeRequest 用于客户端向服务器发送代码执行请求，
// 包含执行上下文和要执行的代码。
type RunCodeRequest struct {
	// Context 执行上下文信息
	Context CodeContext `json:"context,omitempty"`

	// Code 要执行的代码（必填）
	Code string `json:"code" validate:"required"`
}

// Validate 验证请求的有效性
//
// 本方法使用 validator 库验证请求结构体的字段，
// 确保必填字段已提供且格式正确。
//
// 返回值:
//   - error: 验证错误（如有）
func (r *RunCodeRequest) Validate() error {
	validate := validator.New()
	return validate.Struct(r)
}

// CodeContext 代码执行上下文
//
// CodeContext 封装了执行会话的元数据，包括会话 ID、
// 语言类型和工作目录等信息。
type CodeContext struct {
	// ID 会话 ID
	ID string `json:"id,omitempty"`

	// CodeContextRequest 内联上下文请求参数
	CodeContextRequest `json:",inline"`
}

// CodeContextRequest 代码上下文请求参数
//
// CodeContextRequest 用于指定创建执行上下文时的参数，
// 包括语言类型和工作目录。
type CodeContextRequest struct {
	// Language 编程语言类型
	Language string `json:"language,omitempty"`

	// Cwd 工作目录
	Cwd string `json:"cwd,omitempty"`
}

// RunCommandRequest 表示 shell 命令执行请求
//
// RunCommandRequest 用于客户端向服务器发送 shell 命令执行请求，
// 支持同步和后台执行模式。
type RunCommandRequest struct {
	// Command 要执行的 shell 命令（必填）
	Command string `json:"command" validate:"required"`

	// Cwd 命令执行的工作目录（可选）
	Cwd string `json:"cwd,omitempty"`

	// Background 是否在后台执行（可选）
	// true 表示后台执行，立即返回；false 表示同步执行，等待完成
	Background bool `json:"background,omitempty"`

	// TimeoutMs 执行超时时间（毫秒）
	// 0 表示使用服务器默认超时时间
	TimeoutMs int64 `json:"timeout,omitempty" validate:"omitempty,gte=1"`

	// Uid 执行命令的用户 ID（可选）
	Uid *uint32 `json:"uid,omitempty"`

	// Gid 执行命令的组 ID（可选）
	// 注意：当提供 Gid 时，必须同时提供 Uid
	Gid *uint32 `json:"gid,omitempty"`

	// Envs 环境变量映射（可选）
	// 这些变量会被添加到命令执行环境中
	Envs map[string]string `json:"envs,omitempty"`
}

// Validate 验证命令请求的有效性
//
// 本方法验证请求结构体的字段，确保：
// 1. 必填字段已提供
// 2. TimeoutMs 大于等于 1（如果提供）
// 3. 当提供 Gid 时，必须同时提供 Uid
//
// 返回值:
//   - error: 验证错误（如有）
func (r *RunCommandRequest) Validate() error {
	validate := validator.New()
	if err := validate.Struct(r); err != nil {
		return err
	}
	// 验证 Uid 和 Gid 的依赖关系
	if r.Gid != nil && r.Uid == nil {
		return errors.New("uid is required when gid is provided")
	}
	return nil
}

// ServerStreamEventType 服务器流式事件类型
//
// ServerStreamEventType 定义了 SSE（Server-Sent Events）
// 支持的事件类型，用于向客户端推送执行过程中的各种状态。
type ServerStreamEventType string

const (
	// StreamEventTypeInit 初始化事件
	// 在执行开始时发送，包含会话 ID 等信息
	StreamEventTypeInit ServerStreamEventType = "init"

	// StreamEventTypeStatus 状态更新事件
	// 在内核状态变化时发送（如 busy、idle）
	StreamEventTypeStatus ServerStreamEventType = "status"

	// StreamEventTypeError 错误事件
	// 在执行发生错误时发送
	StreamEventTypeError ServerStreamEventType = "error"

	// StreamEventTypeStdout 标准输出事件
	// 在有标准输出时发送
	StreamEventTypeStdout ServerStreamEventType = "stdout"

	// StreamEventTypeStderr 标准错误事件
	// 在有标准错误输出时发送
	StreamEventTypeStderr ServerStreamEventType = "stderr"

	// StreamEventTypeResult 执行结果事件
	// 在有执行结果时发送
	StreamEventTypeResult ServerStreamEventType = "result"

	// StreamEventTypeComplete 执行完成事件
	// 在执行完成时发送，包含执行时间等信息
	StreamEventTypeComplete ServerStreamEventType = "execution_complete"

	// StreamEventTypeCount 执行计数事件
	// 在返回执行计数时发送
	StreamEventTypeCount ServerStreamEventType = "execution_count"

	// StreamEventTypePing Ping 事件
	// 用于心跳检测
	StreamEventTypePing ServerStreamEventType = "ping"
)

// ServerStreamEvent 服务器流式事件
//
// ServerStreamEvent 是 SSE 客户端推送事件的数据结构，
// 包含事件类型、内容、执行状态等信息。
type ServerStreamEvent struct {
	// Type 事件类型
	Type ServerStreamEventType `json:"type,omitempty"`

	// Text 事件文本内容（如输出内容）
	Text string `json:"text,omitempty"`

	// ExecutionCount 执行计数
	ExecutionCount int `json:"execution_count,omitempty"`

	// ExecutionTime 执行耗时（毫秒）
	ExecutionTime int64 `json:"execution_time,omitempty"`

	// Timestamp 时间戳
	Timestamp int64 `json:"timestamp,omitempty"`

	// Results 执行结果数据（map 格式）
	Results map[string]any `json:"results,omitempty"`

	// Error 错误信息（如果有）
	Error *execute.ErrorOutput `json:"error,omitempty"`
}

// ToJSON 将事件序列化为 JSON 字节数组
//
// 本方法用于 SSE 事件中，将事件数据转换为 JSON 格式发送给客户端。
//
// 返回值:
//   - []byte: JSON 格式的字节数组
func (s ServerStreamEvent) ToJSON() []byte {
	bytes, _ := json.Marshal(s)
	return bytes
}

// Summary 生成事件的简洁文本摘要
//
// 本方法生成易于日志记录的文本摘要，不包含 JSON 格式，
// 适合在服务器端日志中记录事件信息。
//
// 返回值:
//   - string: 事件摘要字符串
func (s ServerStreamEvent) Summary() string {
	parts := []string{fmt.Sprintf("type=%s", s.Type)}
	if s.Text != "" {
		parts = append(parts, fmt.Sprintf("text=%s", truncateString(s.Text, 100)))
	}
	if s.ExecutionTime > 0 {
		parts = append(parts, fmt.Sprintf("elapsed_ms=%d", s.ExecutionTime))
	}
	if len(s.Results) > 0 {
		parts = append(parts, fmt.Sprintf("results=%d", len(s.Results)))
	}
	if s.Error != nil {
		errLabel := s.Error.EName
		if errLabel == "" {
			errLabel = "error"
		}
		parts = append(parts, fmt.Sprintf("error=%s: %s", errLabel, truncateString(s.Error.EValue, 80)))
	}
	return strings.Join(parts, " ")
}

// truncateString 截断字符串到指定长度
//
// 本函数用于限制输出长度，避免过长的内容影响日志可读性。
//
// 参数:
//   - value: 要截断的字符串
//   - maxCount: 最大长度
//
// 返回值:
//   - string: 截断后的字符串（如果超过最大长度，末尾添加 "..."）
func truncateString(value string, maxCount int) string {
	if maxCount <= 0 || len(value) <= maxCount {
		return value
	}
	return value[:maxCount] + "..."
}
