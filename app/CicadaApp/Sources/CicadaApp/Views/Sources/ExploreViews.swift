import SwiftUI

/// G166 exploring — the run card at the top of Sources (design §1.4): one line of progress, who started it when it was
/// an agent (D5), and the person's two actions, Stop (one tap) and Copy for an agent. Direction D: a glass card like the
/// source queue strip, neutral buttons (DR-40), text before glyphs, no price or token count (DR-59, ruling 12).
struct ExploreRunCard: View {
    @Environment(ExploreCache.self) private var cache
    @State private var copied = false

    var body: some View {
        if let batch = cache.batch {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.spacingMD) {
                    Text(batch.isRunning ? Copy.Explore.cardTitle
                         : batch.stoppedAt != nil ? Copy.Explore.stopped : Copy.Explore.finished)
                        .font(CicadaTheme.headingFont)
                        .foregroundStyle(CicadaTheme.textPrimary)
                    Spacer(minLength: CicadaTheme.spacingSM)
                    if batch.isRunning {
                        NeutralButton(title: copied ? Copy.Explore.copied : Copy.Explore.copyPrompt,
                                      systemImage: "doc.on.doc", size: .compact, help: Copy.Explore.addAgentHelp) {
                            Task { copied = await cache.copyPrompt() }
                        }
                        NeutralButton(title: Copy.Explore.stop, systemImage: "stop", size: .compact,
                                      help: Copy.Explore.stopHelp) {
                            Task { await cache.stop() }
                        }
                        .disabled(cache.busy)
                        .opacity(cache.busy ? NeutralButton.disabledOpacity : 1)
                    }
                }
                Text(Copy.Explore.progress(batch))
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
                if let who = Copy.Explore.startedBy(batch.startedBy) {
                    Text(who)
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                }
                if let note = cache.note {
                    Text(note)
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.danger)
                }
            }
            .padding(CicadaTheme.spacingMD)
            .glassCard()
            .accessibilityElement(children: .combine)
        }
    }
}

/// The Explore sheet (design §1.2, D5's click): which saved sites, how many, the run's size, then Explore. After the
/// click it shows the prompt to copy for the person's agent — Cicada never opens a browser itself.
struct ExploreSheet: View {
    let done: () -> Void
    @Environment(ExploreCache.self) private var cache
    @State private var scope: ExploreScope = .neverExplored
    @State private var excludedOrigins: Set<String> = []
    @State private var copied = false

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            HStack(alignment: .firstTextBaseline) {
                Text(Copy.Explore.sheetTitle)
                    .font(CicadaTheme.headingFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .accessibilityAddTraits(.isHeader)
                Spacer()
                IconButton(systemName: "xmark", help: Copy.sheetClose, accessibilityLabel: Copy.sheetClose,
                           shortcut: .cancelAction, action: done)
            }
            if let prompt = cache.prompt {
                started(prompt)
            } else {
                choose
            }
        }
        .padding(CicadaTheme.spacingXL)
        .frame(width: CicadaTheme.scaled(460), alignment: .leading)
        .task { await cache.refreshCandidates() }
    }

    private var choose: some View {
        let c = cache.candidates
        return VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            Text(Copy.Explore.sheetIntro)
                .font(CicadaTheme.bodyFont)
                .foregroundStyle(CicadaTheme.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
            Picker("", selection: $scope) {
                Text("\(Copy.Explore.scopeNever) · \(Copy.Explore.count(c?.neverExplored ?? 0))").tag(ExploreScope.neverExplored) // count-lint:ok — Copy.Explore.count goes through UsageFormat
                Text("\(Copy.Explore.scopeAll) · \(Copy.Explore.count(c?.eligible ?? 0))").tag(ExploreScope.all) // count-lint:ok — Copy.Explore.count goes through UsageFormat
            }
            .pickerStyle(.radioGroup)
            .labelsHidden()
            if let origins = c?.origins, origins.count > 1 {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                    Text(Copy.Explore.browsersLabel)
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                    ForEach(origins) { origin in
                        Toggle("\(origin.label) · \(Copy.Explore.count(origin.count))", isOn: Binding(
                            get: { !excludedOrigins.contains(origin.origin) },
                            set: { on in if on { excludedOrigins.remove(origin.origin) } else { excludedOrigins.insert(origin.origin) } }))
                            .toggleStyle(.checkbox)
                    }
                }
            }
            if let c {
                Text(Copy.Explore.size(scope == .all ? c.estimate : c.estimateNeverExplored))
                    .font(CicadaTheme.rowFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                Text(c.exploreSignedIn ? Copy.Explore.signedInNote : Copy.Explore.privateNote)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .fixedSize(horizontal: false, vertical: true)
                if let left = Copy.Explore.leftOut(c.excluded) {
                    Text(left)
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            if let note = cache.note {
                Text(note)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.danger)
                    .fixedSize(horizontal: false, vertical: true)
            }
            HStack {
                Spacer()
                TextButton(title: Copy.Explore.notNow, action: done)
                let blocked = cache.blockedReason(scope: scope)
                PrimaryActionButton(title: Copy.Explore.start) {
                    let chosen = (c?.origins ?? []).map(\.origin).filter { !excludedOrigins.contains($0) }
                    Task { await cache.start(scope: scope, origins: excludedOrigins.isEmpty ? [] : chosen) }
                }
                .disabled(blocked != nil || cache.busy)
                .opacity(blocked == nil ? 1 : NeutralButton.disabledOpacity)
                .help(blocked ?? "")
            }
        }
    }

    private func started(_ prompt: String) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            if let batch = cache.batch {
                Text(Copy.Explore.progress(batch))
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
            }
            ScrollView {
                Text(prompt)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            .frame(maxHeight: CicadaTheme.scaled(180))
            HStack {
                Spacer()
                TextButton(title: Copy.Explore.notNow, action: done)
                PrimaryActionButton(title: copied ? Copy.Explore.copied : Copy.Explore.copyPrompt) {
                    AppPasteboard.copy(prompt)
                    copied = true
                }
            }
        }
    }
}
