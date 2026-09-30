import SwiftUI

/// G162 (§9 2026-09-30) — the Videos tab's strip: one plain 44 pt row on `bgBase`, no card and no glyph (DR-37),
/// "Saved videos · 8 not read yet · 4 queued · 1 picked up by an agent · 1 couldn't be done" and *Choose videos…*
/// trailing. It stands where the Connected strip stands on every other tab and scrolls with the list.
struct VideosStrip: View {
    let summary: VideoSummary?
    let choose: () -> Void

    static let height: CGFloat = 44

    var body: some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            Text(Copy.Videos.savedVideos)
                .font(CicadaTheme.font(size: 13, weight: .medium))
                .foregroundStyle(CicadaTheme.textPrimary)
            if let line = VideosStripText.line(summary) {
                Text(line)
                    .font(CicadaTheme.metaFont)
                    .monospacedDigit()
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .lineLimit(1)
            }
            Spacer(minLength: CicadaTheme.spacingSM)
            NeutralButton(title: Copy.Videos.chooseVideos, size: .compact, help: Copy.Videos.chooseVideosHelp,
                          action: choose)
        }
        .frame(height: CicadaTheme.scaled(Self.height))
        .padding(.horizontal, CicadaTheme.scaled(10))
    }
}

enum VideosStripText {
    /// "8 not read yet · 4 queued · 1 picked up by an agent · 1 couldn't be done" — the unread count, then the one
    /// queue wording; nil before anything was read.
    static func line(_ summary: VideoSummary?) -> String? {
        guard let summary else { return nil }
        let unread = summary.unread > 0 ? Copy.Videos.unreadCount(summary.unread) : Copy.Videos.noneUnread
        return [unread, VideoQueueLine.text(summary)].compactMap { $0 }.joined(separator: " · ")
    }
}

/// G162 (§5.5 density, §9 2026-09-30) — one video in the picker: 64 pt, the neutral check, an 88 × 50 frame, the
/// title, "channel · length" with the provider's mark, and what Cicada holds ("Metadata only · saved Sep 29").
struct VideoPickRow: View {
    let row: VideoRow
    let isSelected: Bool
    let toggle: () -> Void

    static let height: CGFloat = RowMetrics.videoPick

    private var title: String { row.item.title.isEmpty ? row.item.url : row.item.title }

    var body: some View {
        HStack(spacing: CicadaTheme.scaled(10)) {
            Toggle(isOn: Binding(get: { isSelected }, set: { _ in toggle() })) {
                EmptyView()
            }
            .toggleStyle(NeutralCheckToggleStyle())
            .accessibilityLabel(Copy.Videos.selectVideo + ": " + title)
            .help(Copy.Videos.selectVideo)
            Button(action: toggle) {
                HStack(spacing: CicadaTheme.scaled(10)) {
                    VideoThumb(thumbnail: row.item.thumbnail, durationS: row.item.durationS, width: 88, height: 50)
                    VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                        Text(title)
                            .font(CicadaTheme.font(size: 13))
                            .foregroundStyle(CicadaTheme.textPrimary)
                            .lineLimit(1)
                        VideoChannelLine(item: row.item)
                        Text(VideoWords.pickerStateLine(row.item, state: row.state))
                            .font(CicadaTheme.metaFont)
                            .foregroundStyle(CicadaTheme.textTertiary)
                            .lineLimit(1)
                    }
                    Spacer(minLength: 0)
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(.cicadaPlain)
            .accessibilityHidden(true)
        }
        .listRowSurface(height: Self.height, selected: isSelected)
    }
}

/// One member of a hand-off in the run's list column: no check, the batch's live word on the third line.
struct VideoRunListRow: View {
    let member: VideoRunMember

    private var title: String { member.row.item.title.isEmpty ? member.row.item.url : member.row.item.title }

    var body: some View {
        HStack(spacing: CicadaTheme.scaled(10)) {
            VideoThumb(thumbnail: member.row.item.thumbnail, durationS: member.row.item.durationS, width: 88, height: 50)
            VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                Text(title)
                    .font(CicadaTheme.font(size: 13))
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .lineLimit(1)
                VideoChannelLine(item: member.row.item)
                Text(VideoRunProgress.listWord(member))
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .lineLimit(1)
            }
            Spacer(minLength: 0)
        }
        .listRowSurface(height: RowMetrics.videoPick, selected: false)
    }
}
