import SwiftUI

/// DR-76 (consistency pass, round 2, 2026-10-20) — the app's one text field on a page, in a column or in a page's own
/// sheet: a plain field in `detailBodyFont`, 32 pt (a multi-line field grows from 32), a `bgBase` fill and the input
/// ring (DR-9 allows a real border on an input), the ring turning the accent at 70 % while the field has focus (DR-5,
/// use 1: the focus ring). The Inbox's answer field and the entity card's source field drew it; Projects' milestone
/// and backlog fields, the Backlog item, bookmark reasons and the Looks composer used the native rounded field, which
/// sits on a different fill, ring and height. Native fields stay in Settings' forms and the setup sheets (as DR-40's
/// native buttons do), and Skills' header field is the owner's own design.
///
/// The caller owns focus: it applies `.focused(_:)` and passes `isFocused` from the same `@FocusState`, so one field
/// never carries two focus bindings. A field with no focus state passes nothing and keeps the resting ring.
struct CicadaField: ViewModifier {
    var isFocused = false

    static let height: CGFloat = 32

    func body(content: Content) -> some View {
        content
            .textFieldStyle(.plain)
            .font(CicadaTheme.detailBodyFont)
            .foregroundStyle(CicadaTheme.textPrimary)
            .padding(.horizontal, CicadaTheme.scaled(10))
            .padding(.vertical, CicadaTheme.scaled(7))
            .frame(minHeight: CicadaTheme.scaled(Self.height))
            .background(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall).fill(CicadaTheme.bgBase))
            .overlay(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall)
                .strokeBorder(isFocused ? CicadaTheme.accent.opacity(0.7) : CicadaTheme.ring(.input), lineWidth: 1))
    }
}

extension View {
    /// DR-76 — the app's own field (see `CicadaField`).
    func cicadaField(isFocused: Bool = false) -> some View {
        modifier(CicadaField(isFocused: isFocused))
    }
}
