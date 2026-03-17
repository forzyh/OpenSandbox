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

package execute

import (
	"encoding/json"
	"fmt"
	"strings"
	"time"
)

// MessageType 表示 Jupyter 消息类型
//
// Jupyter 协议定义了多种消息类型，用于客户端和内核之间的通信。
// 本类型用于标识不同类型的消息，如执行请求、执行结果、流输出、错误等。
type MessageType string

const (
	// MsgExecuteRequest 代码执行请求消息类型
	MsgExecuteRequest MessageType = "execute_request"

	// MsgExecuteInput 表示输入代码的消息类型
	MsgExecuteInput MessageType = "execute_input"

	// MsgExecuteResult 表示执行结果的消息类型
	MsgExecuteResult MessageType = "execute_result"

	// MsgDisplayData 表示要显示的数据的消息类型
	MsgDisplayData MessageType = "display_data"

	// MsgStream 表示流输出（stdout/stderr）的消息类型
	MsgStream MessageType = "stream"

	// MsgError 表示执行过程中错误的消息类型
	MsgError MessageType = "error"

	// MsgStatus 表示内核状态更新的消息类型
	MsgStatus MessageType = "status"

	// MsgClearOutput 表示清空输出的消息类型
	MsgClearOutput MessageType = "clear_output"

	// MsgComm 表示通信消息的类型
	MsgComm MessageType = "comm"

	// MsgCommOpen 表示打开通信的消息类型
	MsgCommOpen MessageType = "comm_open"

	// MsgCommClose 表示关闭通信的消息类型
	MsgCommClose MessageType = "comm_close"

	// MsgCommMsg 表示通信消息内容的类型
	MsgCommMsg MessageType = "comm_msg"

	// MsgKernelInfo 表示内核信息请求的消息类型
	MsgKernelInfo MessageType = "kernel_info_request"

	// MsgKernelInfoReply 表示内核信息响应的消息类型
	MsgKernelInfoReply MessageType = "kernel_info_reply"

	// MsgExecuteReply 表示执行回复的消息类型
	MsgExecuteReply MessageType = "execute_reply"
)

// StreamType 表示输出流类型
//
// 用于区分标准输出（stdout）和标准错误输出（stderr）。
type StreamType string

const (
	// StreamStdout 表示标准输出流
	StreamStdout StreamType = "stdout"

	// StreamStderr 表示标准错误流
	StreamStderr StreamType = "stderr"
)

// ExecutionState 表示内核执行状态
//
// 内核在执行代码时会经历不同的状态，客户端可以根据这些状态
// 更新 UI 或执行其他逻辑。
type ExecutionState string

const (
	// StateIdle 表示内核空闲，可以接受新的请求
	StateIdle ExecutionState = "idle"

	// StateBusy 表示内核正在执行代码，忙碌状态
	StateBusy ExecutionState = "busy"

	// StateStarting 表示内核正在启动
	StateStarting ExecutionState = "starting"
)

// Header 定义 Jupyter 消息头结构
//
// 每个 Jupyter 消息都包含一个消息头，用于标识消息的来源、类型、时间等信息。
// 消息头对于追踪请求 - 响应关系至关重要。
type Header struct {
	// MessageID 消息的唯一标识符，用于匹配请求和响应
	MessageID string `json:"msg_id"`

	// Username 发送消息的用户名
	Username string `json:"username"`

	// Session 会话标识符，用于标识当前会话
	Session string `json:"session"`

	// Date 消息发送的时间戳
	Date string `json:"date"`

	// MessageType 消息类型，标识消息的用途
	MessageType string `json:"msg_type"`

	// Version 消息协议的版本号
	Version string `json:"version"`
}

// Message 定义 Jupyter 消息的基本结构
//
// Message 是 Jupyter 协议中消息的标准格式，包含消息头、父消息头、
// 元数据、内容和可选的二进制缓冲区。所有客户端与内核之间的通信
// 都使用这种消息格式。
type Message struct {
	// Header 消息头，包含消息的基本信息
	Header Header `json:"header"`

	// ParentHeader 父消息头，用于追踪请求和响应的关系
	// 响应消息的 ParentHeader 对应请求消息的 Header
	ParentHeader Header `json:"parent_header"`

	// Metadata 消息相关的元数据
	Metadata map[string]interface{} `json:"metadata"`

	// Content 消息的实际内容，以 JSON 格式存储
	Content json.RawMessage `json:"content"`

	// Buffers 可选的二进制缓冲区，用于传输大数据
	Buffers [][]byte `json:"buffers"`

	// Channel 消息所属的通道（如 shell、iopub 等）
	Channel string `json:"channel"`
}

// ExecuteRequest 定义代码执行的请求内容
//
// ExecuteRequest 用于向内核发送代码执行请求，包含要执行的代码
// 以及各种控制执行行为的选项。
type ExecuteRequest struct {
	// Code 要执行的代码字符串
	Code string `json:"code"`

	// Silent 是否以静默模式执行
	// 静默模式下不会产生用户可见的输出
	Silent bool `json:"silent"`

	// StoreHistory 是否将执行记录存储到历史中
	StoreHistory bool `json:"store_history"`

	// UserExpressions 在执行上下文中要计算的表达式映射
	// 键为表达式名称，值为表达式代码
	UserExpressions map[string]string `json:"user_expressions"`

	// AllowStdin 是否允许从标准输入读取数据
	// 允许时内核可以请求用户输入
	AllowStdin bool `json:"allow_stdin"`

	// StopOnError 遇到错误时是否停止执行
	// 设置为 true 时，第一个错误会终止执行
	StopOnError bool `json:"stop_on_error"`
}

// StreamOutput 表示流输出内容
//
// StreamOutput 用于封装来自内核的流式输出数据，
// 如标准输出（stdout）或标准错误输出（stderr）。
type StreamOutput struct {
	// Name 流名称，标识输出来源（stdout 或 stderr）
	Name StreamType `json:"name"`

	// Text 流的文本内容
	Text string `json:"text"`
}

// ExecuteResult 表示代码执行的结果
//
// ExecuteResult 包含代码执行的最终结果数据，
// 可以是文本、图像、HTML 等多种格式。
type ExecuteResult struct {
	// ExecutionCount 执行计数器值，标识这是第几次执行
	ExecutionCount int `json:"execution_count"`

	// Data 结果数据，以不同格式存储
	// 常见的 key 包括：text/plain, image/png, text/html 等
	Data map[string]interface{} `json:"data"`

	// Metadata 与结果相关的元数据
	Metadata map[string]interface{} `json:"metadata"`
}

// ExecuteReply 表示执行回复
//
// ExecuteReply 是内核对执行请求的回复，包含执行状态和可能的错误信息。
type ExecuteReply struct {
	// ExecutionCount 执行计数器值
	ExecutionCount int `json:"execution_count"`

	// Status 执行状态（"ok", "error", "abort"）
	Status string `json:"status"`

	// ErrorOutput 错误输出信息（当状态为 "error" 时）
	ErrorOutput `json:",inline"`
}

// DisplayData 表示要显示的数据
//
// DisplayData 用于封装需要显示给用户的数据，
// 支持多种格式（文本、图像、HTML 等）。
type DisplayData struct {
	// Data 显示数据，以不同格式存储
	Data map[string]interface{} `json:"data"`

	// Metadata 与显示数据相关的元数据
	Metadata map[string]interface{} `json:"metadata"`
}

// ErrorOutput 表示执行过程中的错误信息
//
// ErrorOutput 包含错误的名称、值和堆栈跟踪信息，
// 用于向用户展示详细的错误诊断信息。
type ErrorOutput struct {
	// EName 错误名称（异常类型）
	EName string `json:"ename"`

	// EValue 错误值（异常消息）
	EValue string `json:"evalue"`

	// Traceback 错误的堆栈跟踪信息
	// 每个元素代表堆栈的一行
	Traceback []string `json:"traceback"`
}

// String 将错误信息格式化为字符串
//
// 返回值:
//   - string: 格式化后的错误信息字符串
func (e *ErrorOutput) String() string {
	return fmt.Sprintf(`
Error: %s
Value: %s
Traceback: %s
`, e.EName, e.EValue, strings.Join(e.Traceback, "\n"))
}

// StatusUpdate 表示内核状态更新
//
// StatusUpdate 用于通知客户端内核当前的执行状态，
// 客户端可据此更新 UI 状态指示器。
type StatusUpdate struct {
	// ExecutionState 内核的执行状态
	ExecutionState ExecutionState `json:"execution_state"`
}

// ExecutionResult 表示代码执行的完整结果
//
// ExecutionResult 是对执行过程中产生的所有输出的封装，
// 包括流输出、执行结果、错误信息和执行时间等。
type ExecutionResult struct {
	// Status 执行状态
	Status string `json:"status"`

	// ExecutionCount 执行计数器值
	ExecutionCount int `json:"execution_count"`

	// Stream 所有流输出的集合
	Stream []*StreamOutput `json:"stream"`

	// Error 执行过程中的错误信息（如果有）
	Error *ErrorOutput `json:"error"`

	// ExecutionTime 代码执行的总耗时
	ExecutionTime time.Duration `json:"execution_time"`

	// ExecutionData 执行结果数据
	ExecutionData map[string]interface{} `json:"execution_data"`
}

// CallbackHandler 定义处理各类消息的回调函数集合
//
// CallbackHandler 提供了一组可选的回调函数，用于处理
// 执行过程中产生的各类消息。用户可以根据需要只实现
// 关心的回调函数。
type CallbackHandler struct {
	// OnExecuteResult 处理执行结果消息的回调函数
	OnExecuteResult func(*ExecuteResult)

	// OnStream 处理流输出消息的回调函数
	// 参数是可变数量的 StreamOutput 指针
	OnStream func(...*StreamOutput)

	// OnDisplayData 处理显示数据消息的回调函数
	OnDisplayData func(*DisplayData)

	// OnError 处理错误消息的回调函数
	OnError func(*ErrorOutput)

	// OnStatus 处理状态更新消息的回调函数
	OnStatus func(*StatusUpdate)
}
