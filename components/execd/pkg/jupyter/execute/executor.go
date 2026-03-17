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

// Executor 是代码执行器的封装
//
// Executor 提供了更高层的代码执行 API，封装了底层的 Client 实现。
// 它简化了与 Jupyter 内核的交互，提供了更直观的使用方法。
//
// 主要功能：
//   - 连接到 Jupyter 内核
//   - 执行代码并获取结果
//   - 支持流式和回调两种结果处理方式
//   - 断开连接
type Executor struct {
	// client 内部使用的 WebSocket 客户端
	client *Client

	// wsURL WebSocket 连接 URL
	wsURL string
}

// NewExecutor 创建一个新的代码执行器
//
// 本函数初始化一个 Executor 实例，配置好 WebSocket 连接信息和 HTTP 客户端。
//
// 参数:
//   - wsURL: Jupyter 内核的 WebSocket URL
//   - httpClient: HTTP 客户端实例，用于发送 HTTP 请求
//
// 返回值:
//   - *Executor: 新创建的代码执行器实例
//
// 使用示例:
//
//	executor := execute.NewExecutor("ws://localhost:8888/api/kernels/xxx/channels", httpClient)
//	err := executor.Connect()
//	if err != nil {
//	    // 处理连接错误
//	}
//	defer executor.Disconnect()
func NewExecutor(wsURL string, httpClient HTTPClient) *Executor {
	client := NewClient("", httpClient)
	return &Executor{
		client: client,
		wsURL:  wsURL,
	}
}

// Connect 连接到内核
//
// 本方法建立与 Jupyter 内核的 WebSocket 连接，使执行器准备好执行代码。
// 在执行任何代码之前必须先调用此方法。
//
// 返回值:
//   - error: 连接错误（如有）
//
// 使用示例:
//
//	err := executor.Connect()
//	if err != nil {
//	    log.Fatal("连接内核失败:", err)
//	}
func (e *Executor) Connect() error {
	return e.client.Connect(e.wsURL)
}

// Disconnect 断开与内核的连接
//
// 本方法关闭与 Jupyter 内核的 WebSocket 连接。
// 在使用完执行器后应调用此方法释放资源。
//
// 使用示例:
//
//	defer executor.Disconnect()
func (e *Executor) Disconnect() {
	e.client.Disconnect()
}

// ExecuteCodeStream 以流式模式执行代码
//
// 本方法将代码发送到内核执行，并通过通道流式返回执行结果。
// 执行过程中的所有输出（标准输出、标准错误、执行结果、错误等）
// 都会通过 resultChan 通道发送。
//
// 参数:
//   - code: 要执行的代码字符串
//   - resultChan: 接收执行结果的通道
//     注意：方法会在执行完成时自动关闭此通道
//
// 返回值:
//   - error: 执行错误（如有）
//
// 使用示例:
//
//	resultChan := make(chan *execute.ExecutionResult)
//	err := executor.ExecuteCodeStream("print('Hello, World!')", resultChan)
//	if err != nil {
//	    // 处理错误
//	}
//	for result := range resultChan {
//	    // 处理每个结果片段
//	    for _, stream := range result.Stream {
//	        fmt.Print(stream.Text)
//	    }
//	}
func (e *Executor) ExecuteCodeStream(code string, resultChan chan *ExecutionResult) error {
	return e.client.ExecuteCodeStream(code, resultChan)
}

// ExecuteCodeWithCallback 使用回调函数执行代码
//
// 本方法将代码发送到内核执行，并通过回调函数处理各类响应消息。
// 与 ExecuteCodeStream 不同，本方法不使用通道，适合事件驱动的使用场景。
//
// 参数:
//   - code: 要执行的代码字符串
//   - handler: 回调函数集合，包含各类消息的处理函数
//
// 返回值:
//   - error: 执行错误（如有）
//
// 使用示例:
//
//	handler := execute.CallbackHandler{
//	    OnStream: func(streams ...*execute.StreamOutput) {
//	        for _, s := range streams {
//	            fmt.Print(s.Text)
//	        }
//	    },
//	    OnError: func(err *execute.ErrorOutput) {
//	        fmt.Printf("错误：%s: %s\n", err.EName, err.EValue)
//	    },
//	}
//	err := executor.ExecuteCodeWithCallback(code, handler)
func (e *Executor) ExecuteCodeWithCallback(code string, handler CallbackHandler) error {
	return e.client.ExecuteCodeWithCallback(code, handler)
}
