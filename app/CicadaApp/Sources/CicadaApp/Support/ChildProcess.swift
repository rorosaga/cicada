import Foundation

/// One child `Process`, never a shell: both pipes drained while it runs, a timeout, and the child killed when the
/// awaiting Task is cancelled. Shared by the app's readers that run a system tool as Cicada's own child — so a macOS
/// prompt names Cicada, not the launchd backend's interpreter (the `~/Library` rail): `AppleNotesReader` (`osascript`)
/// and `GitRunner` (`git` in a repo a page declares).
enum ChildProcess {
    struct Output: Equatable, Sendable {
        let status: Int32
        let stdout: String
        let stderr: String
        let timedOut: Bool
        /// The executable could not be started (missing, not executable).
        let launchFailed: Bool
        /// The awaiting Task was cancelled; the child was terminated or never started.
        let cancelled: Bool

        init(status: Int32, stdout: String, stderr: String, timedOut: Bool = false,
             launchFailed: Bool = false, cancelled: Bool = false) {
            self.status = status
            self.stdout = stdout
            self.stderr = stderr
            self.timedOut = timedOut
            self.launchFailed = launchFailed
            self.cancelled = cancelled
        }
    }

    /// Runs `executable` with `arguments`. `environment` nil inherits the app's. Both pipes drain on their own
    /// threads — an output far larger than a pipe's buffer would deadlock a read-at-exit.
    static func run(_ executable: URL, arguments: [String], environment: [String: String]? = nil,
                    timeout: TimeInterval) async -> Output {
        let running = RunningProcess()
        return await withTaskCancellationHandler {
            await withCheckedContinuation { (continuation: CheckedContinuation<Output, Never>) in
                DispatchQueue.global(qos: .userInitiated).async {
                    let process = Process()
                    process.executableURL = executable
                    process.arguments = arguments
                    if let environment { process.environment = environment }
                    let out = Pipe(), err = Pipe()
                    process.standardOutput = out
                    process.standardError = err
                    process.standardInput = FileHandle.nullDevice
                    guard running.mayStart else {
                        continuation.resume(returning: Output(status: -1, stdout: "", stderr: "", cancelled: true))
                        return
                    }
                    do {
                        try process.run()
                    } catch {
                        continuation.resume(returning: Output(status: 127, stdout: "", stderr: "", launchFailed: true))
                        return
                    }
                    running.started(process)
                    let timedOut = TimeoutFlag()
                    let timer = DispatchWorkItem {
                        if process.isRunning {
                            timedOut.set()
                            process.terminate()
                        }
                    }
                    DispatchQueue.global().asyncAfter(deadline: .now() + timeout, execute: timer)
                    let errors = ErrorBuffer()
                    let group = DispatchGroup()
                    group.enter()
                    DispatchQueue.global().async {
                        errors.data = err.fileHandleForReading.readDataToEndOfFile()
                        group.leave()
                    }
                    let data = out.fileHandleForReading.readDataToEndOfFile()
                    group.wait()
                    process.waitUntilExit()
                    timer.cancel()
                    continuation.resume(returning: Output(status: process.terminationStatus,
                                                          stdout: String(decoding: data, as: UTF8.self),
                                                          stderr: String(decoding: errors.data, as: UTF8.self),
                                                          timedOut: timedOut.isSet,
                                                          cancelled: running.wasCancelled))
                }
            }
        } onCancel: {
            running.cancel()
        }
    }
}

/// The child a cancellation must reach. `cancel` may land before `started` (the child is then terminated as soon
/// as it exists) or before launch (it never starts).
private final class RunningProcess: @unchecked Sendable {
    private let lock = NSLock()
    private var process: Process?
    private var cancelled = false

    var mayStart: Bool { lock.lock(); defer { lock.unlock() }; return !cancelled }
    var wasCancelled: Bool { lock.lock(); defer { lock.unlock() }; return cancelled }

    func started(_ p: Process) {
        lock.lock()
        process = p
        let kill = cancelled
        lock.unlock()
        if kill, p.isRunning { p.terminate() }
    }

    func cancel() {
        lock.lock()
        cancelled = true
        let p = process
        lock.unlock()
        if let p, p.isRunning { p.terminate() }
    }
}

/// Written by the stderr reader and read only after `group.wait()`, so the group orders the two accesses.
private final class ErrorBuffer: @unchecked Sendable {
    var data = Data()
}

private final class TimeoutFlag: @unchecked Sendable {
    private let lock = NSLock()
    private var value = false

    func set() { lock.lock(); value = true; lock.unlock() }

    var isSet: Bool { lock.lock(); defer { lock.unlock() }; return value }
}
