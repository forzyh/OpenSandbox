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
Package runtime 提供代码和命令执行的运行时实现。

本文件（jupyter.go）负责与 Jupyter Kernel Gateway 集成，实现多语言代码执行：

主要功能：
1. runJupyter - 通过 Jupyter 内核执行代码
2. runJupyterCode - 流式处理内核执行结果
3. getJupyterKernel - 获取内核连接
4. searchKernel - 查找可用的内核规格
5. setWorkingDir - 配置工作目录（当前为空实现）

Jupyter 架构说明：
- Jupyter Kernel Gateway: 提供 HTTP API 管理 Jupyter 内核
- Kernel: 编程语言的执行环境（如 Python、R、Julia）
- Session: 内核的运行实例，包含状态和变量

执行流程：
1. 检查是否已创建默认内核上下文
2. 获取内核连接
3. 连接到内核
4. 发送代码执行请求
5. 流式接收执行结果（输出、状态、错误等）
6. 断开连接

输出类型：
- execute_data: 执行结果数据（如表格、图像）
- stream: 文本输出（stdout/stderr）
- error: 错误信息
- status: 执行状态（busy/idle）
*/
package runtime

import (
	"context"
	"errors"

	"github.com/alibaba/opensandbox/execd/pkg/jupyter"        // Jupyter 客户端
	"github.com/alibaba/opensandbox/execd/pkg/jupyter/execute" // 执行结果处理
	"github.com/alibaba/opensandbox/execd/pkg/log"            // 日志系统
)

// runJupyter 通过 Jupyter 内核执行代码。
//
// 这是 Jupyter 代码执行的入口方法，负责：
//   1. 验证 Jupyter 服务器配置
//   2. 确保默认内核上下文已创建
//   3. 获取目标内核连接
//   4. 调用 runJupyterCode 执行代码
//
// 参数：
//   - ctx: 上下文，用于取消执行
//   - request: 执行请求，包含代码、语言、上下文等信息
//
// 前置条件：
//   - c.baseURL: Jupyter Kernel Gateway 地址
//   - c.token: 认证令牌
//
// 返回值：
//   - error: 执行错误，nil 表示成功
func (c *Controller) runJupyter(ctx context.Context, request *ExecuteCodeRequest) error {
	// 检查 Jupyter 服务器配置
	// baseURL 和 token 必须在初始化时设置
	if c.baseURL == "" || c.token == "" {
		return errors.New("language runtime server not configured, please check your image runtime")
	}

	// 如果没有指定上下文，确保默认上下文已创建
	if request.Context == "" {
		// 检查该语言的默认会话是否存在
		if c.getDefaultLanguageSession(request.Language) == "" {
			// 不存在则创建默认上下文
			if err := c.createDefaultLanguageJupyterContext(request.Language); err != nil {
				return err
			}
		}
	}

	// 确定目标会话 ID
	// 如果没有指定上下文，使用该语言的默认会话
	var targetSessionID string
	if request.Context == "" {
		targetSessionID = c.getDefaultLanguageSession(request.Language)
	} else {
		targetSessionID = request.Context
	}

	// 获取内核连接
	kernel := c.getJupyterKernel(targetSessionID)
	if kernel == nil {
		// 内核不存在，返回错误
		return ErrContextNotFound
	}

	// 设置默认的钩子函数（事件处理器）
	// 如果请求中没有提供，会使用默认的无操作实现
	request.SetDefaultHooks()

	// 发送执行初始化事件
	request.Hooks.OnExecuteInit(targetSessionID)

	// 执行代码
	return c.runJupyterCode(ctx, kernel, request)
}

// runJupyterCode 流式处理 Jupyter 内核的代码执行结果。
//
// 此方法负责：
//   1. 获取内核锁（防止并发执行）
//   2. 连接到内核
//   3. 发送代码执行请求
//   4. 处理各种类型的执行结果
//   5. 处理上下文取消（中断）
//
// 参数：
//   - ctx: 上下文，用于取消执行
//   - kernel: Jupyter 内核连接
//   - request: 执行请求
//
// 锁机制：
//   - 使用 TryLock 尝试获取锁，失败则立即返回"session is busy"
//   - 确保同一内核同时只有一个代码在执行
//
// nolint:gocognit - 此方法复杂度较高，因为需要处理多种事件类型
// TODO: 后续可以考虑重构拆分
func (c *Controller) runJupyterCode(ctx context.Context, kernel *jupyterKernel, request *ExecuteCodeRequest) error {
	// 尝试获取内核锁
	// TryLock 是非阻塞的，如果锁已被占用则返回 false
	if !kernel.mu.TryLock() {
		return errors.New("session is busy")
	}
	defer kernel.mu.Unlock() // 确保函数返回时释放锁

	// 连接到 Jupyter 内核
	// 建立 WebSocket 连接用于接收实时输出
	err := kernel.client.ConnectToKernel(kernel.kernelID)
	if err != nil {
		return err
	}
	defer kernel.client.DisconnectFromKernel(kernel.kernelID) // 断开连接

	// 创建结果通道
	// 用于接收内核返回的执行结果
	// 缓冲大小为 10，防止发送方阻塞
	results := make(chan *execute.ExecutionResult, 10)

	// 启动代码执行
	// ExecuteCodeStream 会异步执行代码，通过 results 通道返回结果
	err = kernel.client.ExecuteCodeStream(kernel.kernelID, request.Code, results)
	if err != nil {
		return err
	}

	// 处理执行结果
	// 使用 select 监听 results 通道和 ctx 取消信号
	for {
		select {
		case result := <-results:
			// 收到执行结果

			// nil 表示执行结束
			if result == nil {
				return nil
			}

			// 处理执行数据（如变量值、图表等）
			// ExecutionCount > 0 表示有执行计数，ExecutionData 非空表示有输出数据
			if result.ExecutionCount > 0 || len(result.ExecutionData) > 0 {
				request.Hooks.OnExecuteResult(result.ExecutionData, result.ExecutionCount)
			}

			// 处理状态更新（如 "busy"、"idle"）
			if result.Status != "" {
				request.Hooks.OnExecuteStatus(result.Status)
			}

			// 处理执行完成事件
			// ExecutionTime > 0 表示有执行耗时
			if result.ExecutionTime > 0 {
				request.Hooks.OnExecuteComplete(result.ExecutionTime)
			}

			// 处理错误
			if result.Error != nil {
				request.Hooks.OnExecuteError(result.Error)
			}

			// 处理流式输出（stdout/stderr）
			if len(result.Stream) > 0 {
				for _, stream := range result.Stream {
					switch stream.Name {
					case execute.StreamStdout:
						// 标准输出
						request.Hooks.OnExecuteStdout(stream.Text)
					case execute.StreamStderr:
						// 标准错误
						request.Hooks.OnExecuteStderr(stream.Text)
					default:
						// 其他流类型（通常不需要处理）
					}
				}
			}

		case <-ctx.Done():
			// 上下文已取消（用户取消或超时）

			// 记录日志
			log.Warning("context cancelled, try to interrupt kernel")

			// 尝试中断内核
			err = kernel.client.InterruptKernel(kernel.kernelID)
			if err != nil {
				log.Error("interrupt kernel failed: %v", err)
			}

			// 发送错误事件
			request.Hooks.OnExecuteError(&execute.ErrorOutput{
				EName:  "ContextCancelled",
				EValue: "Interrupt kernel",
			})

			return errors.New("context cancelled, interrupt kernel")
		}
	}
}

// setWorkingDir 配置内核的工作目录。
//
// 此方法目前为空实现，返回 nil。
// TODO: 后续可以实现通过 %cd 魔术命令或内核配置来设置工作目录。
//
// 参数：
//   - 第一个参数：Jupyter 内核（未使用）
//   - 第二个参数：创建上下文请求，包含工作目录（未使用）
//
// 返回值：
//   - error: 始终返回 nil
func (c *Controller) setWorkingDir(_ *jupyterKernel, _ *CreateContextRequest) error {
	return nil
}

// getJupyterKernel 从会话映射中获取 Jupyter 内核连接。
//
// 此方法用于根据会话 ID 查找对应的内核对象。
//
// 参数：
//   - sessionID: 会话的唯一标识
//
// 返回值：
//   - *jupyterKernel: 内核连接，如果不存在则返回 nil
//
// 实现细节：
//   - 使用 sync.Map 存储会话到内核的映射
//   - 使用类型断言确保类型安全
func (c *Controller) getJupyterKernel(sessionID string) *jupyterKernel {
	// 从并发映射中加载值
	if v, ok := c.jupyterClientMap.Load(sessionID); ok {
		// 类型断言为 jupyterKernel
		if kernel, ok := v.(*jupyterKernel); ok {
			return kernel
		}
	}
	return nil
}

// searchKernel 查找指定编程语言的 Jupyter 内核名称。
//
// Jupyter 支持多种内核（如 python3、ir、julia 等），
// 此方法根据语言名称查找对应的内核规格。
//
// 参数：
//   - client: Jupyter 客户端
//   - language: 编程语言（如 "python"、"r"）
//
// 返回值：
//   - string: 内核名称（如 "python3"）
//   - error: 错误信息
//
// 查找逻辑：
//   1. 获取所有可用的内核规格
//   2. 遍历查找匹配语言的内核
//   3. 跳过 python3（有特殊处理）
//   4. 返回第一个匹配的内核名称
func (c *Controller) searchKernel(client *jupyter.Client, language Language) (string, error) {
	// 获取所有内核规格
	specs, err := client.GetKernelSpecs()
	if err != nil {
		return "", err
	}

	// 检查是否有可用的内核
	if len(specs.Kernelspecs) == 0 {
		return "", errors.New("no kernel specs found")
	}

	// 遍历查找匹配的内核
	var kernelName string
	for name, spec := range specs.Kernelspecs {
		// 跳过 python3，它有特殊处理逻辑
		if name == "python3" {
			continue
		}

		// 比较语言名称
		// spec.Spec.Language 是内核声明的语言
		// language.String() 是请求的语言
		if spec.Spec.Language == language.String() {
			kernelName = name
		}
	}

	// 检查是否找到匹配
	if kernelName == "" {
		return "", errors.New("no kernel specs found")
	}

	return kernelName, nil
}
