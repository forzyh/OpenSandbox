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

// CommandStatusResponse 表示命令状态的 REST API 响应
//
// CommandStatusResponse 用于返回后台命令的执行状态，
// 包括命令 ID、运行状态、退出码、时间戳等信息。
type CommandStatusResponse struct {
	// ID 命令会话 ID
	ID string `json:"id"`

	// Content 执行的命令内容
	Content string `json:"content,omitempty"`

	// Running 命令是否正在运行
	Running bool `json:"running"`

	// ExitCode 命令退出码（如果已完成）
	ExitCode *int `json:"exit_code,omitempty"`

	// Error 错误消息（如果有）
	Error string `json:"error,omitempty"`

	// StartedAt 命令开始执行的时间
	StartedAt time.Time `json:"started_at,omitempty"`

	// FinishedAt 命令执行完成的时间（如果已完成）
	FinishedAt *time.Time `json:"finished_at,omitempty"`
}
