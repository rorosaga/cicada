import Foundation

/// Track I T5 — every sentence the intake prints, pure and locale-aware. The
/// `+` sheet used to say "Imported N, skipped M" and drop G20's updated threads
/// on the floor (R7 defect 4); the `updated` clause is kept here and omitted only
/// when it is zero.
enum IntakeSummary {
    static func line(new: Int, updated: Int, unchanged: Int, locale: Locale = .autoupdatingCurrent) -> String {
        var parts = ["\(UsageFormat.count(new, locale: locale)) new"]
        if updated > 0 { parts.append("\(UsageFormat.count(updated, locale: locale)) updated") }
        parts.append("\(UsageFormat.count(unchanged, locale: locale)) unchanged")
        return parts.joined(separator: " · ")
    }

    /// A Gemini entry is one prompt and its reply (R-IA14); everything else is a conversation.
    static func noun(vendor: String?, count: Int) -> String {
        let base = vendor == "gemini" ? "prompt" : "conversation"
        return count == 1 ? base : base + "s"
    }

    static func headline(_ o: IntakeOutcome, locale: Locale = .autoupdatingCurrent) -> String {
        guard o.total > 0 else { return Copy.intakeNothingNewHeadline }
        var parts: [String] = []
        let chats = o.created + o.updated
        if chats > 0 { parts.append("\(UsageFormat.count(chats, locale: locale)) \(noun(vendor: o.vendor, count: chats))") }
        if o.savedCreated > 0 {
            parts.append("\(UsageFormat.count(o.savedCreated, locale: locale)) saved \(o.savedCreated == 1 ? "item" : "items")")
        }
        return parts.joined(separator: " and ") + (o.total == 1 ? " is in." : " are in.")
    }

    private static func month(_ day: String, locale: Locale) -> String? {
        let parse = DateFormatter()
        parse.locale = Locale(identifier: "en_US_POSIX")
        parse.timeZone = TimeZone(identifier: "UTC")
        parse.dateFormat = "yyyy-MM-dd"
        guard let date = parse.date(from: String(day.prefix(10))) else { return nil }
        let show = DateFormatter()
        show.locale = locale
        show.timeZone = TimeZone(identifier: "UTC")
        show.setLocalizedDateFormatFromTemplate("MMMyyyy")
        return show.string(from: date)
    }

    static func rangeLine(from: String?, to: String?, locale: Locale = .autoupdatingCurrent) -> String? {
        let a = from.flatMap { month($0, locale: locale) }
        let b = to.flatMap { month($0, locale: locale) }
        switch (a, b) {
        case let (a?, b?): return a == b ? a : "\(a) – \(b)"
        case let (a?, nil): return a
        case let (nil, b?): return b
        default: return nil
        }
    }

    static func previewDelta(_ d: IntakeDelta, locale: Locale = .autoupdatingCurrent) -> String {
        "\(UsageFormat.count(d.new, locale: locale)) new · \(UsageFormat.count(d.grown, locale: locale)) grew since last time · "
            + "\(UsageFormat.count(d.unchanged, locale: locale)) already here"
    }

    /// Never interpolated: the "of" form appears only once the job reported (design §5.2).
    static func importingLine(_ p: IntakeProgress, vendor: String?, locale: Locale = .autoupdatingCurrent) -> String {
        if let staged = p.staged {
            return "Bringing in \(UsageFormat.count(staged, locale: locale)) of \(UsageFormat.count(p.total, locale: locale))"
        }
        return "Bringing in \(UsageFormat.count(p.total, locale: locale)) \(noun(vendor: vendor, count: p.total))…"
    }

    static func previewTitle(_ p: IntakePreview) -> String {
        if p.chatFiles.isEmpty { return "Saved links" }
        switch p.vendor {
        case "claude": return "Claude history"
        case "chatgpt": return "ChatGPT history"
        case "gemini": return "Gemini activity"
        default: return "Chat history"
        }
    }

    static func countsLine(_ p: IntakePreview, locale: Locale = .autoupdatingCurrent) -> String {
        var parts: [String] = []
        let chats = p.counts.conversations + p.counts.prompts
        if chats > 0 { parts.append("\(UsageFormat.count(chats, locale: locale)) \(noun(vendor: p.vendor, count: chats))") }
        if p.counts.memories + p.counts.projects > 0 {
            parts.append("\(UsageFormat.count(p.counts.memories + p.counts.projects, locale: locale)) notes Claude kept")
        }
        if p.counts.items > 0 { parts.append("\(UsageFormat.count(p.counts.items, locale: locale)) saved items") }
        if let range = rangeLine(from: p.dateFrom, to: p.dateTo, locale: locale) { parts.append(range) }
        return parts.joined(separator: " · ")
    }

    static func doneDetail(_ o: IntakeOutcome, locale: Locale = .autoupdatingCurrent) -> String? {
        let parts = [rangeLine(from: o.dateFrom, to: o.dateTo, locale: locale),
                     o.updated > 0 ? "\(UsageFormat.count(o.updated, locale: locale)) grew" : nil,
                     o.unchanged > 0 ? "\(UsageFormat.count(o.unchanged, locale: locale)) unchanged" : nil].compactMap { $0 }
        return parts.isEmpty ? nil : parts.joined(separator: " · ")
    }

    static func filterCount(shown: Int, total: Int, locale: Locale = .autoupdatingCurrent) -> String {
        "\(UsageFormat.count(shown, locale: locale)) of \(UsageFormat.count(total, locale: locale))"
    }

    /// The Sources card these will show under — the Sources page's own name for
    /// it (`SourceDisplayName`), so the two cannot disagree.
    static func sourcesName(origin: String?) -> String {
        let channel = ChatVendor.allCases.first { $0.origin == origin }?.channelId ?? "files"
        return SourceDisplayName.of(id: channel)   // Views/Sources/SourceDisplayName.swift
    }
}
