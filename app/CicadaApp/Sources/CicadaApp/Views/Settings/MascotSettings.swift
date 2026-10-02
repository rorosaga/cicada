import SwiftUI

/// Settings → Sleep, beside the scenery. Identity is per viewer and changes no state or capability.
struct MascotSettings: View {
    @AppStorage(MascotPreference.defaultsKey) private var mascotRaw = MascotRegistry.bookworm.id

    var body: some View {
        let selected = MascotRegistry.resolve(mascotRaw)
        SettingsGroupCard {
            SettingsRow(.mascot, title: Copy.Mascot.title, control: { EmptyView() }) {
                LazyVGrid(columns: [.init(.adaptive(minimum: CicadaTheme.scaled(144)),
                                          spacing: CicadaTheme.spacingSM)],
                          alignment: .leading, spacing: CicadaTheme.spacingSM) {
                    ForEach(MascotRegistry.all) { mascot in
                        MascotTile(mascot: mascot, selected: mascot == selected) {
                            mascotRaw = mascot.id
                        }
                    }
                }
            }
        }
    }
}

struct MascotTile: View {
    let mascot: Mascot
    let selected: Bool
    let action: () -> Void
    @State private var hovering = false

    var body: some View {
        Button {
            var transaction = Transaction(animation: nil)
            transaction.disablesAnimations = true
            withTransaction(transaction, action)
        } label: {
            VStack(spacing: CicadaTheme.spacingSM) {
                HStack(alignment: .bottom, spacing: CicadaTheme.spacingSM) {
                    MascotKeyFrame(sheetName: mascot.roomSheet(.awake), tag: "idle", size: BookwormArt.roomFrame)
                    MascotKeyFrame(sheetName: mascot.menuBarSheet, tag: "awake",
                                   size: CGSize(width: 36, height: 36))
                }
                HStack(spacing: CicadaTheme.spacingXS) {
                    Text(mascot.displayName).font(CicadaTheme.captionFont)
                    if selected { Image(systemName: "checkmark").font(CicadaTheme.captionFont) }
                }
                .foregroundStyle(CicadaTheme.textPrimary)
            }
            .padding(CicadaTheme.spacingSM)
            .frame(maxWidth: .infinity)
            .background(selected ? CicadaTheme.bgSelected : (hovering ? CicadaTheme.bgHover : CicadaTheme.bgFocus),
                        in: RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall))
            .overlay {
                RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall)
                    .strokeBorder(selected ? CicadaTheme.textPrimary : CicadaTheme.border, lineWidth: 1)
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .focusable()
        .onHover { hovering = $0 }
        .help(mascot.selectionLabel(selected: selected))
        .accessibilityLabel(mascot.selectionLabel(selected: selected))
        .accessibilityAddTraits(selected ? .isSelected : [])
    }
}

/// Both tile images come from that entry, never from the currently selected skin. No timers or native probes.
private struct MascotKeyFrame: View {
    let sheetName, tag: String
    let size: CGSize

    var body: some View {
        Group {
            if let sheet = SpriteSheets.sheet(named: sheetName), let clip = sheet.clip(tag),
               let index = clip.order.first, let image = sheet.frameImage(index) {
                Image(decorative: image, scale: 1).resizable().interpolation(.none)
            } else { Color.clear }
        }
        .frame(width: size.width, height: size.height)
        .accessibilityHidden(true)
    }
}
