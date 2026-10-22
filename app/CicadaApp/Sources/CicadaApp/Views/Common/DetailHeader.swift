import SwiftUI

/// §5.3 / DR-16 — a detail column's head: the thing's real mark (20 pt, DR-52), its title as the detail heading
/// (`displayFont(size: 22)`, DR-16's H1 role), one line saying what it is, and Close × — with "‹ N" first when DR-27 hid
/// the list. Sources' source and contributor columns share it, and so do the Backlog item, Settings' detail panes and —
/// since the consistency pass (2026-10-20) — Skills' and Looks' side columns, which had set their titles in the 17 pt
/// heading face beside a hand-placed ×. A thing with no mark of its own passes none (`DetailHeader(title:…)`).
struct DetailHeader<Mark: View>: View {
    let title: String
    var blurb: String? = nil
    var backLabel: String? = nil
    var onShowList: () -> Void = {}
    let closeHelp: String
    var closeShortcut: KeyboardShortcut? = nil
    let onClose: () -> Void
    @ViewBuilder var mark: () -> Mark

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            if let backLabel {
                TextButton(title: backLabel, help: Copy.Lists.showList, action: onShowList)
                    .padding(.leading, -CicadaTheme.scaled(10))
            }
            HStack(alignment: .top, spacing: CicadaTheme.spacingMD) {
                if Mark.self != EmptyView.self { mark().padding(.top, CicadaTheme.scaled(4)) }
                VStack(alignment: .leading, spacing: CicadaTheme.scaled(3)) {
                    Text(title)
                        .font(CicadaTheme.displayFont(size: 22))
                        .tracking(CicadaTheme.displayTracking(size: 22))
                        .foregroundStyle(CicadaTheme.textPrimary)
                        .lineLimit(2)
                        .accessibilityAddTraits(.isHeader)
                    if let blurb {
                        Text(blurb)
                            .font(CicadaTheme.bodyFont)
                            .foregroundStyle(CicadaTheme.textSecondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
                Spacer(minLength: CicadaTheme.spacingSM)
                IconButton(systemName: "xmark", help: closeHelp, shortcut: closeShortcut, action: onClose)
            }
        }
        .padding(.vertical, CicadaTheme.spacingMD)
    }
}

extension DetailHeader where Mark == EmptyView {
    init(title: String, blurb: String? = nil, backLabel: String? = nil, onShowList: @escaping () -> Void = {},
         closeHelp: String, closeShortcut: KeyboardShortcut? = nil, onClose: @escaping () -> Void) {
        self.init(title: title, blurb: blurb, backLabel: backLabel, onShowList: onShowList, closeHelp: closeHelp,
                  closeShortcut: closeShortcut, onClose: onClose, mark: { EmptyView() })
    }
}
