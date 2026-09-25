import SwiftUI

/// One belief as a row (§10 Entity card, R-DG22): the sentence in 14, then at most two chips — the evidence chip
/// run (who spoke; a click opens the Reader, DR-57) and the age `Tag` — and a clock for its timeline. Everything
/// the retired `ClaimChip` footer printed as six pills (observer, context, trust, confidence, author) is in
/// `.help`. Hover is a fill, never a lift (DR-48). `ClaimChip` stays for transclusions and timeline rows.
struct BeliefRow: View {
    let claim: Claim
    var onOpenTimeline: (() -> Void)? = nil
    /// F-12 (R-PE17) — on the person card a belief is signed: the signed line takes the age `Tag`'s place, since it
    /// carries the day (DR-38).
    var signed = false
    @State private var showAllEvidence = false
    @State private var hovering = false

    var body: some View {
        HStack(alignment: .top, spacing: CicadaTheme.spacingSM) {
            VStack(alignment: .leading, spacing: CicadaTheme.scaled(6)) {
                Text(renderWikilinks(claim.text))
                    .font(CicadaTheme.detailBodyFont)
                    .strikethrough(!claim.isValid)
                    .foregroundStyle(claim.isValid ? CicadaTheme.textPrimary : CicadaTheme.textTertiary)
                    .textSelection(.enabled)
                    .fixedSize(horizontal: false, vertical: true)
                    .help(BeliefWords.help(claim))
                ClaimFooterFlow(spacing: 6) {
                    EvidenceChipRun(
                        chips: EvidenceChipModel.chips(evidence: claim.evidence, sourceEpisodes: claim.sourceEpisodes,
                                                       subjectId: claim.subject),
                        subjectId: claim.subject.isEmpty ? nil : claim.subject,
                        expanded: $showAllEvidence)
                    if signed, SignedLine.who(claim) != nil {
                        SignedLineView(claim: claim)
                    } else if let age = BeliefWords.age(claim, now: .now) {
                        Tag(text: age.text).help(age.help)
                    }
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            if let onOpenTimeline {
                IconButton(systemName: "clock", help: Copy.Graph.beliefTimelineHelp, action: onOpenTimeline)
            }
        }
        .padding(.leading, CicadaTheme.scaled(10))
        .padding(.trailing, CicadaTheme.spacingXS)
        .padding(.vertical, CicadaTheme.spacingSM)
        .background(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall).fill(hovering ? CicadaTheme.bgHover : Color.clear))
        .onHover { hovering = $0 }
    }
}
