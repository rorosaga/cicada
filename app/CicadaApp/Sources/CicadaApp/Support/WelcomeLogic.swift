import Foundation

/// Design §4.1.5 — the name is required (G117 R1: it is the observer), prefilled
/// from what the person already told Cicada, else the Mac account (no Contacts prompt).
enum WelcomeName {
    static func initial(saved: String?, fullUserName: String) -> String {
        let saved = (saved ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        return saved.isEmpty ? fullUserName.trimmingCharacters(in: .whitespacesAndNewlines) : saved
    }

    static func firstWord(_ name: String) -> String {
        name.trimmingCharacters(in: .whitespacesAndNewlines).split(separator: " ").first.map(String.init) ?? ""
    }
}

/// Design §4.1.4 / W4 / W5 — the ticks are the consent. Untouched rows follow
/// `FoundPolicy.defaultOn`; a row the person touched keeps their answer through
/// every re-probe; a permission granted from the row's own Allow… ticks it.
/// A row with nothing to run (already on) or nothing that can run (failed,
/// checking, still blocked) is never ticked.
enum WelcomeTicks {
    static func canTick(_ item: FoundItem) -> Bool { item.isPresent && item.readiness == .ready }

    static func reconcile(items: [FoundItem], current: Set<FoundItemID>, touched: Set<FoundItemID>,
                          allowRequested: Set<FoundItemID>) -> Set<FoundItemID> {
        var out = Set<FoundItemID>()
        for item in items where canTick(item) {
            if allowRequested.contains(item.id) { out.insert(item.id); continue }
            if touched.contains(item.id) {
                if current.contains(item.id) { out.insert(item.id) }
            } else if FoundPolicy.defaultOn(item) {
                out.insert(item.id)
            }
        }
        return out
    }
}

/// R-IB11 — the Welcome's geometry: the hero band (≈ 36 % of the window, never
/// under 240 scaled points unless that would pass 45 %), the card rising 96
/// scaled points into the meadow, and a footer pinned OUTSIDE the card's scroll
/// view (the G130 lesson `FirstRunSheet` learned: the one way forward must never
/// be the first thing to clip at 1.4×).
enum WelcomeLayout {
    static let bandFraction: CGFloat = 0.36
    static let maxBandFraction: CGFloat = 0.45
    static let minBand: CGFloat = 240
    static let overlap: CGFloat = 96
    static let cardMaxWidth: CGFloat = 680
    static let footerHeight: CGFloat = 128
    static let gutter: CGFloat = 16

    static func bandHeight(windowHeight h: CGFloat, scale: CGFloat) -> CGFloat {
        min(max(h * bandFraction, minBand * scale), h * maxBandFraction)
    }

    static func cardTop(windowHeight h: CGFloat, scale: CGFloat) -> CGFloat {
        bandHeight(windowHeight: h, scale: scale) - overlap * scale
    }

    static func cardViewport(windowHeight h: CGFloat, scale: CGFloat) -> CGFloat {
        h - cardTop(windowHeight: h, scale: scale) - footerHeight * scale
    }

    static func cardWidth(windowWidth w: CGFloat, scale: CGFloat) -> CGFloat {
        min(cardMaxWidth * scale, w - 2 * gutter * scale)
    }
}

/// R-IB13 — the one line under the engine cards. The server's preview cannot
/// know a local pick, so a pick says only that Start will save it; an untouched
/// chooser with nothing that can run says so; otherwise ScheduleHonesty speaks.
enum EngineChoiceLine {
    static func text(pickLabel: String?, readiness: EngineReadiness, inputs: HonestyInputs) -> String {
        if let pickLabel { return Copy.welcomePickSaved(pickLabel) }
        if readiness == .needsChoice { return Copy.welcomeNotChosen }
        return ScheduleHonesty.engineLine(inputs)
    }
}
