import SwiftUI

// MARK: - Feed subscription row

struct FeedSubscriptionRow: View {
    let feed: FeedSubscription
    var isRemoving: Bool = false
    let onRemove: () -> Void

    var body: some View {
        HStack(spacing: CicadaTheme.spacingMD) {
            Image(systemName: "dot.radiowaves.up.forward")
                .font(.system(size: 12))
                .foregroundStyle(CicadaTheme.textTertiary)

            VStack(alignment: .leading, spacing: 2) {
                Text(feed.url)
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .lineLimit(1)
                    .truncationMode(.middle)
                Text(subtitle)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            }

            Spacer()

            if isRemoving {
                ProgressView().controlSize(.small)
            } else {
                Button(action: onRemove) {
                    Image(systemName: "trash")
                        .font(.system(size: 12))
                        .foregroundStyle(CicadaTheme.textTertiary)
                }
                .buttonStyle(.cicadaPlain)
                .help("Unsubscribe")
            }
        }
        .padding(.horizontal, CicadaTheme.spacingMD)
        .padding(.vertical, CicadaTheme.spacingSM)
        .background(CicadaTheme.surfaceHover.opacity(0.4))
        .clipShape(RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall))
    }

    private var subtitle: String {
        var parts = ["added \(feed.added)"]
        if let polled = feed.lastPolled, !polled.isEmpty {
            parts.append("last polled \(polled)")
        } else {
            parts.append("not polled yet")
        }
        if !feed.tags.isEmpty {
            parts.append(feed.tags.joined(separator: ", "))
        }
        return parts.joined(separator: " · ")
    }
}

// MARK: - Calendar subscription row

struct CalendarSubscriptionRow: View {
    let calendar: CalendarSubscription
    var isRemoving: Bool = false
    let onRemove: () -> Void

    var body: some View {
        HStack(spacing: CicadaTheme.spacingMD) {
            Image(systemName: "calendar")
                .font(.system(size: 12))
                .foregroundStyle(CicadaTheme.textTertiary)

            VStack(alignment: .leading, spacing: 2) {
                Text(calendar.url)
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .lineLimit(1)
                    .truncationMode(.middle)
                Text(subtitle)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            }

            Spacer()

            if isRemoving {
                ProgressView().controlSize(.small)
            } else {
                Button(action: onRemove) {
                    Image(systemName: "trash")
                        .font(.system(size: 12))
                        .foregroundStyle(CicadaTheme.textTertiary)
                }
                .buttonStyle(.cicadaPlain)
                .help("Unsubscribe")
            }
        }
        .padding(.horizontal, CicadaTheme.spacingMD)
        .padding(.vertical, CicadaTheme.spacingSM)
        .background(CicadaTheme.surfaceHover.opacity(0.4))
        .clipShape(RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall))
    }

    private var subtitle: String {
        var parts = ["added \(calendar.added)"]
        if let polled = calendar.lastPolled, !polled.isEmpty {
            parts.append("last polled \(polled)")
        } else {
            parts.append("not polled yet")
        }
        if !calendar.tags.isEmpty {
            parts.append(calendar.tags.joined(separator: ", "))
        }
        return parts.joined(separator: " · ")
    }
}
