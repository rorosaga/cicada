import Foundation

/// 2026-11-06 — what a person reads when a file they dropped did not go in: the file, what is wrong with it in plain
/// words, and what to do. An exception's own message never reaches them (G199): `localizedDescription` of a timed-out
/// request ("The request timed out."), of a Cocoa read error or of a decoder is the framework's, not Cicada's. Only a
/// sentence the backend wrote for the person (the `detail` of a 400 from `/intake`) passes through; everything else is
/// mapped here.
enum IntakeFailureWords {
    /// The reason, without the file's name (the caller puts the name in front: `line`).
    static func reason(_ error: Error) -> String {
        if let api = error as? APIError {
            switch api {
            case .httpError(let code, let body):
                if code == 404 { return Copy.intakeBackendOld }
                return detail(in: body) ?? Copy.intakeCouldNotRead
            case .serverUnreachable:
                return Copy.intakeBackendGone
            case .decodingError:
                return Copy.intakeCouldNotRead
            }
        }
        if error is IntakeRouterError { return Copy.intakeWriteStopped }
        if let url = error as? URLError {
            switch url.code {
            case .timedOut: return Copy.intakeStoppedWaiting
            case .networkConnectionLost, .cannotConnectToHost, .cannotFindHost, .notConnectedToInternet:
                return Copy.intakeBackendGone
            default: return Copy.intakeCouldNotRead
            }
        }
        if error is CocoaError { return Copy.intakeCannotOpen }
        return Copy.intakeCouldNotRead
    }

    /// "name: reason", the shape every failed file is shown in.
    static func line(name: String, error: Error) -> String { Copy.intakeFileLine(name, reason(error)) }

    /// The backend's `{"detail": "…"}`, when the body is one and the detail is a sentence (a validation error's
    /// detail is a list, which is not for a person).
    static func detail(in body: String) -> String? {
        guard let data = body.data(using: .utf8),
              let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let detail = object["detail"] as? String, !detail.isEmpty else { return nil }
        return detail
    }

    /// Several files failed: up to three lines, then the count of the rest.
    static func summary(_ failed: [(name: String, reason: String)]) -> String {
        var lines = failed.prefix(3).map { Copy.intakeFileLine($0.name, $0.reason) }
        if failed.count > 3 { lines.append(Copy.intakeAndMore(failed.count - 3)) }
        return lines.joined(separator: "\n")
    }

    /// The file's size in words, when it is big enough that reading it takes a while (a synthetic export measured
    /// 0.3 s a megabyte to read on a busy Mac, so 50 MB is where it stops being instant).
    static let bigFileBytes: Int64 = 50 * 1024 * 1024

    static func bigFileNote(_ urls: [URL]) -> String? {
        let sized = urls.compactMap { url -> (String, Int64)? in
            guard let size = (try? url.resourceValues(forKeys: [.fileSizeKey]))?.fileSize else { return nil }
            return (url.lastPathComponent, Int64(size))
        }
        guard let biggest = sized.max(by: { $0.1 < $1.1 }), biggest.1 >= bigFileBytes else { return nil }
        return Copy.intakeBigFile(biggest.0, ByteCountFormatter.string(fromByteCount: biggest.1, countStyle: .file))
    }
}
