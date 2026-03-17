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

//go:build !linux
// +build !linux

package controller

import (
	"os"
	"time"
)

// getFileCreateTime 获取文件的创建时间（非 Linux 版本）
//
// 在非 Linux 系统上，返回当前时间作为占位符。
//
// 参数:
//   - _ os.FileInfo: 文件信息（未使用）
//
// 返回值:
//   - time.Time: 当前时间
func getFileCreateTime(_ os.FileInfo) time.Time {
	return time.Now()
}
