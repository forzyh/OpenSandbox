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
	"sync"
	"time"

	"github.com/alibaba/opensandbox/execd/pkg/jupyter/execute"
)

// ExecuteResultHook 定义代码执行的回调函数集合
//
// ExecuteResultHook 提供了一组可选的回调函数，用于在代码执行的不同阶段
// 接收通知和处理结果。用户可以根据需要实现部分或全部回调函数。
//
// 回调函数的调用顺序：
// 1. OnExecuteInit: 执行初始化时调用
// 2. OnExecuteStdout/OnExecuteStderr: 有标准输出/错误时调用（可能多次）
// 3. OnExecuteResult: 有执行结果时调用（可能多次）
// 4. OnExecuteStatus: 状态更新时调用（可能多次）
// 5. OnExecuteError: 发生错误时调用（如有错误）
// 6. OnExecuteComplete: 执行完成时调用
type ExecuteResultHook struct {
	// OnExecuteInit 执行初始化回调
	// 参数: context - 执行上下文 ID（会话 ID）
	OnExecuteInit func(context string)

	// OnExecuteResult 执行结果回调
	// 参数:
	//   - result: 执行结果数据（map 格式，key 为 MIME 类型，如 "text/plain"）
	//   - count: 执行计数器
	OnExecuteResult func(result map[string]any, count int)

	// OnExecuteStatus 状态更新回调
	// 参数：status - 当前状态字符串
	OnExecuteStatus func(status string)

	// OnExecuteStdout 标准输出回调
	// 参数：stdout - 标准输出内容
	OnExecuteStdout func(stdout string)

	// OnExecuteStderr 标准错误回调
	// 参数：stderr - 标准错误内容
	OnExecuteStderr func(stderr string)

	// OnExecuteError 错误处理回调
	// 参数：err - 错误信息结构体
	OnExecuteError func(err *execute.ErrorOutput)

	// OnExecuteComplete 执行完成回调
	// 参数：executionTime - 执行总耗时
	OnExecuteComplete func(executionTime time.Duration)
}

// ExecuteCodeRequest 表示代码执行请求
//
// ExecuteCodeRequest 封装了执行代码所需的所有参数，包括：
//   - 语言类型和代码内容
//   - 执行上下文（会话 ID）
//   - 超时时间和工作目录
//   - 环境变量
//   - 用户/组 ID（用于权限控制）
//   - 回调函数集合
type ExecuteCodeRequest struct {
	// Language 编程语言或执行模式
	Language Language `json:"language"`

	// Code 要执行的代码
	Code string `json:"code"`

	// Context 执行上下文 ID（会话 ID）
	// 对于有状态执行，此字段指定使用哪个会话
	Context string `json:"context"`

	// Timeout 执行超时时间
	// 0 或负值表示无超时限制
	Timeout time.Duration `json:"timeout"`

	// Cwd 工作目录
	// 空字符串表示使用默认工作目录
	Cwd string `json:"cwd"`

	// Envs 环境变量映射
	// 这些变量会被添加到执行环境中
	Envs map[string]string `json:"envs"`

	// Uid 用户 ID（可选）
	// 用于以指定用户身份执行命令
	Uid *uint32 `json:"uid,omitempty"`

	// Gid 组 ID（可选）
	// 用于以指定组身份执行命令
	Gid *uint32 `json:"gid,omitempty"`

	// Hooks 回调函数集合
	Hooks ExecuteResultHook
}

// SetDefaultHooks 为未设置的回调函数安装默认实现
//
// 本方法遍历所有回调函数，如果某个回调未设置，则为其安装
// 一个打印到标准输出的默认实现。这确保了即使调用者没有提供
// 回调函数，执行过程也会产生可见的输出。
func (req *ExecuteCodeRequest) SetDefaultHooks() {
	if req.Hooks.OnExecuteResult == nil {
		req.Hooks.OnExecuteResult = func(result map[string]any, count int) {
			fmt.Printf("OnExecuteResult: %d, %++v\n", count, result)
		}
	}
	if req.Hooks.OnExecuteStatus == nil {
		req.Hooks.OnExecuteStatus = func(status string) {
			fmt.Printf("OnExecuteStatus: %s\n", status)
		}
	}
	if req.Hooks.OnExecuteStdout == nil {
		req.Hooks.OnExecuteStdout = func(stdout string) {
			fmt.Printf("OnExecuteStdout: %s\n", stdout)
		}
	}
	if req.Hooks.OnExecuteStderr == nil {
		req.Hooks.OnExecuteStderr = func(stderr string) {
			fmt.Printf("OnExecuteStderr: %s\n", stderr)
		}
	}
	if req.Hooks.OnExecuteError == nil {
		req.Hooks.OnExecuteError = func(err *execute.ErrorOutput) {
			fmt.Printf("OnExecuteError: %++v\n", err)
		}
	}
	if req.Hooks.OnExecuteComplete == nil {
		req.Hooks.OnExecuteComplete = func(executionTime time.Duration) {
			fmt.Printf("OnExecuteComplete: %v\n", executionTime)
		}
	}
	if req.Hooks.OnExecuteInit == nil {
		req.Hooks.OnExecuteInit = func(session string) {
			fmt.Printf("OnExecuteInit: %s\n", session)
		}
	}
}

// CreateContextRequest 表示创建执行上下文的请求
//
// CreateContextRequest 用于创建有状态的执行会话，
// 指定会话的语言类型和工作目录。
type CreateContextRequest struct {
	// Language 会话的编程语言类型
	Language Language `json:"language"`

	// Cwd 会话的初始工作目录
	Cwd string `json:"cwd"`
}

// CodeContext 表示代码执行上下文
//
// CodeContext 封装了执行会话的基本信息，包括会话 ID 和语言类型。
type CodeContext struct {
	// ID 会话的唯一标识符
	ID string `json:"id,omitempty"`

	// Language 会话的语言类型
	Language Language `json:"language"`
}

// bashSessionConfig 保存 Bash 会话的配置信息
//
// bashSessionConfig 定义了创建 Bash 会话时所需的所有配置参数。
type bashSessionConfig struct {
	// StartupSource 启动时要加载的脚本列表
	// 这些脚本会在会话启动时自动执行
	StartupSource []string

	// Session 会话的唯一标识符
	Session string

	// StartupTimeout 会话启动超时时间
	// 如果在此时间内未完成启动，则认为启动失败
	StartupTimeout time.Duration

	// Cwd 工作目录
	Cwd string
}

// bashSession 表示一个 Bash 会话实例
//
// bashSession 封装了一个持久的 Bash 进程，支持：
//   - 保持环境变量和工作目录状态
//   - 执行多条命令并共享状态
//   - 跟踪当前运行的进程
//
// 所有字段的并发访问都是安全的（通过 mu 互斥锁保护）。
type bashSession struct {
	// config 会话配置
	config *bashSessionConfig

	// mu 互斥锁，保护并发访问
	mu sync.Mutex

	// started 会话是否已启动
	started bool

	// env 环境变量映射
	// 记录会话当前的环境变量状态
	env map[string]string

	// cwd 当前工作目录
	cwd string

	// currentProcessPid 当前运行进程的进程组 ID
	// 在执行命令时设置，命令结束后清除
	// 用于在关闭会话时终止相关进程
	currentProcessPid int
}
