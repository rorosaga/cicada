import SwiftUI

/// One frame for every sheet the Settings panel raises (R-HS16): a title, a close × on
/// `.cancelAction` (Esc, in the sheet's own window — the panel's × is in the main window and never
/// sees it), the body, 440 pt wide. A sheet, never a popover: the panel is modal and inset 40 pt, so
/// a popover anchored at its edge could open past the screen (the owner's report); AppKit centres a
/// sheet on its window. `SettingsSheetLintTests` holds `Views/Settings/` to that.
struct SettingsSheet<Content: View>: View {
    static var width: CGFloat { 440 }

    let title: String
    let onClose: () -> Void
    @ViewBuilder let content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.spacingSM) {
                Text(title)
                    .font(CicadaTheme.headingFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .lineLimit(1)
                    .accessibilityAddTraits(.isHeader)
                Spacer(minLength: CicadaTheme.spacingSM)
                IconButton(systemName: "xmark", help: Copy.sheetClose, accessibilityLabel: Copy.sheetClose,
                           shortcut: .cancelAction, action: onClose)
            }
            content
        }
        .padding(CicadaTheme.spacingXL)
        .frame(width: CicadaTheme.scaled(Self.width), alignment: .leading)
        .background(CicadaTheme.bgBase)
    }
}
