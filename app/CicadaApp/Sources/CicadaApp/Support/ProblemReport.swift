import Foundation

/// Report a problem (tester readiness, 2026-10-26) — the text a person reads in the sheet before it leaves the Mac, and
/// where it goes when they press Send. Pure: the sheet passes in what it has, so the words are tested without a window.
///
/// The backend builds and redacts the body (`GET /diagnostics/report`: its version, the engine mode, source ids, the
/// logs through the scrubber — `api/services/diagnostics.py`); the app adds only what it alone knows and what names no
/// one: its own version and build, the macOS version, and the one known issue a tester should read first.
///
/// **Where Send goes (owner 2026-10-26): a private email, never a public page.** The address is not in the repo (it is
/// public): a release build carries it in its Info.plist as `CicadaReportEmail`, filled by `bundle.sh` from CI's
/// `CICADA_REPORT_EMAIL` repository variable (docs/RELEASING.md). Without it — a developer build, or before the owner
/// sets it — there is no Send at all: the sheet offers Copy and Save and says to send it to the person who gave them
/// Cicada. Nothing is ever sent by itself; Send copies the report and opens a new message.
enum ProblemReport {
    static let infoKey = "CicadaReportEmail"

    /// The release's report address, when it carries a plausible one; nil otherwise (no Send button).
    static func reportEmail(info: [String: Any]? = Bundle.main.infoDictionary) -> String? {
        guard let raw = (info?[infoKey] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines),
              raw.range(of: #"^[^@\s/?#&]+@[^@\s/?#&]+\.[^@\s/?#&]+$"#, options: .regularExpression) != nil
        else { return nil }
        return raw
    }

    /// The lines on top: the app's version and build, the macOS version, and the known issue.
    static func header(app: AppVersion, macOS: String) -> String {
        let version = app.short.map { short in app.build.map { "\(short) (build \($0))" } ?? short } ?? "development build"
        return ["Cicada problem report", "App: \(version)", "macOS: \(macOS)",
                "Known issue: \(Copy.ReportProblem.permissionsAfterUpdate)"].joined(separator: "\n")
    }

    /// The whole report: the header, then the backend's half — or, with the backend unreachable, a line that says so
    /// (that is a finding in itself).
    static func compose(header: String, backend: String?) -> String {
        let body = backend?.trimmingCharacters(in: .whitespacesAndNewlines)
        return header + "\n" + ((body?.isEmpty == false) ? body! : Copy.ReportProblem.backendUnreachable) + "\n"
    }

    static let subject = "Cicada problem report"
    /// The message Send opens with. The report itself is pasted by the person (it is on the clipboard): a mail link
    /// cannot reliably carry 200 log lines, and pasting is the last chance to read it.
    static let template = """
    What happened:


    What you expected:


    Steps to see it again:


    The report (Cicada copied it to your clipboard; read it, then paste it below):

    """

    /// `mailto:<address>?subject=…&body=…` for the release's address; nil when there is none.
    static func sendURL(email: String?) -> URL? {
        guard let email else { return nil }
        var parts = URLComponents()
        parts.scheme = "mailto"
        parts.path = email
        parts.queryItems = [URLQueryItem(name: "subject", value: subject), URLQueryItem(name: "body", value: template)]
        return parts.url
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
