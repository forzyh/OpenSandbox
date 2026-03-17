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

package runtime

import (
	"fmt"
	"io"
	"os"
	"time"
)

// CommandStatus 描述命令执行的生命周期状态
//
// CommandStatus 封装了命令执行的当前状态信息，包括：
//   - 会话 ID
//   - 运行状态
//   - 退出码
//   - 错误信息
//   - 开始和结束时间
//   - 执行的命令内容
type CommandStatus struct {
	// Session 会话 ID
	Session string `json:"session"`

	// Running 命令是否正在运行
	Running bool `json:"running"`

	// ExitCode 命令退出码（如果已完成）
	ExitCode *int `json:"exit_code,omitempty"`

	// Error 错误信息（如果有）
	Error string `json:"error,omitempty"`

	// StartedAt 命令开始执行的时间
	StartedAt time.Time `json:"started_at,omitempty"`

	// FinishedAt 命令执行完成的时间（如果已完成）
	FinishedAt *time.Time `json:"finished_at,omitempty"`

	// Content 执行的命令内容
	Content string `json:"content,omitempty"`
}

// CommandOutput 包含命令的非流式输出和状态信息
//
// CommandOutput 扩展了 CommandStatus，增加了标准输出和标准错误的内容。
// 用于获取后台命令的完整输出。
type CommandOutput struct {
	// CommandStatus 命令状态信息
	CommandStatus

	// Stdout 标准输出内容
	Stdout string `json:"stdout"`

	// Stderr 标准错误内容
	Stderr string `json:"stderr"`
}

// commandSnapshot 获取命令内核的状态快照
//
// 本方法创建 commandKernel 的副本，避免并发访问问题。
//
// 参数:
//   - session: 会话 ID
//
// 返回值:
//   - *commandKernel: 命令内核状态快照（如果不存在则返回 nil）
func (c *Controller) commandSnapshot(session string) *commandKernel {
	var kernel *commandKernel
	if v, ok := c.commandClientMap.Load(session); ok {
		kernel, _ = v.(*commandKernel)
	}
	if kernel == nil {
		return nil
	}

	// 创建副本
	cp := *kernel
	return &cp
}

// GetCommandStatus 获取指定会话的命令执行状态
//
// 本方法查询指定会话的命令执行状态，包括运行状态、退出码、时间戳等信息。
//
// 参数:
//   - session: 会话 ID
//
// 返回值:
//   - *CommandStatus: 命令状态信息
//   - error: 查询错误（如会话不存在）
func (c *Controller) GetCommandStatus(session string) (*CommandStatus, error) {
	kernel := c.commandSnapshot(session)
	if kernel == nil {
		return nil, fmt.Errorf("command not found: %s", session)
	}

	status := &CommandStatus{
		Session:    session,
		Running:    kernel.running,
		ExitCode:   kernel.exitCode,
		Error:      kernel.errMsg,
		StartedAt:  kernel.startedAt,
		FinishedAt: kernel.finishedAt,
		Content:    kernel.content,
	}
	return status, nil
}

// SeekBackgroundCommandOutput 获取后台命令的累积输出
//
// 本方法从指定的游标位置读取后台命令的标准输出文件，
// 返回新输出的内容和新的游标位置。
//
// 参数:
//   - session: 会话 ID
//   - cursor: 读取起始位置的游标
//
// 返回值:
//   - []byte: 从游标位置到文件末尾的内容
//   - int64: 新的游标位置（文件末尾）
//   - error: 读取错误（如会话不存在或不是后台命令）
func (c *Controller) SeekBackgroundCommandOutput(session string, cursor int64) ([]byte, int64, error) {
	kernel := c.commandSnapshot(session)
	if kernel == nil {
		return nil, -1, fmt.Errorf("command not found: %s", session)
	}

	// 检查是否是后台命令
	if !kernel.isBackground {
		return nil, -1, fmt.Errorf("command %s is not running in background", session)
	}

	// 打开输出文件
	file, err := os.Open(kernel.stdoutPath)
	if err != nil {
		return nil, -1, fmt.Errorf("error open combined output file for command %s: %w", session, err)
	}
	defer file.Close()

	// 定位到游标位置
	_, err = file.Seek(cursor, 0)
	if err != nil {
		return nil, -1, fmt.Errorf("error seek file: %w", err)
	}

	// 读取从游标到文件末尾的所有内容
	data, err := io.ReadAll(file)
	if err != nil {
		return nil, -1, fmt.Errorf("error read file: %w", err)
	}

	// 获取当前文件位置（文件末尾）
	currentPos, err := file.Seek(0, 1)
	if err != nil {
		return nil, -1, fmt.Errorf("error get current position: %w", err)
	}

	return data, currentPos, nil
}

// markCommandFinished 更新命令完成时的状态记录
//
// 本方法在命令执行完成后更新 commandKernel 的状态信息，
// 包括退出码、错误消息、完成时间等。
//
// 参数:
//   - session: 会话 ID
//   - exitCode: 退出码
//   - errMsg: 错误消息（如果有）
func (c *Controller) markCommandFinished(session string, exitCode int, errMsg string) {
	now := time.Now()

	c.mu.Lock()
	defer c.mu.Unlock()

	var kernel *commandKernel
	if v, ok := c.commandClientMap.Load(session); ok {
		kernel, _ = v.(*commandKernel)
	}
	if kernel == nil {
		return
	}

	// 更新状态
	kernel.exitCode = &exitCode
	kernel.errMsg = errMsg
	kernel.running = false
	kernel.finishedAt = &now
}
