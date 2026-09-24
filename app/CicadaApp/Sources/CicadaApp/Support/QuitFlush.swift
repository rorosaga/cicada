import AppKit

/// DR-42 (R-DI3) — ⌘Q inside an Undo window sends the answer first, so a tap is never lost to
/// quitting; a backend that is gone never holds the app open past `quitFlushLimit`.
enum QuitFlush {
    static func reply(hasHeld: Bool) -> NSApplication.TerminateReply {
        hasHeld ? .terminateLater : .terminateNow
    }

    /// Runs `send`, but returns by `limit` at the latest. True when the send finished in time.
    /// `withTaskGroup` waits for every child, so the cap holds because the losing child is CANCELLED and
    /// the send is cancellation-aware: `perform` → `URLSession` drops its request on cancellation.
    @MainActor
    static func run(_ send: @escaping @MainActor () async -> Void, limit: Duration) async -> Bool {
        await withTaskGroup(of: Bool.self) { group in
            group.addTask { await send(); return true }
            group.addTask { try? await Task.sleep(for: limit); return false }
            let first = await group.next() ?? false
            group.cancelAll()
            return first
        }
    }
}
