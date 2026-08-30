import SwiftUI

// MARK: - Import tile button

struct ImportTileButton: View {
    let icon: String
    let label: String
    var isBusy: Bool = false
    var isActive: Bool = false
    let action: () -> Void
    @State private var isHovered = false

    var body: some View {
        Button(action: action) {
            VStack(spacing: CicadaTheme.spacingSM) {
                Image(systemName: icon)
                    .font(.system(size: 18, weight: .medium))
                    .foregroundStyle(isActive ? CicadaTheme.accent : CicadaTheme.textSecondary)
                Text(label)
                    .font(.system(size: 12, weight: .medium))
                    .foregroundStyle(isActive ? CicadaTheme.textPrimary : CicadaTheme.textSecondary)
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, CicadaTheme.spacingLG)
            .background(
                RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall)
                    .fill(isActive ? CicadaTheme.accent.opacity(0.12) : (isHovered ? CicadaTheme.surfaceHover : CicadaTheme.surfaceElevated))
            )
            .overlay(
                RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall)
                    .stroke(isActive ? CicadaTheme.accent.opacity(0.5) : CicadaTheme.border, lineWidth: 1)
            )
        }
        .buttonStyle(.plain)
        .disabled(isBusy)
        .onHover { isHovered = $0 }
        .animation(.easeInOut(duration: 0.15), value: isHovered)
    }
}

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
                .buttonStyle(.plain)
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
                .buttonStyle(.plain)
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
