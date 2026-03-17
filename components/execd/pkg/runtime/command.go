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

/*
Package runtime 提供代码和命令执行的运行时实现。

本文件（command.go）负责 shell 命令的执行，包括：

1. 同步命令执行（runCommand）
   - 实时捕获 stdout/stderr 并流式输出
   - 支持信号转发（如 Ctrl+C 中断）
   - 用户权限控制（UID/GID）
   - 环境变量配置

2. 后台命令执行（runBackgroundCommand）
   - 命令在后台运行，不阻塞调用
   - 输出重定向到文件，可后续读取
   - 支持超时自动终止
   - 进程组管理

关键概念：
- commandKernel: 命令执行的内核结构，保存进程信息和状态
- session: 命令执行的会话 ID，用于标识和追踪
- 进程组：使用 Setpgid 创建独立进程组，便于信号管理

安全特性：
- 用户权限隔离（通过 UID/GID）
- 进程组隔离（防止进程逃逸）
- 超时控制（防止无限期执行）
- stdin 禁用（防止交互式程序阻塞）
*/
package runtime

import (
	"context"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"os/signal"
	"os/user"
	"strconv"
	"sync"
	"syscall"
	"time"

	"github.com/alibaba/opensandbox/execd/pkg/jupyter/execute" // 执行结果输出类型
	"github.com/alibaba/opensandbox/execd/pkg/log"            // 日志系统
	"github.com/alibaba/opensandbox/execd/pkg/util/safego"    // 安全的 goroutine 启动
)

// getShell 返回优先使用的 shell。
//
// 在 Linux/Unix 系统中，bash 是最常用的 shell，但某些精简的 Docker 镜像
// （如 Alpine）可能只包含 sh。此函数会检测 bash 是否存在，如果不存在
// 则回退到 sh。
//
// 返回值：shell 路径（bash 或 sh）
func getShell() string {
	// exec.LookPath 在 PATH 环境变量中查找可执行文件
	if _, err := exec.LookPath("bash"); err == nil {
		return "bash"
	}
	return "sh"
}

// buildCredential 构建进程的用户凭证。
//
// 此函数用于设置命令执行的用户身份，包括：
//   - UID：用户 ID
//   - GID：组 ID
//   - Groups：补充组列表
//
// 参数：
//   - uid: 用户 ID（可选，为 nil 时使用当前用户）
//   - gid: 组 ID（可选，为 nil 时使用用户的主组）
//
// 返回值：
//   - *syscall.Credential: 凭证结构，用于设置进程的 Unix 身份
//   - error: 错误信息
//
// 实现细节：
//   1. 如果 uid 和 gid 都为 nil，返回 nil（不切换用户）
//   2. 如果提供了 uid，查询用户信息获取主组和补充组
//   3. 如果同时提供了 gid，覆盖主组设置
func buildCredential(uid, gid *uint32) (*syscall.Credential, error) {
	// 如果都没有提供，不需要切换用户
	if uid == nil && gid == nil {
		return nil, nil //nolint:nilnil
	}

	// 创建凭证结构
	cred := &syscall.Credential{}

	// 如果提供了 UID
	if uid != nil {
		cred.Uid = *uid

		// 查询用户信息，获取主组和补充组
		u, err := user.LookupId(strconv.FormatUint(uint64(*uid), 10))
		if err == nil {
			// 如果没有显式指定 GID，使用用户的主组
			if gid == nil {
				primaryGid, err := strconv.ParseUint(u.Gid, 10, 32)
				if err == nil {
					cred.Gid = uint32(primaryGid)
				}
			}

			// 加载用户的补充组列表
			// 补充组是用户除了主组之外所属的其他组
			gids, err := u.GroupIds()
			if err == nil {
				for _, g := range gids {
					id, err := strconv.ParseUint(g, 10, 32)
					if err == nil {
						cred.Groups = append(cred.Groups, uint32(id))
					}
				}
			}
		}
	}

	// 如果显式提供了 GID，覆盖之前的设置
	if gid != nil {
		cred.Gid = *gid
	}

	return cred, nil
}

// runCommand 同步执行 shell 命令并流式输出结果。
//
// 这是命令执行的核心实现，支持：
//   - 实时输出捕获（stdout 和 stderr 分别处理）
//   - 信号转发（将终端信号转发给子进程）
//   - 用户权限控制
//   - 工作目录设置
//   - 环境变量注入
//   - 错误处理和堆栈追踪
//
// 参数：
//   - ctx: 上下文，用于取消执行
//   - request: 执行请求，包含命令、超时、用户信息等
//
// 执行流程：
//   1. 创建会话 ID 和日志文件
//   2. 配置信号处理
//   3. 创建命令进程
//   4. 启动 goroutine 监听输出文件
//   5. 启动进程并发送初始化事件
//   6. 启动信号转发 goroutine
//   7. 等待进程结束
//   8. 发送完成或错误事件
func (c *Controller) runCommand(ctx context.Context, request *ExecuteCodeRequest) error {
	// 生成唯一的会话 ID
	session := c.newContextID()

	// 创建信号通道，用于接收和转发信号
	signals := make(chan os.Signal, 1)
	defer close(signals)
	signal.Notify(signals)   // 订阅所有信号
	defer signal.Reset()     // 清理信号订阅

	// 获取标准输出和标准错误的文件描述符
	// 这些文件用于捕获命令的输出
	stdout, stderr, err := c.stdLogDescriptor(session)
	if err != nil {
		return fmt.Errorf("failed to get stdlog descriptor: %w", err)
	}

	// 获取日志文件路径，用于后续的 tail 读取
	stdoutPath := c.stdoutFileName(session)
	stderrPath := c.stderrFileName(session)

	// 记录开始时间，用于计算执行耗时
	startAt := time.Now()

	// 记录收到的命令（用于调试和审计）
	log.Info("received command: %v", request.Code)

	// 获取要使用的 shell（bash 或 sh）
	shell := getShell()

	// 创建命令
	// exec.CommandContext 会自动处理上下文取消
	// shell -c 表示通过 shell 执行后续的命令字符串
	cmd := exec.CommandContext(ctx, shell, "-c", request.Code)

	// 配置用户凭证和进程组
	cred, err := buildCredential(request.Uid, request.Gid)
	if err != nil {
		return fmt.Errorf("failed to build credential: %w", err)
	}

	// 设置进程属性
	cmd.SysProcAttr = &syscall.SysProcAttr{
		// 创建新的进程组
		// 这样可以将整个进程组一起终止，防止子进程逃逸
		Setpgid:    true,
		// 用户凭证，用于切换用户身份
		Credential: cred,
	}

	// 设置输出重定向
	cmd.Stdout = stdout
	cmd.Stderr = stderr

	// 合并环境变量
	// 1. 加载额外的环境配置文件
	// 2. 合并请求中指定的环境变量
	extraEnv := mergeExtraEnvs(loadExtraEnvFromFile(), request.Envs)
	cmd.Env = mergeEnvs(os.Environ(), extraEnv)

	// 设置工作目录
	cmd.Dir = request.Cwd

	// 创建完成通知通道
	done := make(chan struct{}, 1)

	// 使用 WaitGroup 等待两个 tail goroutine 完成
	var wg sync.WaitGroup
	wg.Add(2)

	// 启动 goroutine 监听标准输出
	// tailStdPipe 会持续读取日志文件并将内容发送给钩子函数
	safego.Go(func() {
		defer wg.Done()
		c.tailStdPipe(stdoutPath, request.Hooks.OnExecuteStdout, done)
	})

	// 启动 goroutine 监听标准错误
	safego.Go(func() {
		defer wg.Done()
		c.tailStdPipe(stderrPath, request.Hooks.OnExecuteStderr, done)
	})

	// 启动进程
	err = cmd.Start()
	if err != nil {
		// 启动失败，发送错误事件
		request.Hooks.OnExecuteInit(session)
		request.Hooks.OnExecuteError(&execute.ErrorOutput{EName: "CommandExecError", EValue: err.Error()})
		log.Error("CommandExecError: error starting commands: %v", err)
		return nil
	}

	// 创建命令内核对象，保存进程状态
	kernel := &commandKernel{
		pid:          cmd.Process.Pid,    // 进程 ID
		stdoutPath:   stdoutPath,         // 标准输出日志路径
		stderrPath:   stderrPath,         // 标准错误日志路径
		startedAt:    startAt,            // 开始时间
		running:      true,               // 运行状态
		content:      request.Code,       // 执行的命令内容
		isBackground: false,              // 同步执行标志
	}

	// 存储内核对象，供后续查询和中断使用
	c.storeCommandKernel(session, kernel)

	// 发送初始化事件
	request.Hooks.OnExecuteInit(session)

	// 启动信号转发 goroutine
	// 将接收到的信号转发给子进程，实现类似终端的行为
	go func() {
		for {
			select {
			case <-ctx.Done():
				// 上下文取消，退出信号转发
				return
			case sig := <-signals:
				if sig == nil {
					continue
				}
				// 不要转发 SIGCHLD 和 SIGURG 给子进程
				// SIGCHLD 是子进程状态变化时发送的信号
				// SIGURG 是紧急数据到达时发送的信号
				if sig != syscall.SIGCHLD && sig != syscall.SIGURG {
					// 负号表示发送给整个进程组
					_ = syscall.Kill(-cmd.Process.Pid, sig.(syscall.Signal))
				}
			}
		}
	}()

	// 等待进程结束
	err = cmd.Wait()

	// 通知 tail goroutine 停止
	close(done)

	// 等待 tail goroutine 完成
	wg.Wait()

	// 处理执行结果
	if err != nil {
		// 定义错误信息
		var eName, eValue string
		var eCode int
		var traceback []string

		// 尝试解析为 ExitError，获取退出码
		var exitError *exec.ExitError
		if errors.As(err, &exitError) {
			exitCode := exitError.ExitCode()
			eName = "CommandExecError"
			eValue = strconv.Itoa(exitCode)
			eCode = exitCode
		} else {
			// 其他类型的错误
			eName = "CommandExecError"
			eValue = err.Error()
			eCode = 1
		}

		// 堆栈追踪
		traceback = []string{err.Error()}

		// 发送错误事件
		request.Hooks.OnExecuteError(&execute.ErrorOutput{
			EName:     eName,
			EValue:    eValue,
			Traceback: traceback,
		})

		// 记录错误日志
		log.Error("CommandExecError: error running commands: %v", err)

		// 标记命令执行完成（失败）
		c.markCommandFinished(session, eCode, err.Error())
		return nil
	}

	// 标记命令执行完成（成功）
	c.markCommandFinished(session, 0, "")

	// 发送完成事件，包含执行耗时
	request.Hooks.OnExecuteComplete(time.Since(startAt))
	return nil
}

// runBackgroundCommand 在后台执行 shell 命令。
//
// 与 runCommand 不同，后台命令：
//   - 不阻塞调用，立即返回
//   - 输出重定向到单个合并文件
//   - 适合长时间运行的任务
//   - 需要通过其他接口查询状态和获取输出
//
// 参数：
//   - ctx: 上下文，用于取消执行
//   - cancel: 取消函数，用于在执行完成时取消上下文
//   - request: 执行请求
//
// 执行流程：
//   1. 创建会话 ID 和合并输出文件
//   2. 配置信号处理
//   3. 创建并启动命令进程
//   4. 在 goroutine 中等待进程完成
//   5. 启动超时/取消处理 goroutine
func (c *Controller) runBackgroundCommand(ctx context.Context, cancel context.CancelFunc, request *ExecuteCodeRequest) error {
	// 生成会话 ID
	session := c.newContextID()

	// 发送初始化事件
	request.Hooks.OnExecuteInit(session)

	// 获取合并输出文件描述符（stdout 和 stderr 合并）
	pipe, err := c.combinedOutputDescriptor(session)
	if err != nil {
		cancel()
		return fmt.Errorf("failed to get combined output descriptor: %w", err)
	}

	// 获取输出文件路径
	stdoutPath := c.combinedOutputFileName(session)
	stderrPath := c.combinedOutputFileName(session) // 后台模式下使用同一文件

	// 创建信号通道
	signals := make(chan os.Signal, 1)
	defer close(signals)
	signal.Notify(signals)
	defer signal.Reset()

	// 记录开始时间
	startAt := time.Now()

	// 记录收到的命令
	log.Info("received command: %v", request.Code)

	// 获取 shell
	shell := getShell()

	// 创建命令
	cmd := exec.CommandContext(ctx, shell, "-c", request.Code)

	// 设置工作目录
	cmd.Dir = request.Cwd

	// 配置用户凭证
	cred, err := buildCredential(request.Uid, request.Gid)
	if err != nil {
		// 记录错误但不中断执行
		log.Error("failed to build credentials: %v", err)
	}

	// 设置进程属性
	cmd.SysProcAttr = &syscall.SysProcAttr{
		Setpgid:    true,       // 创建新进程组
		Credential: cred,       // 用户凭证
	}

	// 设置输出重定向（合并到同一管道）
	cmd.Stdout = pipe
	cmd.Stderr = pipe

	// 合并环境变量
	extraEnv := mergeExtraEnvs(loadExtraEnvFromFile(), request.Envs)
	cmd.Env = mergeEnvs(os.Environ(), extraEnv)

	// 使用 /dev/null 作为标准输入
	// 这样交互式程序会立即退出，而不是等待输入
	cmd.Stdin = os.NewFile(uintptr(syscall.Stdin), os.DevNull)

	// 启动进程
	err = cmd.Start()

	// 创建内核对象
	kernel := &commandKernel{
		pid:          -1,           // 进程 ID（启动后设置）
		stdoutPath:   stdoutPath,   // 输出文件路径
		stderrPath:   stderrPath,   // 错误文件路径
		startedAt:    startAt,      // 开始时间
		running:      true,         // 运行状态
		content:      request.Code, // 命令内容
		isBackground: true,         // 后台执行标志
	}

	// 启动失败处理
	if err != nil {
		cancel()
		log.Error("CommandExecError: error starting commands: %v", err)
		kernel.running = false
		c.storeCommandKernel(session, kernel)
		c.markCommandFinished(session, 255, err.Error())
		return fmt.Errorf("failed to start commands: %w", err)
	}

	// 启动 goroutine 等待进程完成
	safego.Go(func() {
		defer pipe.Close()

		// 设置进程 ID 并存储内核对象
		kernel.running = true
		kernel.pid = cmd.Process.Pid
		c.storeCommandKernel(session, kernel)

		// 等待进程结束
		err = cmd.Wait()

		// 取消上下文
		cancel()

		// 处理执行结果
		if err != nil {
			log.Error("CommandExecError: error running commands: %v", err)
			exitCode := 1
			var exitError *exec.ExitError
			if errors.As(err, &exitError) {
				exitCode = exitError.ExitCode()
			}
			c.markCommandFinished(session, exitCode, err.Error())
			return
		}
		c.markCommandFinished(session, 0, "")
	})

	// 启动超时处理 goroutine
	// 确保在上下文取消（如超时）时终止整个进程组
	safego.Go(func() {
		<-ctx.Done()
		if cmd.Process != nil {
			// 负号表示发送给整个进程组
			// SIGKILL 强制终止进程，不可忽略
			_ = syscall.Kill(-cmd.Process.Pid, syscall.SIGKILL) // best-effort
		}
	})

	// 发送完成事件
	request.Hooks.OnExecuteComplete(time.Since(startAt))
	return nil
}
