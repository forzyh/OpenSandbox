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

// Package auth 提供 Jupyter 服务器的认证功能
//
// 本包封装了与 Jupyter 服务器通信时的认证逻辑，支持两种认证方式：
// 1. Token 认证：通过 Authorization: token <token> 请求头或 URL 查询参数传递 token
// 2. Basic 认证：通过 HTTP Basic Authentication 传递用户名和密码
//
// 主要类型：
//   - Auth: 认证配置结构体
//   - Client: 自动添加认证信息的 HTTP 客户端包装器
package auth

import (
	"fmt"
	"io"
	"net/http"
)

// Client 是 http.Client 的包装器，自动为请求添加认证头
//
// Client 封装了标准的 HTTP 客户端，在发送请求前会根据配置的 Auth 信息
// 自动添加相应的认证头（Token 或 Basic Auth），简化了需要认证的 HTTP 请求操作。
type Client struct {
	// httpClient 底层 HTTP 客户端
	httpClient *http.Client

	// auth 认证配置信息
	auth *Auth
}

// NewClient 创建一个新的带认证的 HTTP 客户端
//
// 参数:
//   - httpClient: 底层 HTTP 客户端实例
//   - auth: 认证配置，可为 nil（表示不使用认证）
//
// 返回值:
//   - *Client: 新创建的认证客户端实例
func NewClient(httpClient *http.Client, auth *Auth) *Client {
	return &Client{
		httpClient: httpClient,
		auth:       auth,
	}
}

// Do 发送 HTTP 请求并自动添加认证信息
//
// 本方法会根据 auth 配置自动为请求添加认证头：
//   - 如果 auth 为 nil，直接发送原始请求
//   - 如果 Token 非空，添加 "Authorization: token <token>" 请求头
//   - 如果 Username 非空，使用 HTTP Basic Authentication
//
// 参数:
//   - req: HTTP 请求对象
//
// 返回值:
//   - *http.Response: HTTP 响应
//   - error: 请求错误（如有）
func (c *Client) Do(req *http.Request) (*http.Response, error) {
	// 如果没有配置认证，直接发送原始请求
	if c.auth == nil {
		return c.httpClient.Do(req)
	}

	// 根据认证类型添加相应的认证头
	if c.auth.Token != "" {
		// Token 认证模式
		req.Header.Set("Authorization", fmt.Sprintf("token %s", c.auth.Token))
	} else if c.auth.Username != "" {
		// Basic 认证模式
		req.SetBasicAuth(c.auth.Username, c.auth.Password)
	}

	return c.httpClient.Do(req)
}

// Get 发送 GET 请求
//
// 创建一个 GET 请求并自动添加认证信息。
//
// 参数:
//   - url: 请求 URL
//
// 返回值:
//   - *http.Response: HTTP 响应
//   - error: 请求错误（如有）
func (c *Client) Get(url string) (*http.Response, error) {
	req, err := http.NewRequest(http.MethodGet, url, nil)
	if err != nil {
		return nil, err
	}
	return c.Do(req)
}

// Post 发送 POST 请求（实际使用 PUT 方法）
//
// 创建一个 PUT 请求并自动添加认证信息和 Content-Type 头。
// 注意：方法名为 Post 但实际发送的是 PUT 请求，这可能是为了向后兼容。
//
// 参数:
//   - url: 请求 URL
//   - contentType: 请求体内容类型（如 "application/json"）
//   - body: 请求体数据读取器
//
// 返回值:
//   - *http.Response: HTTP 响应
//   - error: 请求错误（如有）
func (c *Client) Post(url, contentType string, body io.Reader) (*http.Response, error) {
	req, err := http.NewRequest(http.MethodPut, url, body)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", contentType)
	return c.Do(req)
}

// Put 发送 PUT 请求
//
// 创建一个 PUT 请求并自动添加认证信息和 Content-Type 头。
//
// 参数:
//   - url: 请求 URL
//   - contentType: 请求体内容类型（如 "application/json"）
//   - body: 请求体数据读取器
//
// 返回值:
//   - *http.Response: HTTP 响应
//   - error: 请求错误（如有）
func (c *Client) Put(url, contentType string, body io.Reader) (*http.Response, error) {
	req, err := http.NewRequest(http.MethodPut, url, body)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", contentType)
	return c.Do(req)
}

// Delete 发送 DELETE 请求
//
// 创建一个 DELETE 请求并自动添加认证信息。
//
// 参数:
//   - url: 请求 URL
//
// 返回值:
//   - *http.Response: HTTP 响应
//   - error: 请求错误（如有）
func (c *Client) Delete(url string) (*http.Response, error) {
	req, err := http.NewRequest(http.MethodDelete, url, nil)
	if err != nil {
		return nil, err
	}
	return c.Do(req)
}
