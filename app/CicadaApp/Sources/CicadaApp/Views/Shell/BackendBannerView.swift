import SwiftUI

/// Production blocker (2026-11-06) — the one place the shell says the backend is not answering, and the one thing that
/// helps. A full-width strip over the page, laid out as a safe-area inset so it never covers a row; it draws nothing
/// while the backend answers and clears by itself when it does.
///
/// Applies DR-5 (no accent: the button is neutral), DR-7 (the one semantic colour is the glyph, no fill), DR-37 (a
/// strip, not a card), DR-38 (the page says "couldn't read" once, here says why), DR-40 (a neutral button), DR-41,
/// DR-59 (one plain line), DR-60/DR-61 (it appears in one frame; no duration here).
struct BackendBannerView: View {
    @Environment(BackendWatch.self) private var watch
    @State private var working = false

    var body: some View {
        if let banner = watch.banner {
            HStack(spacing: CicadaTheme.spacingMD) {
                Image(systemName: "exclamationmark.circle")
                    .font(CicadaTheme.icon(.inline))
                    .foregroundStyle(CicadaTheme.warning)
                    .accessibilityHidden(true)
                Text(banner.line)
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .fixedSize(horizontal: false, vertical: true)
                Spacer(minLength: CicadaTheme.spacingMD)
                if let action = banner.action {
                    NeutralButton(title: action, size: .compact, isDisabled: working) {
                        guard !working else { return }
                        working = true
                        Task {
                            await watch.fix()
                            working = false
                        }
                    }
                }
            }
            .padding(.horizontal, CicadaTheme.spacingLG)
            .padding(.vertical, CicadaTheme.spacingSM)
            .frame(maxWidth: .infinity)
            .background(CicadaTheme.bgFocus)
            .accessibilityElement(children: .contain)
            .accessibilityLabel(banner.line)
        }
    }
}
