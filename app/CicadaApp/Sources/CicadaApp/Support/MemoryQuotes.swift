import Foundation

/// G153 — one line about memory or forgetting on You're set (owner, 2026-09-24: "a you're set message, and a nice
/// quote about forgetting or memory"). Public domain only; each line was checked word for word against the Project
/// Gutenberg edition named in `source` on 2026-09-24, and nothing is paraphrased. `year` is when the work first reached
/// an audience: a play's first performance, otherwise its first printing. A line whose source cannot be opened and
/// checked does not join this table.
struct MemoryQuote: Equatable, Identifiable, Sendable {
    let id: String
    let text: String
    let author: String
    let work: String
    let year: Int
    let source: String
}

enum MemoryQuotes {
    static let defaultsKey = "cicada.onboarding.quote"

    static let all: [MemoryQuote] = [
        MemoryQuote(id: "wilde-earnest",
                    text: "Memory, my dear Cecily, is the diary that we all carry about with us.",
                    author: "Oscar Wilde", work: "The Importance of Being Earnest", year: 1895,
                    source: "Act II, Miss Prism; first performed 1895. Project Gutenberg eBook #844"),
        MemoryQuote(id: "carroll-looking-glass",
                    text: "It’s a poor sort of memory that only works backwards.",
                    author: "Lewis Carroll", work: "Through the Looking-Glass", year: 1871,
                    source: "Chapter V, the White Queen (the source's comma before “the Queen remarked” ends the "
                        + "sentence here); published December 1871, title page 1872. Project Gutenberg eBook #12"),
        MemoryQuote(id: "james-principles",
                    text: "If we remembered everything, we should on most occasions be as ill off as if we remembered nothing.",
                    author: "William James", work: "The Principles of Psychology", year: 1890,
                    source: "Volume 1, Chapter XVI, Memory. Project Gutenberg eBook #57628"),
        MemoryQuote(id: "austen-mansfield",
                    text: "If any one faculty of our nature may be called more wonderful than the rest, I do think it is memory.",
                    author: "Jane Austen", work: "Mansfield Park", year: 1814,
                    source: "Chapter XXII, Fanny Price (“more” is italic in the source). Project Gutenberg eBook #141"),
        MemoryQuote(id: "rossetti-remember",
                    text: "Better by far you should forget and smile\nThan that you should remember and be sad.",
                    author: "Christina Rossetti", work: "Remember", year: 1862,
                    source: "Goblin Market and Other Poems (1862). Project Gutenberg eBook #16950"),
        MemoryQuote(id: "shakespeare-tempest",
                    text: "What seest thou else\nIn the dark backward and abysm of time?",
                    author: "William Shakespeare", work: "The Tempest", year: 1611,
                    source: "Act I, Scene 2, Prospero; performed at Whitehall, 1 November 1611. Project Gutenberg eBook #1540"),
        MemoryQuote(id: "johnson-idler",
                    text: "The true art of memory is the art of attention.",
                    author: "Samuel Johnson", work: "The Idler, No. 74", year: 1759,
                    source: "15 September 1759; The Works of Samuel Johnson, Vol. 4. Project Gutenberg eBook #12050"),
    ]

    /// One line per install (G153: "picked at random per install"), chosen the first time You're set shows and kept
    /// per viewer, so a rerun shows the same line. An id a later build dropped re-picks.
    static func chosen(defaults: UserDefaults = .standard, random: () -> Int = { Int.random(in: 0..<Int.max) }) -> MemoryQuote {
        if let id = defaults.string(forKey: defaultsKey), let kept = all.first(where: { $0.id == id }) { return kept }
        let quote = all[abs(random() % all.count)]
        defaults.set(quote.id, forKey: defaultsKey)
        return quote
    }
}
