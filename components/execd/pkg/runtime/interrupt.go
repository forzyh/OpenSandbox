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

//go:build !windows
// +build !windows

package runtime

import (
	"errors"
	"fmt"
	"os"
	"strings"
	"syscall"
	"time"

	"github.com/alibaba/opensandbox/execd/pkg/log"
)

// Interrupt 中断指定会话中的执行
//
// 本方法根据会话类型采用不同的中断策略：
//   - Jupyter 内核会话：调用 Jupyter API 中断内核
//   - 命令执行会话：发送 SIGTERM 信号，超时后发送 SIGKILL
//   - Bash 会话：关闭会话并终止进程组
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
	case c.getBashSession(sessionID) != nil:
		// Bash 会话：关闭会话
		return c.closeBashSession(sessionID)
	default:
		return errors.New("no such session")
	}
}

// killPid 终止指定 PID 的进程
//
// 本方法采用两阶段终止策略：
// 1. 首先发送 SIGTERM 信号，给进程优雅退出的机会
// 2. 如果 3 秒后进程仍未退出，发送 SIGKILL 强制终止
// 3. 确认进程已终止后返回
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

	// 第一阶段：发送 SIGTERM 信号
	if err := process.Signal(syscall.SIGTERM); err != nil {
		// 如果进程已经结束，直接返回成功
		if strings.Contains(err.Error(), "already finished") {
			return nil
		}
		log.Warning("SIGTERM failed for pid %d: %v, trying SIGKILL", pid, err)
	} else {
		// 等待进程退出
		done := make(chan error, 1)
		go func() {
			_, err := process.Wait()
			done <- err
		}()

		select {
		case err := <-done:
			if err == nil {
				log.Info("Process %d terminated gracefully", pid)
				return nil
			}
		case <-time.After(3 * time.Second):
			log.Warning("Process %d did not terminate after SIGTERM, using SIGKILL", pid)
		}
	}

	// 第二阶段：发送 SIGKILL 强制终止
	if err := process.Signal(syscall.SIGKILL); err != nil {
		if strings.Contains(err.Error(), "already finished") {
			return nil
		}
		return fmt.Errorf("failed to kill process %d: %w", pid, err)
	}

	// 确认进程已终止
	for range 3 {
		if err := process.Signal(syscall.Signal(0)); err != nil {
			if strings.Contains(err.Error(), "already finished") ||
				strings.Contains(err.Error(), "no such process") {
				log.Info("Process %d confirmed terminated", pid)
				return nil
			}
		}
		time.Sleep(50 * time.Millisecond)
	}

	return fmt.Errorf("process %d might still be running", pid)
}
