import SwiftUI

/// Proposed ruling 55 (G81): the bank holds `[number:<ten letters>]`, and the digits come only from
/// `POST /people/numbers/reveal`, for what is on screen, in memory, never stored. A token the vault can't answer reads
/// "a number", never as the token.
enum NumberTokens {
    private static var pattern: Regex<(Substring, Substring)> { #/\[number:([a-z]{10})\]/# }

    static func ids(in text: String) -> [String] {
        var seen = Set<String>()
        return text.matches(of: pattern).map { String($0.output.1) }.filter { seen.insert($0).inserted }
    }

    static func shown(_ text: String, _ numbers: [String: String]) -> String {
        guard text.contains("[number:") else { return text }
        return text.replacing(pattern) { numbers[String($0.output.1)] ?? Copy.Graph.aNumber }
    }

    static func shown(_ segments: [CitedSpan.Segment], _ numbers: [String: String]) -> [CitedSpan.Segment] {
        segments.map { .init(text: shown($0.text, numbers), mark: $0.mark) }
    }

    static func isNumber(_ claim: Claim) -> Bool {
        claim.predicate == "phone" && claim.object.wholeMatch(of: pattern) != nil
    }

    /// The digits for what a person's page says is current, in the order the claims came.
    static func current(_ claims: [Claim], _ numbers: [String: String]) -> [String] {
        claims.filter { isNumber($0) && $0.isValid }
            .flatMap { ids(in: $0.object) }
            .compactMap { numbers[$0] }
    }
}

extension EnvironmentValues {
    /// What this Reader has revealed for the document it is showing (`ReaderColumn`), read by each passage it draws.
    @Entry var revealedNumbers: [String: String] = [:]
}

/// A person's current numbers on their page (DR-81: nothing to say, nothing drawn). Fetched here rather than sent in the
/// page's blocks (DR-78), because a page's blocks reach other clients and must never carry a digit.
struct PersonNumbersRow: View {
    let entityId: String
    @State private var numbers: [String] = []
    @State private var problem: String?

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            if !numbers.isEmpty {
                HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.spacingSM) {
                    Text(Copy.Graph.phone)
                        .font(CicadaTheme.metaFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                    VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                        ForEach(numbers, id: \.self) { number in
                            Text(number)
                                .font(CicadaTheme.bodyFont)
                                .foregroundStyle(CicadaTheme.textPrimary)
                                .textSelection(.enabled)
                        }
                    }
                }
            }
            if let problem {
                Text(problem)
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
            }
        }
        .task(id: entityId) { await load() }
    }

    private func load() async {
        numbers = []
        problem = nil
        let id = entityId
        let claims = (try? await APIClient.shared.fetchClaims(subject: id, predicates: ["phone"])) ?? []
        let tokens = claims.filter(NumberTokens.isNumber).flatMap { NumberTokens.ids(in: $0.object) }
        guard !tokens.isEmpty, !Task.isCancelled else { return }
        guard let answer = await APIClient.shared.revealNumbers(tokens), !Task.isCancelled, id == entityId else { return }
        numbers = NumberTokens.current(claims, answer.numbers)
        problem = answer.problem
    }
}
