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

/*
本文件（command.go）提供命令执行相关的 HTTP 控制器方法。

主要功能：
1. RunCommand - 执行 shell 命令并流式输出结果
2. InterruptCommand - 中断正在执行的命令
3. GetCommandStatus - 查询命令执行状态
4. GetBackgroundCommandOutput - 获取后台命令的输出日志

命令执行模式：
- 同步模式：命令执行期间保持连接，实时输出结果（SSE）
- 后台模式：命令在后台执行，可通过其他接口查询状态和获取输出

适用场景：
- 执行系统命令（如 ls、ps、git 等）
- 运行脚本文件
- 启动后台服务
*/
package controller

import (
	"context"
	"fmt"
	"net/http"
	"strconv"
	"time"

	"github.com/alibaba/opensandbox/execd/pkg/flag"     // 配置标志
	"github.com/alibaba/opensandbox/execd/pkg/runtime" // 代码执行运行时
	"github.com/alibaba/opensandbox/execd/pkg/web/model" // 数据模型
)

// RunCommand 执行 shell 命令并通过 SSE 流式输出结果。
//
// 这是命令执行的核心接口，支持：
//   - 同步执行：实时输出 stdout/stderr
//   - 后台执行：命令在后台运行，可独立查询状态
//   - 超时控制：防止命令无限期执行
//   - 用户权限：可指定执行命令的用户 ID 和组 ID
//   - 环境变量：可设置自定义环境变量
//   - 工作目录：可指定命令执行的工作目录
//
// 请求体格式（JSON）：
//   {
//     "command": "ls -la",      // 要执行的命令
//     "cwd": "/path/to/dir",    // 工作目录（可选）
//     "timeoutMs": 30000,       // 超时时间（毫秒）
//     "background": false,      // 是否后台执行
//     "uid": 1000,              // 用户 ID（可选）
//     "gid": 1000,              // 组 ID（可选）
//     "envs": {"KEY": "value"}  // 环境变量（可选）
//   }
//
// 响应：SSE（Server-Sent Events）流式输出
//   - stdout: 标准输出
//   - stderr: 标准错误
//   - status: 执行状态
//   - complete: 执行完成
//   - error: 执行错误
func (c *CodeInterpretingController) RunCommand() {
	// 定义请求结构体
	var request model.RunCommandRequest

	// 从 HTTP 请求体解析 JSON 数据
	if err := c.bindJSON(&request); err != nil {
		c.RespondError(
			http.StatusBadRequest,
			model.ErrorCodeInvalidRequest,
			fmt.Sprintf("error parsing request, MAYBE invalid body format. %v", err),
		)
		return
	}

	// 验证请求参数的合法性
	// 如检查命令是否为空、超时时间是否合理、用户 ID 是否有效等
	err := request.Validate()
	if err != nil {
		c.RespondError(
			http.StatusBadRequest,
			model.ErrorCodeInvalidRequest,
			fmt.Sprintf("invalid request, validation error %v", err),
		)
		return
	}

	// 创建可取消的上下文
	// 用于在客户端断开连接或超时时取消命令执行
	ctx, cancel := context.WithCancel(c.ctx.Request.Context())
	defer cancel() // 确保函数返回时释放资源

	// 将 HTTP 层请求转换为运行时层请求
	runCodeRequest := c.buildExecuteCommandRequest(request)

	// 设置服务器端事件处理器
	// 该处理器负责将执行结果通过 SSE 发送给客户端
	eventsHandler := c.setServerEventsHandler(ctx)
	runCodeRequest.Hooks = eventsHandler

	// 配置 SSE 响应头
	// 设置 Content-Type 为 text/event-stream，启用流式传输
	c.setupSSEResponse()

	// 执行命令
	// codeRunner 会根据请求类型选择同步或后台执行模式
	err = codeRunner.Execute(runCodeRequest)
	if err != nil {
		// 执行失败，返回 500 错误
		c.RespondError(
			http.StatusInternalServerError,
			model.ErrorCodeRuntimeError,
			fmt.Sprintf("error running commands %v", err),
		)
		return
	}

	// 等待一小段时间，确保所有 SSE 事件都已发送完成
	// 这是优雅关闭的需要，避免客户端丢失最后的输出
	time.Sleep(flag.ApiGracefulShutdownTimeout)
}

// InterruptCommand 中断正在执行的命令。
//
// 当用户需要停止长时间运行的命令时，调用此接口。
// 底层会向进程发送中断信号（SIGINT）。
//
// 查询参数：
//   - id: 要中断的命令执行会话 ID
func (c *CodeInterpretingController) InterruptCommand() {
	// 委托给内部 interrupt() 方法处理
	// interrupt() 方法在 codeinterpreting.go 中定义
	c.interrupt()
}

// GetCommandStatus 根据 ID 获取命令执行状态。
//
// 此接口用于查询后台执行的命令的当前状态。
// 对于同步执行的命令，通常不需要调用此接口。
//
// 路径参数：
//   - id: 命令执行的会话 ID
//
// 响应格式：
//   {
//     "id": "session-xxx",      // 会话 ID
//     "running": true,          // 是否正在运行
//     "exitCode": 0,            // 退出码（完成后才有值）
//     "error": "",              // 错误信息（如果有）
//     "content": "ls -la",      // 执行的命令内容
//     "startedAt": "...",       // 开始时间
//     "finishedAt": "..."       // 结束时间（完成后才有值）
//   }
func (c *CodeInterpretingController) GetCommandStatus() {
	// 从路径参数中获取命令执行 ID
	commandID := c.ctx.Param("id")

	// 验证参数是否为空
	if commandID == "" {
		c.RespondError(http.StatusBadRequest, model.ErrorCodeInvalidRequest, "missing command execution id")
		return
	}

	// 调用运行时层获取命令状态
	status, err := codeRunner.GetCommandStatus(commandID)
	if err != nil {
		// 找不到对应的命令执行记录，返回 404
		c.RespondError(http.StatusNotFound, model.ErrorCodeInvalidRequest, err.Error())
		return
	}

	// 构建响应对象
	resp := model.CommandStatusResponse{
		ID:       status.Session,    // 会话 ID
		Running:  status.Running,    // 运行状态
		ExitCode: status.ExitCode,   // 退出码
		Error:    status.Error,      // 错误信息
		Content:  status.Content,    // 命令内容
	}

	// 可选字段：开始时间（如果不为零值则添加）
	if !status.StartedAt.IsZero() {
		resp.StartedAt = status.StartedAt
	}

	// 可选字段：结束时间（如果非空则添加）
	if status.FinishedAt != nil {
		resp.FinishedAt = status.FinishedAt
	}

	c.RespondSuccess(resp)
}

// GetBackgroundCommandOutput 获取后台命令的标准输出和标准错误。
//
// 对于后台执行的命令，此接口用于获取累积的输出内容。
// 支持分页读取，通过 cursor 参数指定起始位置。
//
// 路径参数：
//   - id: 命令执行的会话 ID
//
// 查询参数：
//   - cursor: 读取游标，表示从哪个位置开始读取（默认为 0）
//
// 响应：
//   - 响应体：纯文本格式的输出内容
//   - 响应头 EXECD-COMMANDS-TAIL-CURSOR: 下一次读取的游标位置
func (c *CodeInterpretingController) GetBackgroundCommandOutput() {
	// 从路径参数获取命令执行 ID
	id := c.ctx.Param("id")

	// 验证参数
	if id == "" {
		c.RespondError(http.StatusBadRequest, model.ErrorCodeMissingQuery, "missing command execution id")
		return
	}

	// 从查询参数获取游标，默认为 0（从头开始）
	// QueryInt64 是基础控制器提供的辅助方法
	cursor := c.QueryInt64(c.ctx.Query("cursor"), 0)

	// 调用运行时层获取输出
	// 返回：输出内容、新的游标位置、错误
	output, lastCursor, err := codeRunner.SeekBackgroundCommandOutput(id, cursor)
	if err != nil {
		c.RespondError(http.StatusBadRequest, model.ErrorCodeInvalidRequest, err.Error())
		return
	}

	// 设置响应头，告知客户端下一次读取的游标位置
	c.ctx.Header("EXECD-COMMANDS-TAIL-CURSOR", strconv.FormatInt(lastCursor, 10))

	// 设置响应类型为纯文本
	c.ctx.Header("Content-Type", "text/plain; charset=utf-8")

	// 返回输出内容
	c.ctx.String(http.StatusOK, "%s", output)
}

// buildExecuteCommandRequest 将 HTTP 层的 RunCommandRequest 转换为运行时层的 ExecuteCodeRequest。
//
// 根据是否后台执行，设置不同的语言类型：
//   - 后台执行：runtime.BackgroundCommand
//   - 同步执行：runtime.Command
//
// 参数 request: HTTP 层请求对象
// 返回值：运行时层请求对象，包含执行所需的所有参数
func (c *CodeInterpretingController) buildExecuteCommandRequest(request model.RunCommandRequest) *runtime.ExecuteCodeRequest {
	// 转换超时时间单位：毫秒 -> time.Duration
	timeout := time.Duration(request.TimeoutMs) * time.Millisecond

	// 根据后台执行标志选择不同的语言类型
	if request.Background {
		// 后台执行模式
		return &runtime.ExecuteCodeRequest{
			Language: runtime.BackgroundCommand, // 后台命令类型
			Code:     request.Command,           // 命令内容
			Cwd:      request.Cwd,               // 工作目录
			Timeout:  timeout,                   // 超时时间
			Gid:      request.Gid,               // 组 ID
			Uid:      request.Uid,               // 用户 ID
			Envs:     request.Envs,              // 环境变量
		}
	} else {
		// 同步执行模式
		return &runtime.ExecuteCodeRequest{
			Language: runtime.Command, // 同步命令类型
			Code:     request.Command,
			Cwd:      request.Cwd,
			Timeout:  timeout,
			Gid:      request.Gid,
			Uid:      request.Uid,
			Envs:     request.Envs,
		}
	}
}
