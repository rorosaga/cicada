import AppKit
import SwiftUI

/// G182 phase 3 — the larger search model's one-time install. The model is published under a license
/// the person accepts on Hugging Face with their own account, so the download needs their own
/// read-access token. The sheet says that in plain words, links to the two pages they act on
/// (DR-5 use 5, `InlineLink`), takes the token in a `SecureField` and sends it in one request body
/// (`APIClient.installLargerEmbeddingModel`). The token is cleared from this view's state the moment
/// Install is pressed — before the request even leaves — and is never written anywhere (no
/// UserDefaults, no Keychain). Raised inside `SettingsSheet` (R-HS16): its × is Esc.
///
/// DR-40 — Install is the sheet's one `PrimaryActionButton`, Cancel a `TextButton`; nothing hand-rolled.
/// DR-41 — Install is disabled (45 %) until the field holds something shaped like a token, and its
/// `.help` says what it waits for. DR-19 — no monospace: a token is pasted, never shown or copied.
struct LargerSearchModelSheet: View {
    /// The catalog's downloadable model; its id builds the model page's address.
    let modelID: String
    /// The 202's status — the row takes it and shows the install's progress.
    let onStarted: (EmbeddingsStatus) -> Void
    let onCancel: () -> Void

    @State private var token = ""
    @State private var failure: String?
    @State private var sending = false

    private var ready: Bool { SearchModelLogic.tokenLooksValid(token) && !sending }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            ForEach([Copy.SearchModel.sheetWhy, Copy.SearchModel.sheetTokenUse], id: \.self) { paragraph in
                Text(paragraph)
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            step(Copy.SearchModel.stepLicense) {
                InlineLink(title: Copy.SearchModel.openModelPage) { open(SearchModelLogic.modelPage(modelID)) }
            }
            step(Copy.SearchModel.stepToken) {
                InlineLink(title: Copy.SearchModel.createToken) { open(SearchModelLogic.tokensPage) }
            }
            VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                Text(Copy.SearchModel.stepPaste)
                    .font(CicadaTheme.font(size: 13, weight: .medium))
                    .foregroundStyle(CicadaTheme.textPrimary)
                SecureField(Copy.SearchModel.tokenPlaceholder, text: $token)
                    .textFieldStyle(.roundedBorder)
                    .font(CicadaTheme.captionFont)
                    .accessibilityLabel(Copy.SearchModel.tokenLabel)
                    .privacySensitive()
                    .onSubmit { if ready { send() } }
            }
            if let failure {
                Text(failure)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.danger)
                    .fixedSize(horizontal: false, vertical: true)
            }
            HStack(spacing: CicadaTheme.spacingSM) {
                if sending { ProgressView().controlSize(.small) }
                Spacer()
                TextButton(title: Copy.SearchModel.cancel) { token = ""; onCancel() }
                PrimaryActionButton(title: Copy.SearchModel.install) { send() }
                    .disabled(!ready)
                    .opacity(ready ? 1 : NeutralButton.disabledOpacity)
                    .help(ready ? Copy.SearchModel.installHelp : Copy.SearchModel.installDisabledHelp)
            }
        }
        .onDisappear { token = "" }
    }

    private func step(_ text: String, @ViewBuilder link: () -> some View) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            Text(text)
                .font(CicadaTheme.font(size: 13, weight: .medium))
                .foregroundStyle(CicadaTheme.textPrimary)
                .fixedSize(horizontal: false, vertical: true)
            link()
        }
    }

    private func open(_ url: URL?) {
        if let url { NSWorkspace.shared.open(url) }
    }

    /// The token leaves this view's state before the request does; a failure asks for it again.
    private func send() {
        guard ready else { return }
        let secret = token.trimmingCharacters(in: .whitespacesAndNewlines)
        token = ""
        failure = nil
        sending = true
        Task { @MainActor in
            defer { sending = false }
            do {
                let status = try await APIClient.shared.installLargerEmbeddingModel(token: secret)
                onStarted(status)
            } catch {
                // The backend's own sentence (`detail`): a token not shaped like one (400), an install
                // already running (409). Neither echoes the token.
                failure = AddSourceSheet.friendlyError(error)
            }
        }
    }
}
