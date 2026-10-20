import SwiftUI

/// DR-76 (consistency pass, round 2, 2026-10-20) — the app's one text field on a page, in a column or in a page's own
/// sheet: a plain field in `detailBodyFont`, 32 pt (a multi-line field grows from 32), a `bgBase` fill and the input
/// ring (DR-9 allows a real border on an input), the ring turning the accent at 70 % while the field has focus (DR-5,
/// use 1: the focus ring). The Inbox's answer field and the entity card's source field drew it; Projects' milestone
/// and backlog fields, the Backlog item, bookmark reasons and the Looks composer used the native rounded field, which
/// sits on a different fill, ring and height. Native fields stay in Settings' forms and the setup sheets (as DR-40's
/// native buttons do), and Skills' header field is the owner's own design.
///
/// **Focus.** The field owns its focus ring, so no caller can forget it: with no argument the modifier tracks focus
/// itself (its own `@FocusState`, bound on the field). A caller that already drives focus — it applies
/// `.focused(_:)` to move the cursor in (⌘N, "Add a milestone") — passes `isFocused:` from that same `@FocusState`
/// instead, so one field never carries two focus bindings (`DesignConsistencyLintTests` holds both halves).
///
/// **Placeholder.** The field draws its own prompt in `textTertiary` while it is empty, and the field's own title is
/// empty (`TextField("", …)`): a plain field's system placeholder renders at #3E3E3E in light — the secondary ink's
/// weight, measured offscreen — and neither `prompt:` styling nor a foreground style reaches it. The words typed take
/// the system's text ink under the app's colour scheme. The prompt is the field's accessibility label too.
struct CicadaField: ViewModifier {
    /// The caller's focus, when it owns one; nil lets the field track its own.
    var isFocused: Bool? = nil
    /// The words shown while the field is empty, drawn here in `textTertiary`.
    var prompt: String
    var isEmpty: Bool
    @FocusState private var ownFocus: Bool

    static let height: CGFloat = 32

    func body(content: Content) -> some View {
        Group {
            if isFocused == nil {
                surface(content.focused($ownFocus), focused: ownFocus)
            } else {
                surface(content, focused: isFocused ?? false)
            }
        }
    }

    private func surface<V: View>(_ field: V, focused: Bool) -> some View {
        field
            .textFieldStyle(.plain)
            .font(CicadaTheme.detailBodyFont)
            .accessibilityLabel(prompt)
            .background(alignment: .topLeading) {
                if isEmpty {
                    Text(prompt)
                        .font(CicadaTheme.detailBodyFont)
                        .foregroundStyle(Self.promptInk)
                        .lineLimit(1)
                        .allowsHitTesting(false)
                        .accessibilityHidden(true)
                }
            }
            .padding(.horizontal, CicadaTheme.scaled(10))
            .padding(.vertical, CicadaTheme.scaled(7))
            .frame(minHeight: CicadaTheme.scaled(Self.height))
            .background(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall).fill(CicadaTheme.bgBase))
            .overlay(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall)
                .strokeBorder(Self.ring(focused: focused), lineWidth: 1))
    }

    /// The prompt's ink: the tertiary step (DR-2), never the words' own.
    static var promptInk: Color { CicadaTheme.textTertiary }

    /// The ring: the accent at 70 % while focused (DR-5's focus ring), else the resting input ring.
    static func ring(focused: Bool) -> Color {
        focused ? CicadaTheme.accent.opacity(0.7) : CicadaTheme.ring(.input)
    }
}

extension View {
    /// DR-76 — the app's own field (see `CicadaField`). Pass `isFocused:` only when this field already has a
    /// `.focused(_:)` binding of the caller's.
    func cicadaField(isFocused: Bool? = nil, prompt: String, isEmpty: Bool) -> some View {
        modifier(CicadaField(isFocused: isFocused, prompt: prompt, isEmpty: isEmpty))
    }
}
