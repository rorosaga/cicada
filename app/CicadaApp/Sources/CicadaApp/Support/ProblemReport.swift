import Foundation

/// Report a problem (tester readiness, 2026-10-26) — the text a person reads in the sheet before it leaves the Mac, and
/// the one place it goes when they press Send. Pure: the sheet passes in what it has, so the words are tested without
/// a window.
///
/// The backend builds and redacts the body (`GET /diagnostics/report`: its version, the engine mode, source ids, the
/// logs through the scrubber — `api/services/diagnostics.py`); the app adds only what it alone knows and what names no
/// one: its own version and build, and the macOS version. Nothing is sent on its own: Send copies the report and opens
/// `destination` with a short template; the person pastes it there, after reading it.
enum ProblemReport {
    /// THE destination of Send — the owner chooses the channel by changing this one value (a `mailto:` works too).
    /// For now the repository's public "new issue" page, which the sheet says in words.
    static let destination = URL(string: "https://github.com/rorosaga/cicada/issues/new")!

    /// Whether `destination` is a public page (an issue tracker) rather than a private channel (mail): the sheet says
    /// so above Send.
    static var destinationIsPublic: Bool { destination.scheme?.lowercased() != "mailto" }

    /// The lines on top: the app's version and build and the macOS version.
    static func header(app: AppVersion, macOS: String) -> String {
        let version = app.short.map { short in app.build.map { "\(short) (build \($0))" } ?? short } ?? "development build"
        return ["Cicada problem report", "App: \(version)", "macOS: \(macOS)"].joined(separator: "\n")
    }

    /// The whole report: the header, then the backend's half — or, with the backend unreachable, a line that says so
    /// (that is a finding in itself).
    static func compose(header: String, backend: String?) -> String {
        let body = backend?.trimmingCharacters(in: .whitespacesAndNewlines)
        return header + "\n" + ((body?.isEmpty == false) ? body! : Copy.ReportProblem.backendUnreachable) + "\n"
    }

    /// The short template Send opens with. The report itself is pasted by the person (it is on the clipboard): a URL
    /// cannot carry 200 log lines, and pasting is the last chance to read it.
    static let issueTitle = "Problem: "
    static let issueTemplate = """
    **What happened**


    **What you expected**


    **Steps to see it again**


    **Report**
    <!-- Cicada copied its report to your clipboard. Read it, then paste it below. This issue is public. -->

    """

    /// `destination` with the template: an issue page's `title` and `body`, a mail's `subject` and `body`.
    static func sendURL(destination: URL = destination) -> URL {
        guard var parts = URLComponents(url: destination, resolvingAgainstBaseURL: false) else { return destination }
        let isMail = destination.scheme?.lowercased() == "mailto"
        parts.queryItems = (parts.queryItems ?? []) + [
            URLQueryItem(name: isMail ? "subject" : "title", value: issueTitle),
            URLQueryItem(name: "body", value: issueTemplate),
        ]
        return parts.url ?? destination
    }

    /// The file name Save offers: dated, no name of anyone's.
    static func fileName(now: Date = .now) -> String {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM-dd-HHmm"
        return "cicada-report-\(f.string(from: now)).txt"
    }

    static var macOSVersion: String {
        let v = ProcessInfo.processInfo.operatingSystemVersion
        return "\(v.majorVersion).\(v.minorVersion).\(v.patchVersion)"
    }
}
