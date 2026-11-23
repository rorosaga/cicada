import Foundation
import XCTest

/// Every settings suite a test makes, kept out of `~/Library/Preferences` (2026-11-23: about 60,000 suite files had
/// piled up there, one per test run per suite — `removePersistentDomain` empties a suite but leaves its file).
///
/// A suite named by an absolute path is stored at that path, so every test suite lives in one folder of this run's own
/// under the temporary directory, removed when the test bundle finishes. A run that crashed leaves its folder behind;
/// the next run removes every folder whose process is gone. `TestDefaultsLintTests` keeps tests on this door.
enum TestDefaults {
    /// The suite `name`, stored in this run's folder (same optionality as `UserDefaults(suiteName:)`).
    static func suite(_ name: String) -> UserDefaults? { UserDefaults(suiteName: path(name)) }

    /// The domain name a suite made here goes by — for `removePersistentDomain(forName:)`.
    static func path(_ name: String) -> String {
        root.appendingPathComponent(name.replacingOccurrences(of: "/", with: "_")).path
    }

    static let parent = FileManager.default.temporaryDirectory.appendingPathComponent("cicada-test-defaults",
                                                                                   isDirectory: true)

    private static let root: URL = {
        let fm = FileManager.default
        try? fm.createDirectory(at: parent, withIntermediateDirectories: true)
        sweepAbandoned()
        let dir = parent.appendingPathComponent(String(ProcessInfo.processInfo.processIdentifier), isDirectory: true)
        try? fm.createDirectory(at: dir, withIntermediateDirectories: true)
        Cleanup.register(dir)
        return dir
    }()

    /// The folders of runs that ended without cleaning up (a crash, a killed run).
    private static func sweepAbandoned() {
        let fm = FileManager.default
        let me = ProcessInfo.processInfo.processIdentifier
        for folder in (try? fm.contentsOfDirectory(at: parent, includingPropertiesForKeys: nil)) ?? [] {
            guard let pid = Int32(folder.lastPathComponent), pid != me else { continue }
            if kill(pid, 0) != 0 && errno == ESRCH { try? fm.removeItem(at: folder) }
        }
    }

    private final class Cleanup: NSObject, XCTestObservation {
        let dir: URL
        init(dir: URL) { self.dir = dir }

        /// Held here: the observation center does not keep its observers alive.
        private static var held: Cleanup?

        static func register(_ dir: URL) {
            let observer = Cleanup(dir: dir)
            held = observer
            let add = { XCTestObservationCenter.shared.addTestObserver(observer) }
            if Thread.isMainThread { add() } else { DispatchQueue.main.async(execute: add) }
        }

        func testBundleDidFinish(_ testBundle: Bundle) { try? FileManager.default.removeItem(at: dir) }
    }
}
