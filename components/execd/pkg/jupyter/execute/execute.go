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

// Package execute 提供通过 WebSocket 执行 Jupyter 内核代码的功能
//
// 本包实现了与 Jupyter 内核通信的完整客户端，支持：
//   - 通过 WebSocket 连接 Jupyter 内核
//   - 发送代码执行请求
//   - 接收流式执行结果（stdout/stderr）
//   - 接收错误信息和状态更新
//   - 支持回调函数和通道两种结果处理方式
//
// 主要类型：
//   - Client: WebSocket 客户端，负责与内核通信
//   - Executor: 代码执行器，封装 Client 提供高层 API
//   - Message: Jupyter 消息结构
//   - ExecutionResult: 执行结果封装
//
// 使用示例:
//
//	executor := execute.NewExecutor(wsURL, httpClient)
//	err := executor.Connect()
//	if err != nil { /* 处理错误 */ }
//	defer executor.Disconnect()
//
//	resultChan := make(chan *execute.ExecutionResult)
//	err = executor.ExecuteCodeStream(code, resultChan)
//	for result := range resultChan {
//	    // 处理结果
//	}
package execute

import (
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"sync"
	"time"

	"github.com/google/uuid"
	"github.com/gorilla/websocket"
)

// HTTPClient 定义 HTTP 客户端接口
//
// 该接口用于抽象 HTTP 请求的发送，便于测试和自定义 HTTP 客户端行为。
type HTTPClient interface {
	// Do 发送 HTTP 请求
	// 参数:
	//   - req: HTTP 请求对象
	// 返回值:
	//   - *http.Response: HTTP 响应
	//   - error: 请求错误（如有）
	Do(req *http.Request) (*http.Response, error)
}

// Client 是用于代码执行的 WebSocket 客户端
//
// Client 负责与 Jupyter 内核建立 WebSocket 连接，发送执行请求，
// 并接收和处理各种类型的响应消息（执行结果、流输出、错误、状态等）。
// 该类型是线程安全的，支持并发访问。
type Client struct {
	// httpClient 底层 HTTP 客户端，用于发送 HTTP 请求
	httpClient HTTPClient

	// conn WebSocket 连接对象
	conn *websocket.Conn

	// handlers 消息类型到处理函数的映射表
	handlers map[MessageType]func(*Message)

	// session 会话 ID，用于标识当前会话
	session string

	// msgCounter 消息 ID 计数器，用于生成唯一的消息 ID
	msgCounter int

	// mu 互斥锁，保护并发访问
	mu sync.Mutex

	// wsURL WebSocket URL，用于内核连接
	wsURL string
}

// NewClient 创建一个新的代码执行客户端
//
// 参数:
//   - baseURL: 基础 URL（当前未使用，保留用于扩展）
//   - httpClient: HTTP 客户端实例
//
// 返回值:
//   - *Client: 新创建的客户端实例，已初始化会话 ID 和消息处理器映射
func NewClient(baseURL string, httpClient HTTPClient) *Client {
	return &Client{
		httpClient: httpClient,
		handlers:   make(map[MessageType]func(*Message)),
		session:    uuid.New().String(),
		msgCounter: 0,
	}
}

// Connect 连接到指定内核的 WebSocket
//
// 本方法建立与 Jupyter 内核的 WebSocket 连接，并启动消息接收协程。
// 连接成功后会自动注册默认的消息处理器。
//
// 参数:
//   - wsURL: 内核的 WebSocket URL
//
// 返回值:
//   - error: 连接错误（如有）
func (c *Client) Connect(wsURL string) error {
	c.mu.Lock()
	defer c.mu.Unlock()

	// 保存 WebSocket URL
	c.wsURL = wsURL

	// 建立 WebSocket 连接
	conn, resp, err := websocket.DefaultDialer.Dial(wsURL, nil)
	if resp != nil && err != nil {
		resp.Body.Close()
	}
	if err != nil {
		return fmt.Errorf("failed to connect to kernel: %w", err)
	}
	c.conn = conn

	// 注册默认消息处理器
	c.registerDefaultHandlers()

	// 启动消息接收协程
	go c.receiveMessages()

	return nil
}

// Disconnect 断开与内核的 WebSocket 连接
//
// 本方法关闭当前的 WebSocket 连接并将连接对象置为 nil。
// 调用后，receiveMessages 协程会检测到连接关闭并退出。
func (c *Client) Disconnect() {
	c.mu.Lock()
	defer c.mu.Unlock()

	if c.conn != nil {
		c.conn.Close()
		c.conn = nil
	}
}

// IsConnected 检查是否已连接到内核
//
// 返回值:
//   - bool: 是否已连接（conn 非 nil）
func (c *Client) IsConnected() bool {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.conn != nil
}

// ExecuteCodeStream 以流式模式执行代码，将结果发送到指定通道
//
// 本方法发送代码执行请求到内核，并通过通道流式返回执行结果。
// 执行过程中的各种输出（stdout、stderr、执行结果、错误等）会
// 通过 resultChan 通道逐个发送。
//
// 执行流程：
// 1. 检查是否已连接到内核
// 2. 记录执行开始时间
// 3. 构建执行请求消息
// 4. 注册临时消息处理器捕获各类响应
// 5. 发送执行请求
// 6. 当收到 idle 状态时，计算执行时间并关闭结果通道
//
// 参数:
//   - code: 要执行的代码字符串
//   - resultChan: 接收执行结果的通道（方法会在执行完成时关闭此通道）
//
// 返回值:
//   - error: 发送请求错误（如有）
func (c *Client) ExecuteCodeStream(code string, resultChan chan *ExecutionResult) error {
	if !c.IsConnected() {
		return errors.New("not connected to kernel, please call Connect method")
	}

	// 记录开始时间
	startTime := time.Now()

	// 准备执行请求
	msgID := c.nextMessageID()
	request := &ExecuteRequest{
		Code:            code,
		Silent:          false,
		StoreHistory:    true,
		UserExpressions: make(map[string]string),
		AllowStdin:      false,
		StopOnError:     true,
	}

	// 序列化请求内容
	content, err := json.Marshal(request)
	if err != nil {
		return fmt.Errorf("failed to serialize request: %w", err)
	}

	// 创建消息
	msg := &Message{
		Header: Header{
			MessageID:   msgID,
			Username:    "go-client",
			Session:     c.session,
			Date:        time.Now().Format(time.RFC3339),
			MessageType: string(MsgExecuteRequest),
			Version:     "5.3",
		},
		ParentHeader: Header{},
		Metadata:     make(map[string]interface{}),
		Content:      content,
		Channel:      "shell",
	}

	// 创建结果对象
	result := &ExecutionResult{
		Status:        "ok",
		Stream:        make([]*StreamOutput, 0),
		ExecutionTime: 0,
	}

	// 注册临时处理器接收执行结果
	var executeDone bool
	var executeMutex sync.Mutex
	var executeResult *ExecuteResult

	// 创建互斥锁保护结果对象
	var resultMutex sync.Mutex

	// 清除临时处理器
	c.clearTemporaryHandlers()

	// 注册执行回复处理器
	c.registerHandler(MsgExecuteReply, func(msg *Message) {
		var execReply ExecuteReply
		if err := json.Unmarshal(msg.Content, &execReply); err != nil {
			return
		}

		resultMutex.Lock()
		result.ExecutionCount = execReply.ExecutionCount
		if execReply.EName != "" {
			result.Error = &execReply.ErrorOutput
		}
		resultMutex.Unlock()
	})

	// 注册执行结果处理器
	c.registerHandler(MsgExecuteResult, func(msg *Message) {
		var execResult ExecuteResult
		if err := json.Unmarshal(msg.Content, &execResult); err != nil {
			return
		}

		executeMutex.Lock()
		executeResult = &execResult
		executeMutex.Unlock()

		resultMutex.Lock()
		result.ExecutionCount = execResult.ExecutionCount

		notify := &ExecutionResult{}
		notify.ExecutionCount = executeResult.ExecutionCount
		notify.ExecutionData = executeResult.Data

		resultChan <- notify
		resultMutex.Unlock()
	})

	// 注册流输出处理器
	c.registerHandler(MsgStream, func(msg *Message) {
		var stream StreamOutput
		if err := json.Unmarshal(msg.Content, &stream); err != nil {
			return
		}

		resultMutex.Lock()
		result.Stream = append(result.Stream, &stream)

		notify := &ExecutionResult{}
		notify.Stream = []*StreamOutput{&stream}

		resultChan <- notify
		resultMutex.Unlock()
	})

	// 注册错误处理器
	c.registerHandler(MsgError, func(msg *Message) {
		var errOutput ErrorOutput
		if err := json.Unmarshal(msg.Content, &errOutput); err != nil {
			return
		}

		resultMutex.Lock()
		result.Status = "error"
		result.Error = &errOutput

		notify := &ExecutionResult{}
		notify.Error = &errOutput
		notify.Status = "error"

		resultChan <- notify
		resultMutex.Unlock()
	})

	// 注册状态处理器
	c.registerHandler(MsgStatus, func(msg *Message) {
		var status StatusUpdate
		if err := json.Unmarshal(msg.Content, &status); err != nil {
			return
		}

		if status.ExecutionState == StateIdle {
			executeMutex.Lock()

			// 检查执行是否完成
			if !executeDone {
				executeDone = true
				go func() {
					// 计算执行时间
					resultMutex.Lock()
					result.ExecutionTime = time.Since(startTime)

					// 发送最终结果
					notify := &ExecutionResult{}
					notify.ExecutionTime = result.ExecutionTime

					resultChan <- notify
					resultMutex.Unlock()

					// 等待执行计数或错误结果
					for result.ExecutionCount <= 0 && result.Error == nil {
						time.Sleep(300 * time.Millisecond)
					}

					// 关闭结果通道
					close(resultChan)
				}()
			}
			executeMutex.Unlock()
		}
	})

	// 发送执行请求
	c.mu.Lock()
	err = c.conn.WriteJSON(msg)
	c.mu.Unlock()
	if err != nil {
		return fmt.Errorf("failed to send execution request: %w", err)
	}

	return nil
}

// ExecuteCodeWithCallback 使用回调函数执行代码
//
// 本方法发送代码执行请求到内核，并通过回调函数处理各类响应消息。
// 与 ExecuteCodeStream 不同，本方法不使用通道，而是直接调用提供的回调函数。
//
// 参数:
//   - code: 要执行的代码字符串
//   - handler: 回调函数集合，包含各类消息的处理函数
//
// 返回值:
//   - error: 发送请求错误（如有）
func (c *Client) ExecuteCodeWithCallback(code string, handler CallbackHandler) error {
	if !c.IsConnected() {
		return errors.New("not connected to kernel, please call Connect method")
	}

	// 准备执行请求
	msgID := c.nextMessageID()
	request := &ExecuteRequest{
		Code:            code,
		Silent:          false,
		StoreHistory:    true,
		UserExpressions: make(map[string]string),
		AllowStdin:      false,
		StopOnError:     true,
	}

	// 序列化请求内容
	content, err := json.Marshal(request)
	if err != nil {
		return fmt.Errorf("failed to serialize request: %w", err)
	}

	// 创建消息
	msg := &Message{
		Header: Header{
			MessageID:   msgID,
			Username:    "go-client",
			Session:     c.session,
			Date:        time.Now().Format(time.RFC3339),
			MessageType: string(MsgExecuteRequest),
			Version:     "5.3",
		},
		ParentHeader: Header{},
		Metadata:     make(map[string]interface{}),
		Content:      content,
		Channel:      "shell",
	}

	// 注册执行结果处理器
	if handler.OnExecuteResult != nil {
		c.registerHandler(MsgExecuteResult, func(msg *Message) {
			var execResult ExecuteResult
			if err := json.Unmarshal(msg.Content, &execResult); err != nil {
				return
			}

			// 调用回调函数
			handler.OnExecuteResult(&execResult)
		})
	}

	// 注册流输出处理器
	if handler.OnStream != nil {
		c.registerHandler(MsgStream, func(msg *Message) {
			var stream StreamOutput
			if err := json.Unmarshal(msg.Content, &stream); err != nil {
				return
			}

			// 调用回调函数
			handler.OnStream(&stream)
		})
	}

	// 注册显示数据处理器
	if handler.OnDisplayData != nil {
		c.registerHandler(MsgDisplayData, func(msg *Message) {
			var display DisplayData
			if err := json.Unmarshal(msg.Content, &display); err != nil {
				return
			}

			// 调用回调函数
			handler.OnDisplayData(&display)
		})
	}

	// 注册错误处理器
	if handler.OnError != nil {
		c.registerHandler(MsgError, func(msg *Message) {
			var errOutput ErrorOutput
			if err := json.Unmarshal(msg.Content, &errOutput); err != nil {
				return
			}

			// 调用回调函数
			handler.OnError(&errOutput)
		})
	}

	// 注册状态处理器
	if handler.OnStatus != nil {
		c.registerHandler(MsgStatus, func(msg *Message) {
			var status StatusUpdate
			if err := json.Unmarshal(msg.Content, &status); err != nil {
				return
			}

			// 调用回调函数
			handler.OnStatus(&status)
		})
	}

	// 发送执行请求
	c.mu.Lock()
	err = c.conn.WriteJSON(msg)
	c.mu.Unlock()
	if err != nil {
		return fmt.Errorf("failed to send execution request: %w", err)
	}

	return nil
}

// registerDefaultHandlers 注册默认消息处理器
//
// 当前为空实现，可根据需要添加默认的消息处理逻辑。
func (c *Client) registerDefaultHandlers() {
	// 默认消息处理器可在此处注册
}

// registerHandler 注册临时消息处理器
//
// 本方法为指定消息类型注册处理函数，会覆盖已存在的同类型处理器。
//
// 参数:
//   - msgType: 消息类型
//   - handler: 处理函数
func (c *Client) registerHandler(msgType MessageType, handler func(*Message)) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.handlers[msgType] = handler
}

// clearTemporaryHandlers 清除临时消息处理器
//
// 本方法清除所有已注册的处理器并重新注册默认处理器。
// 通常在执行新的代码前调用，以确保不会收到旧执行的残留消息。
func (c *Client) clearTemporaryHandlers() {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.handlers = make(map[MessageType]func(*Message))
	c.registerDefaultHandlers()
}

// receiveMessages 接收 WebSocket 消息
//
// 本方法在独立的协程中运行，持续从 WebSocket 连接读取消息并分发给相应的处理器。
// 当连接关闭或发生错误时退出循环。
func (c *Client) receiveMessages() {
	for {
		c.mu.Lock()
		conn := c.conn
		c.mu.Unlock()

		if conn == nil {
			break
		}

		// 接收消息
		var msg Message
		err := conn.ReadJSON(&msg)
		if err != nil {
			// 连接可能已关闭
			break
		}

		// 处理消息
		c.handleMessage(&msg)
	}
}

// handleMessage 处理接收到的消息
//
// 本方法根据消息类型调用相应的处理函数。
//
// 参数:
//   - msg: 接收到的消息
func (c *Client) handleMessage(msg *Message) {
	// 提取消息类型
	msgType := MessageType(msg.Header.MessageType)

	// 调用相应的处理器
	c.mu.Lock()
	handler, ok := c.handlers[msgType]
	c.mu.Unlock()

	if ok && handler != nil {
		handler(msg)
	}
}

// nextMessageID 生成下一个消息 ID
//
// 消息 ID 格式为：<session>-<counter>，确保每个消息有唯一标识。
//
// 返回值:
//   - string: 新生成的消息 ID
func (c *Client) nextMessageID() string {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.msgCounter++
	return fmt.Sprintf("%s-%d", c.session, c.msgCounter)
}
