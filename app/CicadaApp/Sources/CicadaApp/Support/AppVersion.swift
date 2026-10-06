import Foundation

/// G182 — the app's own version, from the Info.plist `bundle.sh` writes: `CFBundleShortVersionString` is the repo's
/// one `VERSION` file (the backend's `/healthz` and the MCP server's `serverInfo` read the same file) and
/// `CFBundleVersion` is the build number, which only ever grows. A bundle-less test binary has neither.
struct AppVersion: Equatable {
    let short: String?
    let build: String?

    static func current(info: [String: Any]? = Bundle.main.infoDictionary) -> AppVersion {
        func value(_ key: String) -> String? {
            guard let s = (info?[key] as? String)?.trimmingCharacters(in: .whitespaces), !s.isEmpty else { return nil }
            return s
        }
        return AppVersion(short: value("CFBundleShortVersionString"), build: value("CFBundleVersion"))
    }

    /// True only when both sides are known and differ: an app updated while an older backend keeps running (the
    /// background service survives the swap), or a checkout moved on without a rebuild. A backend that hasn't
    /// answered yet is not a mismatch.
    func differs(fromBackend backend: String?) -> Bool {
        guard let short, let backend = backend?.trimmingCharacters(in: .whitespaces), !backend.isEmpty else { return false }
        return short != backend
    }
}
