import Observation
import SwiftUI

/// The two theme modes the SwiftUI chrome supports. Persisted via
/// `@AppStorage("cicada.colorScheme")` (see `CicadaApp`/`ContentView`) and
/// mirrored into `CicadaTheme.mode`.
enum AppColorScheme: String, CaseIterable {
    case light
    case dark
}

/// Storage behind `CicadaTheme.mode`, and the reason the sidebar's sun/moon
/// toggle repaints the whole app instead of two views.
///
/// `CicadaTheme` is a namespace of *static computed* colours. When the mode was
/// a plain `static var`, flipping it changed what every token would return but
/// invalidated nothing: SwiftUI only re-evaluates a `body` whose tracked inputs
/// changed, so only the root and the sidebar — the two views that read
/// `@AppStorage("cicada.colorScheme")` themselves — repainted, and the rest of
/// the app kept its cached dark colours. The toggle looked broken because it
/// effectively was.
///
/// Holding the mode in an `@Observable` object fixes that without touching a
/// single one of the hundreds of `CicadaTheme.xxx` call sites: SwiftUI evaluates
/// every `body` inside observation tracking, so reading `CicadaTheme.surface`
/// registers a dependency on `mode` and that view repaints when it changes.
///
/// The initial value is read from `UserDefaults` rather than mirrored out of a
/// view's `body`, so the persisted choice applies on the first frame and no
/// view writes observable state while rendering.
@Observable
final class ThemeStore {
    static let shared = ThemeStore()

    /// The key `@AppStorage` persists the toggle under.
    static let defaultsKey = "cicada.colorScheme"

    var mode: AppColorScheme

    /// The key `uiScale` persists under (G130).
    static let scaleKey = "cicada.uiScale"
    /// R1: one scale, clamped to a floor/ceiling a scaled layout can't clip
    /// past (R7's fixed frames get the benefit of the doubt up to 1.4).
    static let scaleRange: ClosedRange<Double> = 0.8...1.4
    /// R1: ⌘+/⌘− move in steps, not a continuous drag — only the Settings
    /// slider (Task 2) offers anything finer, and even that snaps here.
    static let scaleStep = 0.1

    var uiScale: Double

    init(defaults: UserDefaults = .standard) {
        let raw = defaults.string(forKey: Self.defaultsKey)
        mode = raw.flatMap(AppColorScheme.init(rawValue:)) ?? .dark

        // `defaults.double(forKey:)` returns exactly 0 both when the key is
        // absent (fresh install) and when it holds a non-numeric value (a
        // hand-edited plist). 0 is outside scaleRange, so running it through
        // clampScale first would silently clamp every fresh install to the
        // FLOOR (0.8) instead of today's layout (1.0) — the zero-check must
        // happen BEFORE clampScale. A real stored value still goes through
        // clampScale so a hand-edited plist can't smuggle an out-of-range or
        // off-step scale past the setter's guard.
        let storedScale = defaults.double(forKey: Self.scaleKey)
        uiScale = storedScale == 0 ? 1.0 : ThemeStore.clampScale(storedScale)
    }

    /// Snaps to the nearest 0.1 step, then clamps to `scaleRange` — the same
    /// multiply-by-10/round/divide-by-10 trick `CicadaTheme.scaled(_:)` uses,
    /// so float noise from repeated +/- 0.1 (e.g. `0.1 + 0.2 ==
    /// 0.30000000000000004`) never leaves a value that reads as "not on a
    /// step" to a test's `==` or to `resetZoom`'s callers.
    static func clampScale(_ value: Double) -> Double {
        let stepped = (value * 10).rounded() / 10
        return min(max(stepped, scaleRange.lowerBound), scaleRange.upperBound)
    }
}

enum CicadaTheme {
    /// Active theme mode. Defaults to `.dark` to preserve the app's original
    /// hardcoded look for anyone who hasn't touched the toggle yet.
    ///
    /// Stored in `ThemeStore`, which is `@Observable` — see its doc comment for
    /// why. Reading any token below inside a SwiftUI `body` subscribes that view
    /// to this value, so a flip repaints the whole tree without threading an
    /// `@Environment` value through it or rewriting a single reference.
    /// Assigning the value it already holds is a no-op: `@Observable` notifies
    /// on every write regardless of equality, and a redundant notification from
    /// inside a render pass is how you get an invalidation loop.
    static var mode: AppColorScheme {
        get { ThemeStore.shared.mode }
        set {
            guard ThemeStore.shared.mode != newValue else { return }
            ThemeStore.shared.mode = newValue
        }
    }

    // MARK: - Background & Surface
    static var background: Color { mode == .dark ? Dark.background : Light.background }
    static var surface: Color { mode == .dark ? Dark.surface : Light.surface }
    static var surfaceHover: Color { mode == .dark ? Dark.surfaceHover : Light.surfaceHover }
    static var surfaceElevated: Color { mode == .dark ? Dark.surfaceElevated : Light.surfaceElevated }
    static var border: Color { mode == .dark ? Dark.border : Light.border }
    static var borderLight: Color { mode == .dark ? Dark.borderLight : Light.borderLight }

    // MARK: - Text
    static var textPrimary: Color { mode == .dark ? Dark.textPrimary : Light.textPrimary }
    static var textSecondary: Color { mode == .dark ? Dark.textSecondary : Light.textSecondary }
    static var textTertiary: Color { mode == .dark ? Dark.textTertiary : Light.textTertiary }

    // MARK: - Accent
    static var accent: Color { mode == .dark ? Dark.accent : Light.accent }

    // MARK: - Semantic State Colors (G68)
    // Mode-aware success/warning/danger/info, following the `entityColor`
    // pattern above: one accessor here, one hue per palette below. Every page
    // that used to hardcode 0x22C55E / 0xF59E0B / 0xEF4444 / 0x3B82F6 (or the
    // near-duplicate blue 0x4A9EFF) reads these instead, so a state colour is
    // legible in BOTH modes and moves in one place. Brand hues (a vendor's own
    // colour — OriginPill, channel tints, AgentSetup.brand, provider badges)
    // stay literal at their call sites — they are identity, not state.
    static var success: Color { mode == .dark ? Dark.success : Light.success }
    static var warning: Color { mode == .dark ? Dark.warning : Light.warning }
    static var danger: Color { mode == .dark ? Dark.danger : Light.danger }
    static var info: Color { mode == .dark ? Dark.info : Light.info }

    /// Plate behind a monospaced command/config snippet (`CommandBox`). The
    /// old flat `Color.black.opacity(0.35)` put near-black `textPrimary` on a
    /// near-black plate in light mode; this is one step darker than the
    /// surface it sits on, in both modes.
    static var codeBackground: Color { mode == .dark ? Dark.codeBackground : Light.codeBackground }

    /// Timeline dot hue per commit change type (entity History tab). Replaces
    /// `HistoryChangeType.color`, which returned a hex STRING that the view
    /// re-parsed — a model has no business naming a colour.
    static func historyColor(for change: HistoryChangeType) -> Color {
        switch change {
        case .created: success
        case .updated, .relationAdded: info
        case .statusChange, .confidenceChange: warning
        }
    }

    // MARK: - Entity Type Colors
    // Mirrors the `typeColors` map in graph.js so the SwiftUI chrome and the d3
    // canvas agree on hue per type. Light mode reuses the same hue family, just
    // deepened (Tailwind ~600 band) so each still clears ~4.5:1 on a near-white
    // surface instead of the ~0.6:1 a pastel-on-white pairing would give.
    static func entityColor(for type: EntityType) -> Color {
        mode == .dark ? Dark.entityColor(for: type) : Light.entityColor(for: type)
    }

    // MARK: - Graph-specific accents
    static var mediaPink: Color { mode == .dark ? Dark.mediaPink : Light.mediaPink }
    static var hubGold: Color { mode == .dark ? Dark.hubGold : Light.hubGold }
    static var pendingPulse: Color { mode == .dark ? Dark.pendingPulse : Light.pendingPulse }

    // MARK: - Context Colors (claim layer)
    // Contexts are an open set, so we hash unknown ones into a stable hue and
    // hard-code the known core to keep the demo legible. Mirrored by
    // CONTEXT_COLORS in graph.js for the d3 canvas.
    static func contextColor(_ context: String) -> Color {
        mode == .dark ? Dark.contextColor(context) : Light.contextColor(context)
    }

    // MARK: - Status Colors
    static func statusColor(for status: EntityStatus) -> Color {
        mode == .dark ? Dark.statusColor(for: status) : Light.statusColor(for: status)
    }

    // MARK: - Usage heatmap (G51)
    /// Five-step sequential ramp for the usage heatmap (0 = empty cell).
    /// Derived from `accent` so it follows the light/dark palette automatically.
    static func heatRamp(level: Int) -> Color {
        switch max(0, min(4, level)) {
        case 0: surfaceElevated
        case 1: accent.opacity(0.30)
        case 2: accent.opacity(0.55)
        case 3: accent.opacity(0.80)
        default: accent
        }
    }

    // MARK: - Zoom (G130: one persisted uiScale behind every theme token)
    /// Active app-wide scale. Stored in `ThemeStore`, same `@Observable`
    /// mechanism as `mode` (see its doc comment) — reading any font or
    /// spacing token below inside a SwiftUI `body` subscribes that view to
    /// this value, so ⌘+/⌘−/⌘0 repaint the whole tree with no `.id()`
    /// anywhere (the PR #49 lesson) and no call site touched (R2).
    static var uiScale: Double {
        get { ThemeStore.shared.uiScale }
        set {
            // clampScale is applied HERE, not by callers — zoomIn/zoomOut do
            // plain float arithmetic on the current value and rely on this
            // setter to snap it back onto a step and inside range (R1: "0.1 +
            // 0.2 arithmetic never drifts"), and the Settings slider's
            // Binding can hand this raw drag values between steps.
            let clamped = ThemeStore.clampScale(newValue)
            // R4: idempotent, and never called from a body — only commands,
            // the key monitor and the Settings slider write it. Skipping a
            // redundant write also skips the redundant UserDefaults sync.
            guard ThemeStore.shared.uiScale != clamped else { return }
            ThemeStore.shared.uiScale = clamped
            UserDefaults.standard.set(clamped, forKey: ThemeStore.scaleKey)
        }
    }

    static func zoomIn() { uiScale = ThemeStore.shared.uiScale + ThemeStore.scaleStep }
    static func zoomOut() { uiScale = ThemeStore.shared.uiScale - ThemeStore.scaleStep }
    static func resetZoom() { uiScale = 1.0 }

    // MARK: - Typography (G130: derived from `uiScale`, so ⌘+/⌘− reach every reader)
    private static var scale: CGFloat { CGFloat(uiScale) }

    /// `pt * scale`, rounded to one decimal so accumulated float noise never
    /// makes a token drift off a value a snapshot test or a layout constant
    /// expects. `1.0` is today's layout exactly: `scaled(x) == x` (R1).
    static func scaled(_ pt: CGFloat) -> CGFloat { (pt * scale * 10).rounded() / 10 }

    /// Replaces every literal `.system(size:)` / `Font.system(size:)` call in
    /// `Sources/` (R3, migrated in a follow-up track) so a scaled font is one
    /// call away instead of a hand-rolled `.system(size: CicadaTheme.scaled(N))`
    /// at each of ~322 sites.
    ///
    /// **Measured quirk:** `Font.system(size:weight:)` (2-arg) and
    /// `Font.system(size:weight:design:)` (3-arg, even passed `.default`
    /// explicitly) are NOT `==` to each other despite rendering identically —
    /// verified with a standalone script, not assumed. Every pre-G130 literal
    /// in this file used the 2-arg form except `monoFont`. Branching on
    /// `design == .default` reproduces the 2-arg call for those tokens so
    /// `scaled(x) == x` at `uiScale == 1.0` (R1) means the SAME `Font` value
    /// today's layout used, not merely a visually-identical one a `==` test
    /// can't actually observe.
    static func font(size: CGFloat, weight: Font.Weight = .regular, design: Font.Design = .default) -> Font {
        let resolved = scaled(size)
        return design == .default
            ? .system(size: resolved, weight: weight)
            : .system(size: resolved, weight: weight, design: design)
    }

    static var titleFont: Font { font(size: 20, weight: .semibold) }
    static var headingFont: Font { font(size: 16, weight: .medium) }
    static var bodyFont: Font { font(size: 13) }
    static var captionFont: Font { font(size: 11) }
    static var monoFont: Font { font(size: 12, design: .monospaced) }

    // MARK: - Spacing (G130: derived from `uiScale` — the 551 call sites are untouched, R2)
    static var spacingXS: CGFloat { scaled(4) }
    static var spacingSM: CGFloat { scaled(8) }
    static var spacingMD: CGFloat { scaled(12) }
    static var spacingLG: CGFloat { scaled(16) }
    static var spacingXL: CGFloat { scaled(24) }
    static var spacingXXL: CGFloat { scaled(32) }

    // MARK: - Corner Radius
    static let cornerRadius: CGFloat = 12
    static let cornerRadiusSmall: CGFloat = 8

    // MARK: - Inbox Kind Colors
    // Leading-icon hue per inbox card kind. Decay amber, conflict red,
    // clarification indigo, merge yellow. Used by InboxCardView and the
    // sidebar/filter chrome.
    static func inboxColor(for kind: InboxKind) -> Color {
        mode == .dark ? Dark.inboxColor(for: kind) : Light.inboxColor(for: kind)
    }

    // MARK: - Diff / Decay Colors (G67 / G66)
    // Added/removed line color in the shared commit-diff renderer (`DiffView`,
    // reused by the entity History tab and the Contributors drill-down), and
    // the decay-chip tint. Both are THIN ALIASES of the semantic state tokens
    // above (G68) rather than their own hex pairs — dark mode was already the
    // exact same hex as success/danger/info/warning; light mode's separate
    // ~600-band values are dropped in favor of the deeper, higher-contrast
    // ~700-band the state tokens use. No duplicated hex pairs left in the
    // theme.
    static var diffAdded: Color { success }
    static var diffRemoved: Color { danger }
    static var decayDurable: Color { info }
    static var decayVolatile: Color { warning }
}

// MARK: - Dark Palette
// The app's original hand-tuned palette, unchanged. Radix-style 4-step
// elevation ramp on a Catppuccin/Tokyo-Night cool near-black base with a
// faint violet cast.

private extension CicadaTheme {
    enum Dark {
        // Darkening the canvas is the single biggest "pop" lever since the d3
        // graph is transparent and every node sits directly on `background`.
        static let background = Color(hex: 0x0E0F14)
        static let surface = Color(hex: 0x16171D)
        static let surfaceHover = Color(hex: 0x1D1F26)
        static let surfaceElevated = Color(hex: 0x23252E)
        static let border = Color(hex: 0x262A33)
        static let borderLight = Color(hex: 0x363B47)

        // AA-checked against the darkest surface (#0E0F14). Primary ~16.5:1
        // (AAA), secondary ~6.9:1 (AA), tertiary ~3.6:1 (decorative/large only).
        static let textPrimary = Color(hex: 0xECEDF2)
        static let textSecondary = Color(hex: 0x9BA1AE)
        static let textTertiary = Color(hex: 0x6B7180)

        // Periwinkle, nudged one notch brighter so it pops on the darker base.
        static let accent = Color(hex: 0x8896FF)

        // State hues, Tailwind ~500 band — same brightness register as the
        // entity hues above so they read as one system on the near-black base.
        static let success = Color(hex: 0x22C55E)
        static let warning = Color(hex: 0xF59E0B)
        static let danger = Color(hex: 0xEF4444)
        static let info = Color(hex: 0x4A9EFF)
        static let codeBackground = Color(hex: 0x0A0B0F)

        static func entityColor(for type: EntityType) -> Color {
            // Tailwind-400-band hues: each keeps its type identity but is pushed
            // brighter/more saturated so all 8 clear ~4.5:1+ on the darker base and
            // stay >15° apart in hue. MUST stay in sync with graph.js `typeColors`.
            switch type {
            case .person: Color(hex: 0x5AA8FF)
            case .project: Color(hex: 0xB57BFF)
            case .company: Color(hex: 0xFF8A3D)
            case .concept: Color(hex: 0x3BD97A)
            case .tool: Color(hex: 0x2DD4BF)
            case .deadline: Color(hex: 0xFF5C5C)
            case .skill: Color(hex: 0xF2C744)
            case .location: Color(hex: 0xAEB6C4)
            case .media: mediaPink
            case .hub: hubGold
            // directory = a slate blue-gray "Finder folder" hue. Saturated/bluer
            // than location's neutral gray (AEB6C4) so the two stay distinguishable,
            // and >15° off person-blue (5AA8FF) and project-purple (B57BFF).
            case .directory: Color(hex: 0x7AA0C4)
            case .unknown: Color(hex: 0x9BA1AE)
            }
        }

        static let mediaPink = Color(hex: 0xF65BA6)   // media entity hue
        static let hubGold = Color(hex: 0xE0A93A)     // hub ring / hub node hue (deeper amber, distinct from skill gold)
        static let pendingPulse = Color(hex: 0xFFCB57) // amber "needs you" pulse

        static func contextColor(_ context: String) -> Color {
            switch context {
            case "engineering":   return Color(hex: 0x2DD4BF)   // teal  = tool
            case "family":        return Color(hex: 0xF65BA6)   // pink  = media
            case "philosophical": return Color(hex: 0xB57BFF)   // purple = project
            case "career":        return Color(hex: 0xFF8A3D)   // orange = company
            case "cross":         return Color(hex: 0xF2C744)   // gold — the cross-context bridge (= skill)
            case "general":       return Color(hex: 0x7A8290)   // neutral, lifted to stay visible on the dark base
            default:
                // Stable hue for any open-tail context so the graph never flickers.
                // Mirrors graph.js `hashHue` (h = h*31 + charCode, 32-bit wrap, then
                // abs % 360) and its `hsl(hue, 55%, 68%)` output EXACTLY so the
                // SwiftUI chrome and the d3 canvas pick the same color for an
                // unknown context. NOTE: Swift's String.hashValue is per-process
                // randomized — never use it for a color that must be stable.
                let hue = Double(CicadaTheme.hashHue(context))
                return Color(hslHue: hue, saturation: 0.55, lightness: 0.68)
            }
        }

        static func statusColor(for status: EntityStatus) -> Color {
            switch status {
            case .active: accent
            case .decaying: Color(hex: 0xF5A93B)
            case .archived: Color(hex: 0x7A8290)
            case .dropped: Color(hex: 0xFF5C5C).opacity(0.6)
            }
        }

        static func inboxColor(for kind: InboxKind) -> Color {
            switch kind {
            case .decay: Color(hex: 0xF5A93B)
            case .conflict: Color(hex: 0xFF5C5C)
            case .clarification: Color(hex: 0x8896FF)
            case .mergeSuggestion: Color(hex: 0xF2C744)
            // G113 slice 3: no new hue budget — a divergence IS a conflict
            // shape (two competing claims) and a normalization IS a
            // clarification shape (confirm-or-correct), so each borrows its
            // sibling's color rather than adding a color the palette wasn't
            // designed around.
            case .divergence: Color(hex: 0xFF5C5C)
            case .normalization: Color(hex: 0x8896FF)
            // G129 slice 2 — decay's amber, darkened: a retraction reads as a
            // graver cousin of decay's fade, not a wholly new hue (R9, same
            // "no new hue budget" precedent as divergence/normalization above).
            case .removal: Color(hex: 0xC9822E)
            // Forward-compat bucket — no real category, reuse the muted text
            // token rather than inventing a colour for it (R8).
            case .unknown: Dark.textTertiary
            }
        }
    }
}

// MARK: - Light Palette
// Not a naive inversion of Dark: near-white surfaces with a faint cool cast
// (mirrors the dark base's violet tint), dark ink text, and entity/status
// hues deepened into the Tailwind ~600 band so they keep ~4.5:1+ contrast on
// a near-white surface instead of the ~pastel-on-white pairing a straight
// invert would give. Same hue family per type as Dark — only lightness/
// saturation changed — so the two modes still "feel" like the same app.

private extension CicadaTheme {
    enum Light {
        // Same 4-step elevation ramp, running the opposite direction: the
        // canvas is the flattest step, cards/panels get progressively closer
        // to pure white as they "lift" off it.
        static let background = Color(hex: 0xF5F6FA)
        static let surface = Color(hex: 0xFFFFFF)
        static let surfaceHover = Color(hex: 0xEDEEF3)
        static let surfaceElevated = Color(hex: 0xFFFFFF)
        static let border = Color(hex: 0xE3E5EC)
        static let borderLight = Color(hex: 0xCACDD9)

        // AA-checked against the background (#F5F6FA). Primary ~16.8:1 (AAA),
        // secondary ~7.3:1 (AA), tertiary ~4.0:1 (decorative/large only).
        static let textPrimary = Color(hex: 0x14161C)
        static let textSecondary = Color(hex: 0x51566A)
        static let textTertiary = Color(hex: 0x82879A)

        // Same periwinkle family, deepened for AA contrast on a near-white
        // surface (~4.7:1 vs the dark mode value's ~1.7:1 on white).
        static let accent = Color(hex: 0x5A62E0)

        // Same families, deepened into the Tailwind ~700 band so each clears
        // ~4.5:1 on the near-white surface instead of the ~1.8:1 the dark
        // values give.
        static let success = Color(hex: 0x15803D)
        static let warning = Color(hex: 0xB45309)
        static let danger = Color(hex: 0xB91C1C)
        static let info = Color(hex: 0x1D4ED8)
        static let codeBackground = Color(hex: 0xE7E9F0)

        static func entityColor(for type: EntityType) -> Color {
            switch type {
            case .person: Color(hex: 0x2A66D9)
            case .project: Color(hex: 0x8B3FE0)
            case .company: Color(hex: 0xD9650F)
            case .concept: Color(hex: 0x1C9A52)
            case .tool: Color(hex: 0x0E9488)
            case .deadline: Color(hex: 0xE43D3D)
            case .skill: Color(hex: 0xB48A00)
            case .location: Color(hex: 0x6B7180)
            case .media: mediaPink
            case .hub: hubGold
            case .directory: Color(hex: 0x4E6E8C)
            case .unknown: Color(hex: 0x6B7180)
            }
        }

        static let mediaPink = Color(hex: 0xD43C87)   // media entity hue
        static let hubGold = Color(hex: 0xA6740F)     // hub ring / hub node hue
        static let pendingPulse = Color(hex: 0xC67F00) // amber "needs you" pulse

        static func contextColor(_ context: String) -> Color {
            switch context {
            case "engineering":   return Color(hex: 0x0E9488)   // teal  = tool
            case "family":        return Color(hex: 0xD43C87)   // pink  = media
            case "philosophical": return Color(hex: 0x8B3FE0)   // purple = project
            case "career":        return Color(hex: 0xD9650F)   // orange = company
            case "cross":         return Color(hex: 0xB48A00)   // gold — the cross-context bridge (= skill)
            case "general":       return Color(hex: 0x5E6372)   // neutral, deepened to stay legible on the light base
            default:
                // Same hash as Dark for a stable per-context hue, but lightness
                // pulled down so the open-tail color stays readable on white.
                let hue = Double(CicadaTheme.hashHue(context))
                return Color(hslHue: hue, saturation: 0.55, lightness: 0.38)
            }
        }

        static func statusColor(for status: EntityStatus) -> Color {
            switch status {
            case .active: accent
            case .decaying: Color(hex: 0xB9740A)
            case .archived: Color(hex: 0x5E6372)
            case .dropped: Color(hex: 0xE43D3D).opacity(0.6)
            }
        }

        static func inboxColor(for kind: InboxKind) -> Color {
            switch kind {
            case .decay: Color(hex: 0xB9740A)
            case .conflict: Color(hex: 0xE43D3D)
            case .clarification: Color(hex: 0x5A62E0)
            case .mergeSuggestion: Color(hex: 0xB48A00)
            // G113 slice 3: same pairing as Dark above — divergence reads as
            // conflict, normalization reads as clarification.
            case .divergence: Color(hex: 0xE43D3D)
            case .normalization: Color(hex: 0x5A62E0)
            case .removal: Color(hex: 0x8A5A10)
            case .unknown: Light.textTertiary
            }
        }
    }
}

// MARK: - Shared hashing helper

private extension CicadaTheme {
    /// Deterministic 0–359 hue for an open-tail context string. Byte-for-byte
    /// match of graph.js `hashHue`: 32-bit signed wraparound on each step.
    static func hashHue(_ str: String) -> Int {
        var h: Int32 = 0
        for scalar in str.unicodeScalars {
            // charCodeAt() yields UTF-16 code units; restrict to BMP like JS
            // does for the demo's ASCII context labels.
            h = h &* 31 &+ Int32(truncatingIfNeeded: scalar.value)
        }
        return Int(abs(Int(h)) % 360)
    }
}

// MARK: - Glass Card Modifier

struct GlassCard: ViewModifier {
    var cornerRadius: CGFloat = CicadaTheme.cornerRadius

    func body(content: Content) -> some View {
        content
            .background {
                RoundedRectangle(cornerRadius: cornerRadius)
                    .fill(CicadaTheme.surface.opacity(0.6))
            }
            .background(.ultraThinMaterial)
            .clipShape(RoundedRectangle(cornerRadius: cornerRadius))
            .overlay(
                // On the darker base a thin border reads crisper than a heavy
                // glass blur (Linear/GitHub convention). Use the cool `border`
                // token instead of a flat white stroke, and a tighter shadow.
                RoundedRectangle(cornerRadius: cornerRadius)
                    .stroke(CicadaTheme.border, lineWidth: 1)
            )
            .shadow(color: .black.opacity(0.3), radius: 14, y: 8)
    }
}

extension View {
    func glassCard(cornerRadius: CGFloat = CicadaTheme.cornerRadius) -> some View {
        modifier(GlassCard(cornerRadius: cornerRadius))
    }
}

// MARK: - Plain Button Style (G83)

/// Shared replacement for `.buttonStyle(.cicadaPlain)`. Two problems in one fix:
///
/// 1. **Hit area.** A bare `Button { ... } label: { HStack { Image; Text } }`
///    styled `.plain` paints no background of its own, so SwiftUI falls back
///    to its default content shape — the union of the label's rendered
///    glyphs. Padding grows the layout box but NOT the tap target, which is
///    why clicking the icon/text works and the surrounding padded pill
///    doesn't. Wrapping `configuration.label` in `.contentShape(Rectangle())`
///    makes the tappable region match the label's full layout frame
///    (including padding) every time, at every adopting call site, from one
///    definition.
/// 2. **Snappy feedback.** Plain buttons gave no visual acknowledgement of a
///    click. A subtle scale-down + opacity dip keyed on `configuration.isPressed`,
///    with a short eased animation, makes every adopting button feel
///    responsive without changing its resting appearance.
struct CicadaPlainButtonStyle: ButtonStyle {
    /// Scale applied to the label while the button is pressed.
    static let pressedScale: CGFloat = 0.97
    /// Opacity applied to the label while the button is pressed.
    static let pressedOpacity: Double = 0.85
    /// Duration of the press/release transition.
    static let pressAnimationDuration: Double = 0.12

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .contentShape(Rectangle())
            .scaleEffect(configuration.isPressed ? Self.pressedScale : 1.0)
            .opacity(configuration.isPressed ? Self.pressedOpacity : 1.0)
            .animation(.easeOut(duration: Self.pressAnimationDuration), value: configuration.isPressed)
    }
}

extension ButtonStyle where Self == CicadaPlainButtonStyle {
    /// Drop-in replacement for `.buttonStyle(.cicadaPlain)` that also fixes the
    /// hit-area bug and adds pressed-state feedback. See `CicadaPlainButtonStyle`.
    static var cicadaPlain: CicadaPlainButtonStyle { CicadaPlainButtonStyle() }
}

// MARK: - Glass Plain Button Style (G83 review finding 2)

/// `CicadaPlainButtonStyle` for a button whose visible chrome is a
/// `.glassCard(...)` pill. `.glassCard()` chained AFTER `.buttonStyle(.cicadaPlain)`
/// wraps the button's ALREADY-styled output — the pill background sits outside
/// `CicadaPlainButtonStyle`'s own `scaleEffect`/`opacity`, which only reaches
/// `configuration.label`. The result: on press, the label dips but the glass
/// pill drawn behind it stays static — partial, not-quite-there feedback on
/// exactly the top-bar/toolbar buttons the user hits constantly.
///
/// This style folds the SAME glass-card decoration (`.modifier(GlassCard(...))`
/// — the existing `GlassCard` recipe, not a duplicated copy) into `makeBody`
/// itself, so the card is composed BEFORE the pressed-state transform, and the
/// whole pill — background, border, shadow included — scales/dims together.
/// Replaces the `.buttonStyle(.cicadaPlain)` + `.glassCard(cornerRadius:)` pair
/// at every site where they decorate the SAME button (not a container that
/// merely happens to wrap several buttons in one shared card — that pattern is
/// unaffected and stays as plain `.glassCard()` on the container).
struct CicadaGlassButtonStyle: ButtonStyle {
    var cornerRadius: CGFloat = CicadaTheme.cornerRadius

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .contentShape(Rectangle())
            .modifier(GlassCard(cornerRadius: cornerRadius))
            .scaleEffect(configuration.isPressed ? CicadaPlainButtonStyle.pressedScale : 1.0)
            .opacity(configuration.isPressed ? CicadaPlainButtonStyle.pressedOpacity : 1.0)
            .animation(.easeOut(duration: CicadaPlainButtonStyle.pressAnimationDuration), value: configuration.isPressed)
    }
}

extension ButtonStyle where Self == CicadaGlassButtonStyle {
    static var cicadaGlass: CicadaGlassButtonStyle { CicadaGlassButtonStyle() }
    static func cicadaGlass(cornerRadius: CGFloat) -> CicadaGlassButtonStyle {
        CicadaGlassButtonStyle(cornerRadius: cornerRadius)
    }
}

// MARK: - Color Hex Init

extension Color {
    init(hex: UInt32, opacity: Double = 1.0) {
        self.init(
            .sRGB,
            red: Double((hex >> 16) & 0xFF) / 255.0,
            green: Double((hex >> 8) & 0xFF) / 255.0,
            blue: Double(hex & 0xFF) / 255.0,
            opacity: opacity
        )
    }

    /// HSL initializer so we can match CSS `hsl()` exactly. SwiftUI's stock
    /// `Color(hue:saturation:brightness:)` is HSB, which produces a different
    /// color for the same numbers — graph.js emits `hsl(...)`, so the open-tail
    /// context color must be computed in HSL to agree with the d3 canvas.
    init(hslHue: Double, saturation s: Double, lightness l: Double, opacity: Double = 1.0) {
        let h = (hslHue.truncatingRemainder(dividingBy: 360) + 360)
            .truncatingRemainder(dividingBy: 360) / 360.0
        let c = (1 - abs(2 * l - 1)) * s
        let x = c * (1 - abs((h * 6).truncatingRemainder(dividingBy: 2) - 1))
        let m = l - c / 2
        let (r1, g1, b1): (Double, Double, Double)
        switch h * 6 {
        case ..<1: (r1, g1, b1) = (c, x, 0)
        case ..<2: (r1, g1, b1) = (x, c, 0)
        case ..<3: (r1, g1, b1) = (0, c, x)
        case ..<4: (r1, g1, b1) = (0, x, c)
        case ..<5: (r1, g1, b1) = (x, 0, c)
        default:   (r1, g1, b1) = (c, 0, x)
        }
        self.init(.sRGB, red: r1 + m, green: g1 + m, blue: b1 + m, opacity: opacity)
    }
}
