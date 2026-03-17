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

//gogo:build linux
// +build linux

package controller

import (
	"os"
	"syscall"
	"time"
)

// getFileCreateTime 获取文件的创建时间（Linux 版本）
//
// 本函数从 Linux stat 结构体中读取文件创建时间。
// 如果无法获取创建时间，则返回修改时间作为回退。
//
// 参数:
//   - fileInfo: 文件信息
//
// 返回值:
//   - time.Time: 文件创建时间
func getFileCreateTime(fileInfo os.FileInfo) time.Time {
	stat, ok := fileInfo.Sys().(*syscall.Stat_t)
	if !ok || stat == nil {
		return fileInfo.ModTime()
	}

	return time.Unix(stat.Ctim.Sec, stat.Ctim.Nsec)
}
