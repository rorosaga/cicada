import Foundation

/// R-S5 — the one place a channel's state line is composed.
///
/// `channel_registry._plural` used to bake `f"{n:,} bookmarks"` into `detail`
/// and every surface printed that verbatim, so the SERVER's `en_US` grouping
/// ("1,035") sat in the same window as the app's own locale-correct grouping
/// ("1.035" for a Spanish reader) — critique B1's third convention. The server
/// has no idea what locale the reader is in, so the number could never be
/// right there: it now ships as `count` + `countNoun` (singular) +
/// `countIsDelta`, and this composer puts the line back together with
/// `UsageFormat.count` — the same formatter the card grid and the Contributors
/// strip use.
///
/// The output is byte-identical to what the registry printed before the move,
/// including the connector's `+`/" this sync" wording (`_connector_channel`'s
/// L2 note: a connector's `count` is "items pulled THIS run", not a total).
enum ChannelDetailLine {
    /// `<count phrase> · <detail>`, either half alone when the other is
    /// absent, and nil when both are.
    ///
    /// A branch with nothing to count ships no `countNoun`, which is what makes
    /// "0 pins · Last sync failed" unrepresentable rather than merely unlikely
    /// (R-S16). Pluralisation is `+ "s"`: every noun the registry and its
    /// adapters ship is regular, and
    /// `test_channel_detail_numbers.py::test_every_shipped_noun_pluralises_by_adding_s`
    /// is the rail that keeps an irregular one from arriving as "calendarys".
    static func text(_ channel: SourceChannel,
                     locale: Locale = .autoupdatingCurrent) -> String? {
        var phrase: String?
        if let noun = channel.countNoun, !noun.isEmpty {
            let number = UsageFormat.count(channel.count, locale: locale)
            let unit = channel.count == 1 ? noun : noun + "s"
            phrase = channel.countIsDelta ? "+\(number) \(unit) this sync" : "\(number) \(unit)"
        }
        let detail = (channel.detail?.isEmpty == false) ? channel.detail : nil
        switch (phrase, detail) {
        case let (phrase?, detail?): return "\(phrase) · \(detail)"
        case let (phrase?, nil): return phrase
        case let (nil, detail?): return detail
        case (nil, nil): return nil
        }
    }
}
