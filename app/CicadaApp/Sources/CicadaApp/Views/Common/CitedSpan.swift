import SwiftUI

/// The cited span (DR-18): washed and underlined — a `wash` fill with a 4 pt radius and 1 pt
/// of padding, and a 2 pt accent underline 4 pt below the run; the other spans in the same
/// passage in `washSoft`. Defined once here; the Reader and the Inbox (DS-2) adopt it.
///
/// Two renderers, one rule (R-DS12). On macOS 15+, a `TextRenderer` draws the exact shape
/// behind each tagged run. The package floor is 14, where `AttributedString` can carry a fill
/// and an underline colour but neither an offset nor a radius, so `fallback(_:)` is the honest
/// approximation there. The owner runs 26.
///
/// `.mention` — a match found by name (G118 §4.9, DR-57): semibold, never washed; the wash and the
/// underline are for words someone quoted (R-DI11). `reveal` (0…1) scales the wash and the
/// underline so `spanReveal` fades them in (DR-61) instead of popping them; every existing call
/// site passes nothing and gets 1.
enum CitedSpan {
    enum Mark: Equatable { case plain, current, other, mention }
    struct Segment: Equatable {
        let text: String
        let mark: Mark
    }

    static let padding: CGFloat = 1
    static let cornerRadius: CGFloat = CicadaTheme.radiusXS
    static let underlineThickness: CGFloat = 2
    static let underlineOffset: CGFloat = 4

    static func washRect(for run: CGRect) -> CGRect { run.insetBy(dx: -padding, dy: -padding) }
    static func underlineRect(for run: CGRect) -> CGRect {
        CGRect(x: run.minX - padding, y: run.maxY + underlineOffset - underlineThickness / 2,
               width: run.width + 2 * padding, height: underlineThickness)
    }

    /// macOS 14 — the fill and the underline colour; no offset, no radius. Written through the
    /// SwiftUI scope explicitly: AppKit's scope has its own `backgroundColor` (an `NSColor`) and
    /// `underlineStyle`, and the bare names are ambiguous on macOS.
    static func fallback(_ segments: [Segment], reveal: Double = 1) -> AttributedString {
        segments.reduce(into: AttributedString()) { out, segment in
            var piece = AttributedString(segment.text)
            var marks = AttributeContainer()
            switch segment.mark {
            case .plain: break
            case .current:
                marks.swiftUI.backgroundColor = CicadaTheme.wash.opacity(reveal)
                marks.swiftUI.underlineStyle = Text.LineStyle(pattern: .solid, color: CicadaTheme.accent.opacity(reveal))
            case .other:
                marks.swiftUI.backgroundColor = CicadaTheme.washSoft.opacity(reveal)
            case .mention:
                // Found, not quoted: emphasis only, no fill (R-DI11).
                marks.inlinePresentationIntent = .stronglyEmphasized
            }
            piece.mergeAttributes(marks)
            out.append(piece)
        }
    }

    /// The passage as one `Text`: tagged runs on 15+ (draw them with `.citedSpans()`), the
    /// fallback string on 14.
    static func text(_ segments: [Segment]) -> Text {
        if #available(macOS 15, *) {
            return segments.reduce(Text("")) { text, segment in
                switch segment.mark {
                case .plain: text + Text(segment.text)
                case .current: text + Text(segment.text).customAttribute(CitedSpanTag(current: true))
                case .other: text + Text(segment.text).customAttribute(CitedSpanTag(current: false))
                case .mention: text + Text(segment.text).fontWeight(.semibold)
                }
            }
        }
        return Text(fallback(segments))
    }
}

@available(macOS 15, *)
struct CitedSpanTag: TextAttribute {
    let current: Bool
}

@available(macOS 15, *)
struct CitedSpanRenderer: TextRenderer {
    let wash: Color
    let washSoft: Color
    let underline: Color
    /// DR-61 — 0 → 1 over `spanReveal`; animatable so the wash fades rather than pops.
    var reveal: Double = 1

    var animatableData: Double {
        get { reveal }
        set { reveal = newValue }
    }

    /// The underline sits below the last line's box; ask for the room so it is never clipped.
    var displayPadding: EdgeInsets {
        EdgeInsets(top: 0, leading: CitedSpan.padding, bottom: CitedSpan.underlineOffset + CitedSpan.underlineThickness,
                   trailing: CitedSpan.padding)
    }

    func draw(layout: Text.Layout, in ctx: inout GraphicsContext) {
        for line in layout {
            for run in line {
                if let tag = run[CitedSpanTag.self] {
                    let bounds = run.typographicBounds.rect
                    ctx.fill(Path(roundedRect: CitedSpan.washRect(for: bounds), cornerRadius: CitedSpan.cornerRadius,
                                  style: .continuous),
                             with: .color((tag.current ? wash : washSoft).opacity(reveal)))
                    if tag.current {
                        ctx.fill(Path(CitedSpan.underlineRect(for: bounds)), with: .color(underline.opacity(reveal)))
                    }
                }
                ctx.draw(run)
            }
        }
    }
}

extension View {
    /// Draws `CitedSpan.text(_:)`'s tagged runs (macOS 15+); a no-op on 14, where the fallback
    /// string already carries its marks.
    @ViewBuilder
    func citedSpans(reveal: Double = 1) -> some View {
        if #available(macOS 15, *) {
            textRenderer(CitedSpanRenderer(wash: CicadaTheme.wash, washSoft: CicadaTheme.washSoft,
                                           underline: CicadaTheme.accent, reveal: reveal))
        } else {
            self
        }
    }

    /// DR-18 — a quote block: indented 16 pt behind a 2 pt rule (white 16 % / black 14 %).
    func quoteBlock() -> some View {
        padding(.leading, CicadaTheme.scaled(16))
            .overlay(alignment: .leading) { Rectangle().fill(CicadaTheme.quoteRule).frame(width: 2) }
    }
}
