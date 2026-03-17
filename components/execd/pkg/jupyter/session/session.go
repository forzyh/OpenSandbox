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

// Package session 提供管理 Jupyter 会话的功能
package session

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
)

// Client 是会话管理客户端
//
// Client 封装了与 Jupyter 服务器会话管理 API 的交互，
// 提供了创建、查询、修改和删除会话的方法。
// 所有方法都支持通过 httpClient 发送带认证的请求。
type Client struct {
	// baseURL Jupyter 服务器的基础 URL
	baseURL string

	// httpClient 用于发送 HTTP 请求的客户端，支持认证
	httpClient *http.Client
}

// NewClient 创建一个新的会话管理客户端
//
// 参数:
//   - baseURL: Jupyter 服务器的基础 URL（如 "http://localhost:8888"）
//   - httpClient: HTTP 客户端实例
//
// 返回值:
//   - *Client: 新创建的会话管理客户端
func NewClient(baseURL string, httpClient *http.Client) *Client {
	return &Client{
		baseURL:    baseURL,
		httpClient: httpClient,
	}
}

// ListSessions 获取所有活动会话的列表
//
// 本方法向 Jupyter 服务器发送 GET 请求，获取当前所有活跃的会话信息。
//
// 返回值:
//   - []*Session: 会话列表
//   - error: 请求错误（如有）
func (c *Client) ListSessions() ([]*Session, error) {
	// 构建请求 URL
	url := fmt.Sprintf("%s/api/sessions", c.baseURL)

	// 发送 GET 请求
	resp, err := c.httpClient.Get(url)
	if err != nil {
		return nil, fmt.Errorf("failed to send request: %w", err)
	}
	defer resp.Body.Close()

	// 检查响应状态
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("server returned error status code: %d", resp.StatusCode)
	}

	// 读取响应内容
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("failed to read response: %w", err)
	}

	// 解析 JSON 响应
	var sessions []*Session
	if err := json.Unmarshal(body, &sessions); err != nil {
		return nil, fmt.Errorf("failed to parse response: %w", err)
	}

	return sessions, nil
}

// GetSession 获取指定会话的详细信息
//
// 本方法向 Jupyter 服务器发送 GET 请求，获取指定 ID 的会话信息。
//
// 参数:
//   - sessionId: 会话 ID
//
// 返回值:
//   - *Session: 会话信息
//   - error: 请求错误（如有）
func (c *Client) GetSession(sessionId string) (*Session, error) {
	// 构建请求 URL
	url := fmt.Sprintf("%s/api/sessions/%s", c.baseURL, sessionId)

	// 发送 GET 请求
	resp, err := c.httpClient.Get(url)
	if err != nil {
		return nil, fmt.Errorf("failed to send request: %w", err)
	}
	defer resp.Body.Close()

	// 检查响应状态
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("server returned error status code: %d", resp.StatusCode)
	}

	// 读取响应内容
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("failed to read response: %w", err)
	}

	// 解析 JSON 响应
	var session Session
	if err := json.Unmarshal(body, &session); err != nil {
		return nil, fmt.Errorf("failed to parse response: %w", err)
	}

	return &session, nil
}

// CreateSession 创建一个新的会话
//
// 本方法向 Jupyter 服务器发送 POST 请求，创建一个新的会话并启动指定的内核。
//
// 参数:
//   - name: 会话名称
//   - ipynb: 关联的 notebook 文件路径
//   - kernel: 内核名称（如 "python3"）
//
// 返回值:
//   - *Session: 创建的会话信息
//   - error: 请求错误（如有）
func (c *Client) CreateSession(name, ipynb, kernel string) (*Session, error) {
	// 构建请求 URL
	url := fmt.Sprintf("%s/api/sessions", c.baseURL)

	// 构建请求体
	reqBody := &SessionCreateRequest{
		Path: ipynb,
		Name: name,
		Type: DefaultSessionType,
		Kernel: &KernelSpec{
			Name: kernel,
		},
	}

	// 序列化请求体为 JSON
	jsonData, err := json.Marshal(reqBody)
	if err != nil {
		return nil, fmt.Errorf("failed to serialize request: %w", err)
	}

	// 创建 POST 请求
	req, err := http.NewRequest(http.MethodPost, url, bytes.NewBuffer(jsonData))
	if err != nil {
		return nil, fmt.Errorf("failed to create request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")

	// 发送请求
	resp, err := c.httpClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("failed to send request: %w", err)
	}
	defer resp.Body.Close()

	// 检查响应状态（201 Created 或 200 OK 均为成功）
	if resp.StatusCode != http.StatusCreated && resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("server returned error status code: %d", resp.StatusCode)
	}

	// 读取响应内容
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("failed to read response: %w", err)
	}

	// 解析 JSON 响应
	var session Session
	if err := json.Unmarshal(body, &session); err != nil {
		return nil, fmt.Errorf("failed to parse response: %w", err)
	}

	return &session, nil
}

// ModifySession 修改现有会话的属性
//
// 本方法向 Jupyter 服务器发送 PATCH 请求，修改指定会话的属性。
// 只有非空的参数会被更新。
//
// 参数:
//   - sessionId: 会话 ID
//   - name: 新的会话名称（空字符串表示不修改）
//   - path: 新的路径（空字符串表示不修改）
//   - kernel: 新的内核名称（空字符串表示不修改）
//
// 返回值:
//   - *Session: 更新后的会话信息
//   - error: 请求错误（如有）
func (c *Client) ModifySession(sessionId, name, path, kernel string) (*Session, error) {
	// 构建请求 URL
	url := fmt.Sprintf("%s/api/sessions/%s", c.baseURL, sessionId)

	// 构建请求体
	reqBody := &SessionUpdateRequest{}
	if name != "" {
		reqBody.Name = name
	}
	if path != "" {
		reqBody.Path = path
	}
	if kernel != "" {
		reqBody.Kernel = &KernelSpec{
			Name: kernel,
		}
	}

	// 序列化请求体为 JSON
	jsonData, err := json.Marshal(reqBody)
	if err != nil {
		return nil, fmt.Errorf("failed to serialize request: %w", err)
	}

	// 创建 PATCH 请求
	req, err := http.NewRequest(http.MethodPatch, url, bytes.NewBuffer(jsonData))
	if err != nil {
		return nil, fmt.Errorf("failed to create request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")

	// 发送请求
	resp, err := c.httpClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("failed to send request: %w", err)
	}
	defer resp.Body.Close()

	// 检查响应状态
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("server returned error status code: %d", resp.StatusCode)
	}

	// 读取响应内容
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("failed to read response: %w", err)
	}

	// 解析 JSON 响应
	var session Session
	if err := json.Unmarshal(body, &session); err != nil {
		return nil, fmt.Errorf("failed to parse response: %w", err)
	}

	return &session, nil
}

// DeleteSession 删除指定的会话
//
// 本方法向 Jupyter 服务器发送 DELETE 请求，删除指定 ID 的会话。
// 删除会话同时会终止关联的内核。
//
// 参数:
//   - sessionId: 会话 ID
//
// 返回值:
//   - error: 请求错误（如有）
func (c *Client) DeleteSession(sessionId string) error {
	// 构建请求 URL
	url := fmt.Sprintf("%s/api/sessions/%s", c.baseURL, sessionId)

	// 创建 DELETE 请求
	req, err := http.NewRequest(http.MethodDelete, url, nil)
	if err != nil {
		return fmt.Errorf("failed to create request: %w", err)
	}

	// 发送请求
	resp, err := c.httpClient.Do(req)
	if err != nil {
		return fmt.Errorf("failed to send request: %w", err)
	}
	defer resp.Body.Close()

	// 检查响应状态（204 No Content 或 200 OK 均为成功）
	if resp.StatusCode != http.StatusNoContent && resp.StatusCode != http.StatusOK {
		return fmt.Errorf("server returned error status code: %d", resp.StatusCode)
	}

	return nil
}

// CreateSessionWithOptions 使用选项创建新会话
//
// 本方法是 CreateSession 的增强版本，通过 SessionOptions 提供更灵活的配置。
// 支持指定会话类型、重用已有内核等高级选项。
//
// 参数:
//   - options: 会话选项
//
// 返回值:
//   - *Session: 创建的会话信息
//   - error: 请求错误（如有）
func (c *Client) CreateSessionWithOptions(options *SessionOptions) (*Session, error) {
	// 构建请求 URL
	url := fmt.Sprintf("%s/api/sessions", c.baseURL)

	// 构建请求体
	reqBody := &SessionCreateRequest{
		Path: options.Path,
		Name: options.Name,
	}

	// 设置会话类型
	if options.Type != "" {
		reqBody.Type = options.Type
	} else {
		reqBody.Type = DefaultSessionType
	}

	// 设置内核信息
	if options.KernelID != "" {
		// 如果提供了内核 ID，使用已有内核
		reqBody.Kernel = &KernelSpec{
			ID: options.KernelID,
		}
	} else if options.KernelName != "" {
		// 如果提供了内核名称，启动新内核
		reqBody.Kernel = &KernelSpec{
			Name: options.KernelName,
		}
	}

	// 序列化请求体为 JSON
	jsonData, err := json.Marshal(reqBody)
	if err != nil {
		return nil, fmt.Errorf("failed to serialize request: %w", err)
	}

	// 创建 POST 请求
	req, err := http.NewRequest(http.MethodPost, url, bytes.NewBuffer(jsonData))
	if err != nil {
		return nil, fmt.Errorf("failed to create request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")

	// 发送请求
	resp, err := c.httpClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("failed to send request: %w", err)
	}
	defer resp.Body.Close()

	// 检查响应状态
	if resp.StatusCode != http.StatusCreated && resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("server returned error status code: %d", resp.StatusCode)
	}

	// 读取响应内容
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("failed to read response: %w", err)
	}

	// 解析 JSON 响应
	var session Session
	if err := json.Unmarshal(body, &session); err != nil {
		return nil, fmt.Errorf("failed to parse response: %w", err)
	}

	return &session, nil
}
