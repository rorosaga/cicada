import CoreServices
import Foundation

/// A recursive, file-level FSEvents watch on one directory (G133, G134).
///
/// `BrowserWatch`'s `DispatchSource` is one vnode per directory and does not
/// see files changing inside subfolders — right for one bookmarks file, wrong
/// for a folder of notes or an app that writes a SQLite WAL (a WAL append
/// changes no directory entry at all). FSEvents with file events covers both.
/// Events are delivered on the main queue; the handler is expected to debounce.
final class FSEventsWatch {
    private var stream: FSEventStreamRef?
    private let handler: @MainActor () -> Void

    init?(path: String, latency: TimeInterval = 1.0, handler: @escaping @MainActor () -> Void) {
        self.handler = handler
        var context = FSEventStreamContext(version: 0, info: nil, retain: nil, release: nil, copyDescription: nil)
        context.info = Unmanaged.passUnretained(self).toOpaque()
        let callback: FSEventStreamCallback = { _, info, _, _, _, _ in
            guard let info else { return }
            let watch = Unmanaged<FSEventsWatch>.fromOpaque(info).takeUnretainedValue()
            MainActor.assumeIsolated { watch.handler() }
        }
        let flags = FSEventStreamCreateFlags(kFSEventStreamCreateFlagFileEvents | kFSEventStreamCreateFlagNoDefer)
        guard let stream = FSEventStreamCreate(kCFAllocatorDefault, callback, &context, [path] as CFArray,
                                               FSEventStreamEventId(kFSEventStreamEventIdSinceNow), latency, flags)
        else { return nil }
        self.stream = stream
        FSEventStreamSetDispatchQueue(stream, DispatchQueue.main)
        FSEventStreamStart(stream)
    }

    func stop() {
        guard let stream else { return }
        FSEventStreamStop(stream)
        FSEventStreamInvalidate(stream)
        FSEventStreamRelease(stream)
        self.stream = nil
    }

    deinit { stop() }
}
