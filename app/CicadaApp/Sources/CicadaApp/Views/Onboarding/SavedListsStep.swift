import SwiftUI

/// Onboarding, step 5 (owner 2026-10-26: "maybe when first onboarding you ask the user 'Do you want an agent to go through
/// your saved posts?'"; ruling 39's dated line). Every list the person's own agent can keep current from their signed-in
/// browser, pre-ticked (an off they chose before stays unticked), one plain line on how and on the sites' terms, and the
/// foot's one primary — whose answer is the consent (`SavedListsStepModel.write`, sent by `OnboardingView`). Nothing is
/// read before that button; Skip changes nothing. A departure from "nothing is pre-ticked" dated in DESIGN_RULES §9.
/// DR-5 (no accent here), DR-20, DR-38, DR-48, DR-52 (each platform's own mark), DR-70.
struct SavedListsStep: View {
    @Binding var ticked: Set<SavedListItem>
    let failure: String?

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
            OnboardingHeadline(title: Copy.savedListsTitle, subline: Copy.savedListsSubline)
            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                ForEach(SavedListItem.allCases) { item in
                    Toggle(isOn: Binding(get: { ticked.contains(item) },
                                         set: { on in if on { ticked.insert(item) } else { ticked.remove(item) } })) {
                        HStack(spacing: CicadaTheme.spacingSM) {
                            OriginMark(origin: item.origin, size: CicadaTheme.scaled(18))
                            Text(item.title)
                                .font(CicadaTheme.bodyFont)
                                .foregroundStyle(CicadaTheme.textPrimary)
                        }
                    }
                    .toggleStyle(.checkbox)
                }
            }
            if let failure {
                Text(failure).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.danger)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }
}
