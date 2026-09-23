import SwiftUI

/// One Claude-style setting (design §1.3): title and an optional one-line
/// detail on the left, the control right-aligned, optional content below
/// (a command box, a list). Every row is a landing anchor by construction.
struct SettingsRow<Control: View, Below: View>: View {
    let id: SettingsRowID
    let title: String
    var detail: String?
    @ViewBuilder var control: () -> Control
    @ViewBuilder var below: () -> Below

    init(_ id: SettingsRowID, title: String, detail: String? = nil,
         @ViewBuilder control: @escaping () -> Control,
         @ViewBuilder below: @escaping () -> Below) {
        self.id = id
        self.title = title
        self.detail = detail
        self.control = control
        self.below = below
    }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            HStack(alignment: .center, spacing: CicadaTheme.spacingMD) {
                VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                    Text(title)
                        .font(CicadaTheme.font(size: 13, weight: .medium))
                        .foregroundStyle(CicadaTheme.textPrimary)
                    if let detail, !detail.isEmpty {
                        Text(detail)
                            .font(CicadaTheme.captionFont)
                            .foregroundStyle(CicadaTheme.textSecondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
                Spacer(minLength: CicadaTheme.scaled(16))
                control()
            }
            below()
        }
        .padding(.vertical, CicadaTheme.spacingSM + CicadaTheme.scaled(2))
        .padding(.horizontal, CicadaTheme.spacingMD)
        .frame(maxWidth: .infinity, alignment: .leading)
        .settingsRow(id)
    }
}

extension SettingsRow where Below == EmptyView {
    init(_ id: SettingsRowID, title: String, detail: String? = nil,
         @ViewBuilder control: @escaping () -> Control) {
        self.init(id, title: title, detail: detail, control: control, below: { EmptyView() })
    }
}

extension SettingsRow where Control == EmptyView, Below == EmptyView {
    /// A fact row: a title and a sentence, nothing to change.
    init(_ id: SettingsRowID, title: String, detail: String?) {
        self.init(id, title: title, detail: detail, control: { EmptyView() }, below: { EmptyView() })
    }
}

/// A group of rows on one surface (design §1.3): content layer, so a plain
/// surface with a hairline — never glass, never a shadow.
struct SettingsGroupCard<Content: View>: View {
    var header: String? = nil
    var trailingHeader: String? = nil
    @ViewBuilder var content: () -> Content

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            if header != nil || trailingHeader != nil {
                HStack(alignment: .firstTextBaseline) {
                    if let header { SettingsGroupHeader(header) }
                    Spacer(minLength: CicadaTheme.spacingSM)
                    if let trailingHeader {
                        Text(trailingHeader)
                            .font(CicadaTheme.captionFont)
                            .foregroundStyle(CicadaTheme.textTertiary)
                    }
                }
                .padding(.horizontal, CicadaTheme.spacingXS)
            }
            VStack(alignment: .leading, spacing: 0) { content() }
                .settingsCardSurface()
        }
    }
}

struct SettingsGroupHeader: View {
    let text: String
    init(_ text: String) { self.text = text }

    var body: some View {
        SectionLabel(text)
    }
}

/// A hairline between rows, inset like the rows' text.
struct SettingsDivider: View {
    var body: some View {
        Rectangle()
            .fill(CicadaTheme.border)
            .frame(height: 1)
            .padding(.leading, CicadaTheme.spacingMD)
    }
}

extension View {
    /// The Settings card surface: one group of rows on the focus surface with a
    /// resting ring (DR-9, DR-37) — also used by a card that is not a group of
    /// rows (a Plans & keys connection, a recommended skill).
    func settingsCardSurface() -> some View {
        background(CicadaTheme.shape(CicadaTheme.cornerRadius).fill(CicadaTheme.bgFocus))
            .ringed(.resting, in: CicadaTheme.shape(CicadaTheme.cornerRadius))
    }
}
