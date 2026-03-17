// Copyright 2026 Alibaba Group Holding Ltd.
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
	"github.com/go-playground/validator/v10"
)

// CreateSessionRequest 表示创建 Bash 会话的请求
//
// CreateSessionRequest 用于客户端向服务器请求创建一个新的 Bash 会话。
// Bash 会话是一个持久的 shell 环境，支持有状态的命令执行。
type CreateSessionRequest struct {
	// Cwd 会话的初始工作目录（可选）
	// 空字符串表示使用默认工作目录
	Cwd string `json:"cwd,omitempty"`
}

// CreateSessionResponse 表示创建会话的响应
//
// CreateSessionResponse 是服务器在成功创建 Bash 会话后返回的响应，
// 包含新创建的会话 ID。
type CreateSessionResponse struct {
	// SessionID 新创建的会话 ID
	// 客户端可以使用此 ID 在会话中执行命令
	SessionID string `json:"session_id"`
}

// RunInSessionRequest 表示在现有会话中执行代码的请求
//
// RunInSessionRequest 用于客户端向服务器发送在已存在的 Bash 会话
// 中执行代码的请求。会话必须已经通过 CreateSessionRequest 创建。
type RunInSessionRequest struct {
	// Code 要执行的代码（必填）
	Code string `json:"code" validate:"required"`

	// Cwd 命令执行的工作目录（可选）
	// 空字符串表示使用会话的当前工作目录
	Cwd string `json:"cwd,omitempty"`

	// TimeoutMs 执行超时时间（毫秒）
	// 0 表示使用服务器默认超时时间
	TimeoutMs int64 `json:"timeout_ms,omitempty" validate:"omitempty,gte=0"`
}

// Validate 验证请求的有效性
//
// 本方法使用 validator 库验证请求结构体的字段，
// 确保必填字段已提供且格式正确。
//
// 返回值:
//   - error: 验证错误（如有）
func (r *RunInSessionRequest) Validate() error {
	validate := validator.New()
	return validate.Struct(r)
}
