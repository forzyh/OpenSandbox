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

// Package model 定义 API 请求和响应的数据结构
//
// 本包包含 execd 服务所有 REST API 的数据模型定义，包括：
//   - 请求结构：用于解析客户端请求
//   - 响应结构：用于返回服务器响应
//   - 错误码定义：统一的错误码常量
//   - 流式事件：SSE 事件类型和数据
package model

// ErrorCode 错误码类型
//
// ErrorCode 定义了 API 错误响应的错误码类型，
// 用于标识不同类型的错误情况。
type ErrorCode string

const (
	// ErrorCodeInvalidRequest 无效的请求体
	// 当请求体格式错误或无法解析时返回
	ErrorCodeInvalidRequest ErrorCode = "INVALID_REQUEST_BODY"

	// ErrorCodeMissingQuery 缺少查询参数
	// 当必需的查询参数缺失时返回
	ErrorCodeMissingQuery ErrorCode = "MISSING_QUERY"

	// ErrorCodeRuntimeError 运行时错误
	// 当代码执行过程中发生错误时返回
	ErrorCodeRuntimeError ErrorCode = "RUNTIME_ERROR"

	// ErrorCodeInvalidFile 无效的文件
	// 当文件路径或格式无效时返回
	ErrorCodeInvalidFile ErrorCode = "INVALID_FILE"

	// ErrorCodeInvalidFileContent 无效的文件内容
	// 当文件内容格式错误时返回
	ErrorCodeInvalidFileContent ErrorCode = "INVALID_FILE_CONTENT"

	// ErrorCodeInvalidFileMetadata 无效的文件元数据
	// 当文件元数据格式错误时返回
	ErrorCodeInvalidFileMetadata ErrorCode = "INVALID_FILE_METADATA"

	// ErrorCodeFileNotFound 文件未找到
	// 当请求的文件不存在时返回
	ErrorCodeFileNotFound ErrorCode = "FILE_NOT_FOUND"

	// ErrorCodeUnknown 未知错误
	// 当发生未分类的错误时返回
	ErrorCodeUnknown ErrorCode = "UNKNOWN"

	// ErrorCodeContextNotFound 执行上下文未找到
	// 当请求的会话或上下文不存在时返回
	ErrorCodeContextNotFound ErrorCode = "CONTEXT_NOT_FOUND"
)

// ErrorResponse 错误响应结构
//
// ErrorResponse 是 API 错误响应的标准格式，
// 包含错误码和错误消息。
type ErrorResponse struct {
	// Code 错误码
	Code ErrorCode `json:"code,omitempty"`

	// Message 错误消息描述
	Message string `json:"message,omitempty"`
}
