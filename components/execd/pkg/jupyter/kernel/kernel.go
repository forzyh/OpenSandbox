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

// Package kernel 提供 Jupyter 内核管理功能。
//
// 本包封装了与 Jupyter Kernel Gateway API 的交互，提供以下能力：
//
// 1. 内核规格查询（GetKernelSpecs）
//    - 获取所有可用的编程语言内核
//    - 返回内核名称、语言、显示名称等信息
//
// 2. 内核生命周期管理
//    - ListKernels: 列出所有运行中的内核
//    - GetKernel: 获取单个内核的详细信息
//    - StartKernel: 启动新的内核
//    - RestartKernel: 重启内核（清空状态）
//    - InterruptKernel: 中断内核（发送 SIGINT）
//    - ShutdownKernel: 关闭内核（释放资源）
//
// Jupyter Kernel Gateway API 参考：
// https://jupyter-kernel-gateway.readthedocs.io/en/latest/
//
// 使用示例：
//   client := kernel.NewClient("http://localhost:8888", httpClient)
//   specs, err := client.GetKernelSpecs()
//   kernel, err := client.StartKernel("python3")
//   err = client.InterruptKernel(kernel.ID)
//   err = client.ShutdownKernel(kernel.ID, false)
package kernel

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
)

// Client 是 Jupyter 内核管理的客户端。
//
// 该客户端封装了与 Jupyter Kernel Gateway 的 HTTP 通信，
// 提供类型安全的方法来管理内核的生命周期。
//
// 结构体字段：
//   - baseURL: Jupyter Kernel Gateway 的基础 URL
//     例如："http://localhost:8888"
//   - httpClient: HTTP 客户端，支持自定义配置（如超时、认证等）
type Client struct {
	// baseURL 是 Jupyter 服务器的基础 URL
	baseURL string

	// httpClient 是用于发送 HTTP 请求的客户端，支持认证配置
	httpClient *http.Client
}

// NewClient 创建新的内核管理客户端。
//
// 参数：
//   - baseURL: Jupyter Kernel Gateway 的基础 URL
//     例如："http://localhost:8888" 或 "http://jupyter:8888"
//   - httpClient: HTTP 客户端实例
//     可以配置超时、Transport、认证等
//     如果传 nil，会使用 http.DefaultClient
//
// 返回值：
//   - *Client: 初始化好的客户端实例
//
// 使用示例：
//   client := kernel.NewClient("http://localhost:8888", &http.Client{
//       Timeout: 30 * time.Second,
//   })
func NewClient(baseURL string, httpClient *http.Client) *Client {
	return &Client{
		baseURL:    baseURL,
		httpClient: httpClient,
	}
}

// GetKernelSpecs 获取所有可用的内核规格列表。
//
// 内核规格（Kernel Spec）描述了一个内核的元数据，包括：
//   - 名称（name）：如 "python3"、"ir"
//   - 语言（language）：如 "python"、"r"
//   - 显示名称（display_name）：如 "Python 3"
//   - 可执行文件路径（argv）
//   - 图标、描述等
//
// 返回值：
//   - *KernelSpecs: 内核规格集合
//   - error: 请求错误
//
// API 端点：GET /api/kernelspecs
func (c *Client) GetKernelSpecs() (*KernelSpecs, error) {
	// 构建请求 URL
	url := fmt.Sprintf("%s/api/kernelspecs", c.baseURL)

	// 发送 GET 请求
	resp, err := c.httpClient.Get(url)
	if err != nil {
		return nil, fmt.Errorf("failed to send request: %w", err)
	}
	defer resp.Body.Close() // 确保关闭响应体，防止连接泄漏

	// 检查响应状态码
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("server returned error status code: %d", resp.StatusCode)
	}

	// 读取响应体
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("failed to read response: %w", err)
	}

	// 解析 JSON 响应
	var specs KernelSpecs
	if err := json.Unmarshal(body, &specs); err != nil {
		return nil, fmt.Errorf("failed to parse response: %w", err)
	}

	return &specs, nil
}

// ListKernels 获取所有运行中的内核列表。
//
// 此方法返回当前由 Jupyter Kernel Gateway 管理的所有活动内核。
// 可用于：
//   - 监控内核使用情况
//   - 清理空闲内核
//   - 调试和诊断
//
// 返回值：
//   - []*Kernel: 内核信息切片
//   - error: 请求错误
//
// API 端点：GET /api/kernels
func (c *Client) ListKernels() ([]*Kernel, error) {
	// 构建请求 URL
	url := fmt.Sprintf("%s/api/kernels", c.baseURL)

	// 发送 GET 请求
	resp, err := c.httpClient.Get(url)
	if err != nil {
		return nil, fmt.Errorf("failed to send request: %w", err)
	}
	defer resp.Body.Close()

	// 检查响应状态码
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("server returned error status code: %d", resp.StatusCode)
	}

	// 读取响应体
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("failed to read response: %w", err)
	}

	// 解析 JSON 响应
	var kernels []*Kernel
	if err := json.Unmarshal(body, &kernels); err != nil {
		return nil, fmt.Errorf("failed to parse response: %w", err)
	}

	return kernels, nil
}

// GetKernel 获取指定内核的详细信息。
//
// 返回的信息包括：
//   - 内核 ID
//   - 内核名称
//   - 最后活动时间
//   - 连接信息（WebSocket URL 等）
//
// 参数：
//   - kernelId: 内核的唯一标识
//
// 返回值：
//   - *Kernel: 内核信息
//   - error: 请求错误
//
// API 端点：GET /api/kernels/{kernelId}
func (c *Client) GetKernel(kernelId string) (*Kernel, error) {
	// 构建请求 URL
	url := fmt.Sprintf("%s/api/kernels/%s", c.baseURL, kernelId)

	// 发送 GET 请求
	resp, err := c.httpClient.Get(url)
	if err != nil {
		return nil, fmt.Errorf("failed to send request: %w", err)
	}
	defer resp.Body.Close()

	// 检查响应状态码
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("server returned error status code: %d", resp.StatusCode)
	}

	// 读取响应体
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("failed to read response: %w", err)
	}

	// 解析 JSON 响应
	var kernel Kernel
	if err := json.Unmarshal(body, &kernel); err != nil {
		return nil, fmt.Errorf("failed to parse response: %w", err)
	}

	return &kernel, nil
}

// StartKernel 启动新的内核。
//
// 此方法会请求 Jupyter Kernel Gateway 创建一个新的内核实例。
// 内核启动后会自动分配一个唯一的 ID。
//
// 参数：
//   - name: 内核规格名称
//     如 "python3"、"ir"、"julia" 等
//     可通过 GetKernelSpecs 获取可用的名称列表
//
// 返回值：
//   - *Kernel: 新创建的内核信息
//   - error: 请求错误
//
// API 端点：POST /api/kernels
// 请求体：{"name": "python3"}
func (c *Client) StartKernel(name string) (*Kernel, error) {
	// 构建请求 URL
	url := fmt.Sprintf("%s/api/kernels", c.baseURL)

	// 构建请求体
	reqBody := &KernelStartRequest{
		Name: name,
	}

	// 将请求体序列化为 JSON
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

	// 检查响应状态码
	// 201 Created 或 200 OK 都表示成功
	if resp.StatusCode != http.StatusCreated && resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("server returned error status code: %d", resp.StatusCode)
	}

	// 读取响应体
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("failed to read response: %w", err)
	}

	// 解析 JSON 响应
	var kernel Kernel
	if err := json.Unmarshal(body, &kernel); err != nil {
		return nil, fmt.Errorf("failed to parse response: %w", err)
	}

	return &kernel, nil
}

// RestartKernel 重启指定的内核。
//
// 重启内核会：
//   1. 清除内核的所有状态（变量、导入等）
//   2. 保留内核 ID（便于客户端继续使用）
//   3. 重新加载内核规格
//
// 使用场景：
//   - 清理被污染的執行環境
//   - 释放内存
//   - 重置到初始状态
//
// 参数：
//   - kernelId: 内核的唯一标识
//
// 返回值：
//   - bool: 是否成功重启
//   - error: 请求错误
//
// API 端点：POST /api/kernels/{kernelId}/restart
func (c *Client) RestartKernel(kernelId string) (bool, error) {
	// 构建请求 URL
	url := fmt.Sprintf("%s/api/kernels/%s/restart", c.baseURL, kernelId)

	// 创建 POST 请求（无请求体）
	req, err := http.NewRequest(http.MethodPost, url, nil)
	if err != nil {
		return false, fmt.Errorf("failed to create request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")

	// 发送请求
	resp, err := c.httpClient.Do(req)
	if err != nil {
		return false, fmt.Errorf("failed to send request: %w", err)
	}
	defer resp.Body.Close()

	// 检查响应状态码
	if resp.StatusCode != http.StatusOK {
		return false, fmt.Errorf("server returned error status code: %d", resp.StatusCode)
	}

	// 读取响应体
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return false, fmt.Errorf("failed to read response: %w", err)
	}

	// 解析 JSON 响应
	var response KernelRestartResponse
	if err := json.Unmarshal(body, &response); err != nil {
		return false, fmt.Errorf("failed to parse response: %w", err)
	}

	return response.Restarted, nil
}

// InterruptKernel 中断指定的内核。
//
// 中断内核会发送 SIGINT 信号（类似 Ctrl+C），用于：
//   - 停止长时间运行的代码
//   - 取消当前的执行请求
//   - 恢复内核到可接受新命令的状态
//
// 注意：
//   - 中断不会清除内核状态
//   - 已经执行的代码效果仍然保留
//   - 与 Restart 不同，Interrupt 是温和的停止
//
// 参数：
//   - kernelId: 内核的唯一标识
//
// 返回值：
//   - error: 请求错误
//
// API 端点：POST /api/kernels/{kernelId}/interrupt
func (c *Client) InterruptKernel(kernelId string) error {
	// 构建请求 URL
	url := fmt.Sprintf("%s/api/kernels/%s/interrupt", c.baseURL, kernelId)

	// 创建 POST 请求（无请求体）
	req, err := http.NewRequest(http.MethodPost, url, nil)
	if err != nil {
		return fmt.Errorf("failed to create request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")

	// 发送请求
	resp, err := c.httpClient.Do(req)
	if err != nil {
		return fmt.Errorf("failed to send request: %w", err)
	}
	defer resp.Body.Close()

	// 检查响应状态码
	// 204 No Content 或 200 OK 都表示成功
	if resp.StatusCode != http.StatusNoContent && resp.StatusCode != http.StatusOK {
		return fmt.Errorf("server returned error status code: %d", resp.StatusCode)
	}

	return nil
}

// ShutdownKernel 关闭指定的内核。
//
// 关闭内核会：
//   1. 终止内核进程
//   2. 释放所有资源（内存、文件句柄等）
//   3. 断开所有 WebSocket 连接
//   4. 从内核列表中移除
//
// 参数：
//   - kernelId: 内核的唯一标识
//   - restart: 是否重启标志
//     - true: 关闭后立即重启（用于重置）
//     - false: 完全关闭
//
// 返回值：
//   - error: 请求错误
//
// API 端点：DELETE /api/kernels/{kernelId}
// 请求体：{"restart": false}
func (c *Client) ShutdownKernel(kernelId string, restart bool) error {
	// 构建请求 URL
	url := fmt.Sprintf("%s/api/kernels/%s", c.baseURL, kernelId)

	// 构建请求体
	reqBody := &KernelShutdownRequest{
		Restart: restart,
	}

	// 将请求体序列化为 JSON
	jsonData, err := json.Marshal(reqBody)
	if err != nil {
		return fmt.Errorf("failed to serialize request: %w", err)
	}

	// 创建 DELETE 请求
	// 注意：虽然是 DELETE 方法，但可以带有请求体
	req, err := http.NewRequest(http.MethodDelete, url, bytes.NewBuffer(jsonData))
	if err != nil {
		return fmt.Errorf("failed to create request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")

	// 发送请求
	resp, err := c.httpClient.Do(req)
	if err != nil {
		return fmt.Errorf("failed to send request: %w", err)
	}
	defer resp.Body.Close()

	// 检查响应状态码
	// 204 No Content 或 200 OK 都表示成功
	if resp.StatusCode != http.StatusNoContent && resp.StatusCode != http.StatusOK {
		return fmt.Errorf("server returned error status code: %d", resp.StatusCode)
	}

	return nil
}
