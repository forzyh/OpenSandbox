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

//go:build windows
// +build windows

package runtime

import (
	"errors"
	"fmt"
	"os"
	"time"

	"github.com/alibaba/opensandbox/execd/pkg/log"
)

// Interrupt 中断指定会话中的执行（Windows 版本）
//
// 本方法根据会话类型采用不同的中断策略：
//   - Jupyter 内核会话：调用 Jupyter API 中断内核
//   - 命令执行会话：调用进程 Kill 方法
//
// 注意：Windows 版本不支持 Bash 会话。
//
// 参数:
//   - sessionID: 会话 ID
//
// 返回值:
//   - error: 中断错误（如会话不存在）
func (c *Controller) Interrupt(sessionID string) error {
	switch {
	case c.getJupyterKernel(sessionID) != nil:
		// Jupyter 内核会话：调用 Jupyter API 中断
		kernel := c.getJupyterKernel(sessionID)
		log.Warning("Interrupting Jupyter kernel %s", kernel.kernelID)
		return kernel.client.InterruptKernel(kernel.kernelID)
	case c.getCommandKernel(sessionID) != nil:
		// 命令执行会话：终止进程
		kernel := c.getCommandKernel(sessionID)
		return c.killPid(kernel.pid)
	default:
		return errors.New("no such session")
	}
}

// killPid 终止指定 PID 的进程（Windows 版本）
//
// Windows 版本的进程终止直接调用 process.Kill() 方法，
// 然后等待进程退出（最多等待 3 秒）。
//
// 参数:
//   - pid: 进程 ID
//
// 返回值:
//   - error: 终止错误（如有）
func (c *Controller) killPid(pid int) error {
	process, err := os.FindProcess(pid)
	if err != nil {
		return err
	}
	log.Warning("Attempting to terminate process %d", pid)

	// Windows 直接调用 Kill 方法
	if err := process.Kill(); err != nil {
		return fmt.Errorf("failed to kill process %d: %w", pid, err)
	}

	// 等待进程退出（最佳努力，因为 os.Process.Wait 只对子进程有效）
	done := make(chan error, 1)
	go func() {
		_, err := process.Wait()
		done <- err
	}()

	select {
	case <-done:
		// 进程已退出
	case <-time.After(3 * time.Second):
		// 等待超时
		log.Warning("Process %d kill wait timed out", pid)
	}

	return nil
}
