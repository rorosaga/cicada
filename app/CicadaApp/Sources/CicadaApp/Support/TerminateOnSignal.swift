import AppKit

/// SIGTERM quits the way ⌘Q does: `NSApp.terminate`, so `applicationShouldTerminate` still sends a held Inbox answer
/// (`QuitFlush`) and the backend child is stopped. `install_app.sh` quits a running Cicada this way rather than with an
/// AppleScript `quit`, which would make macOS ask whether the calling shell may control Cicada.
enum TerminateOnSignal {
    @MainActor private static var source: DispatchSourceSignal?

    @MainActor
    static func install() {
        guard source == nil else { return }
        signal(SIGTERM, SIG_IGN)   // the dispatch source receives it instead of the default exit
        let s = DispatchSource.makeSignalSource(signal: SIGTERM, queue: .main)
        s.setEventHandler { NSApp.terminate(nil) }
        s.resume()
        source = s
    }
}
