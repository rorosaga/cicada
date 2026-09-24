import Observation
import AppKit
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

    /// G139 (R-O4) — the system appearance, observable like `mode`, so a
    /// `system` preference repaints both scenes when macOS flips.
    var systemIsDark: Bool

    /// The key `uiScale` persists under (G130).
    static let scaleKey = "cicada.uiScale"
    /// R1: one scale, clamped to a floor/ceiling a scaled layout can't clip
    /// past (R7's fixed frames get the benefit of the doubt up to 1.4).
    static let scaleRange: ClosedRange<Double> = 0.8...1.4
    /// R1: ⌘+/⌘− move in steps, not a continuous drag — only the Settings
    /// slider (Task 2) offers anything finer, and even that snaps here.
    static let scaleStep = 0.1

    var uiScale: Double

    /// Where the preference and `AppleInterfaceStyle` are re-read on a flip —
    /// a test hands in a suite, the app the standard domain.
    @ObservationIgnored private let defaults: UserDefaults
    /// The one distributed-notification observer (see `observeSystemAppearance`).
    @ObservationIgnored private var systemObserver: NSObjectProtocol?

    init(defaults: UserDefaults = .standard, systemIsDark: Bool? = nil) {
        self.defaults = defaults
        let dark = systemIsDark ?? AppearancePreference.systemIsDark(defaults)
        self.systemIsDark = dark
        mode = AppearancePreference.stored(defaults.string(forKey: Self.defaultsKey)).resolved(systemIsDark: dark)

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

    /// Re-reads the system appearance and re-resolves `mode` from the stored
    /// preference. Writes only on a real change — `@Observable` notifies on
    /// every write, and `CicadaTheme.mode`'s setter documents why a redundant
    /// notification is how an invalidation loop starts.
    func refreshSystemAppearance() {
        let dark = AppearancePreference.systemIsDark(defaults)
        if systemIsDark != dark { systemIsDark = dark }
        let resolved = AppearancePreference.stored(defaults.string(forKey: Self.defaultsKey))
            .resolved(systemIsDark: dark)
        if mode != resolved { mode = resolved }
    }

    /// G139 final review (R-O4): the macOS appearance observer used to hang off
    /// the main window's `ContentView` alone, so a flip while that window was
    /// closed — menu-bar only, or only Settings open — was missed, and the
    /// window reopened in the old mode until the next flip. Registered once at
    /// app scope (`CicadaApp.init`) instead, so every scene follows whichever
    /// windows are open. Idempotent; never called from `init` so a headless
    /// test's `ThemeStore` never listens to the real system.
    func observeSystemAppearance() {
        guard systemObserver == nil else { return }
        systemObserver = DistributedNotificationCenter.default().addObserver(
            forName: AppearancePreference.systemChangedNotification, object: nil, queue: .main
        ) { [weak self] _ in self?.refreshSystemAppearance() }
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

    // MARK: - Graphite neutrals (Direction D — DESIGN_RULES §3.1, DR-1, DR-72)
    // One base and small lightness steps from it, chroma ≤ 4 (ThemeTokenTests measures each in
    // CIE Lab). Hue is spent on data, never on chrome (P-c); the Meadow neutrals retired as a
    // base (DR-13). The pre-D names below are ALIASES, so the hundreds of call sites that read
    // `background` / `surface` / `surfaceHover` follow without being touched (R-DS2).
    static var bgRail: Color { mode == .dark ? Dark.bgRail : Light.bgRail }
    static var bgBase: Color { mode == .dark ? Dark.bgBase : Light.bgBase }
    static var bgPane: Color { mode == .dark ? Dark.bgPane : Light.bgPane }
    static var bgHover: Color { mode == .dark ? Dark.bgHover : Light.bgHover }
    static var bgFocus: Color { mode == .dark ? Dark.bgFocus : Light.bgFocus }
    static var bgOption: Color { mode == .dark ? Dark.bgOption : Light.bgOption }
    static var bgButton: Color { mode == .dark ? Dark.bgButton : Light.bgButton }
    static var bgButtonHover: Color { mode == .dark ? Dark.bgButtonHover : Light.bgButtonHover }
    static var bgSelected: Color { mode == .dark ? Dark.bgSelected : Light.bgSelected }
    static var bgMenu: Color { mode == .dark ? Dark.bgMenu : Light.bgMenu }
    static var bgKey: Color { mode == .dark ? Dark.bgKey : Light.bgKey }
    /// The keycap's glyph (DR-49) — text on `bgKey`, 5.4:1 / 5.6:1.
    static var keyGlyph: Color { mode == .dark ? Dark.keyGlyph : Light.keyGlyph }
    /// The rail's pending numeral (DR-22, DR-51) and the Projects band's unfilled track (§3.8).
    static var bgBadge: Color { mode == .dark ? Dark.bgBadge : Light.bgBadge }
    /// A hovered rail cell (R-DS13). Light cannot use `bgHover`: it IS `bgRail` (#EFEFEC), so
    /// the hover would not show; `bgButtonHover`'s light step (#E3E3E0) is the mock's value.
    static var bgRailHover: Color { mode == .dark ? Dark.bgHover : Light.bgButtonHover }
    /// DR-23 — the command bar: `bgHover` in dark, `bgMenu` (with its ring) in light.
    static var commandBarFill: Color { mode == .dark ? Dark.bgHover : Light.bgMenu }

    // MARK: - Background & Surface (the pre-D names — aliases, R-DS2)
    static var background: Color { bgBase }
    /// The one pre-D name the rules' table does not rename. A card is the focus surface.
    static var surface: Color { bgFocus }
    static var surfaceHover: Color { bgHover }
    static var surfaceElevated: Color { bgFocus }
    /// The opaque twin of the resting ring (white 7 % / black 8 % over `bgBase`) — for AppKit
    /// and graph.js, which need an opaque colour. New code draws the ring (`ringed`), never this.
    static var border: Color { mode == .dark ? Dark.border : Light.border }
    /// The opaque twin of the input border (white 14 % / black 16 % over `bgBase`); graph.js's
    /// edges (R-DS2).
    static var borderLight: Color { mode == .dark ? Dark.borderLight : Light.borderLight }

    // MARK: - Text (DR-2: four steps plus one fill variant)
    static var textPrimary: Color { mode == .dark ? Dark.textPrimary : Light.textPrimary }
    static var textSecondary: Color { mode == .dark ? Dark.textSecondary : Light.textSecondary }
    static var textTertiary: Color { mode == .dark ? Dark.textTertiary : Light.textTertiary }
    /// Tertiary text ON a selected or hovered fill: light `textTertiary` is 4.33:1 on
    /// `bgSelected`, under the 4.5:1 bar (DR-2). Dark's tertiary already clears it.
    static var textTertiaryOnFill: Color { mode == .dark ? Dark.textTertiary : Light.textTertiaryOnFill }
    /// Disabled states only (DR-3) — never the only cue, never text a reader needs.
    static var textQuaternary: Color { mode == .dark ? Dark.textQuaternary : Light.textQuaternary }

    // MARK: - Accent (DR-4 … DR-6)
    /// DR-4 — one accent, and it is the Mac's. Native toggles, sliders, segmented controls and
    /// `.borderedProminent` then match with no `.tint`, which removes the two-accent problem at
    /// its root. Six uses only (DR-5): the focus ring, the one primary action, radio dots and the
    /// highlighted option's ring, the cited span, links, "Recommended".
    static var accent: Color { .accentColor }
    /// Links and "Recommended" (DR-5 uses 5–6) — see `AccentInk` (R-DS4).
    static var accentText: Color { mode == .dark ? AccentInk.textDark : AccentInk.textLight }
    static var accentTextHover: Color { mode == .dark ? AccentInk.hoverDark : AccentInk.hoverLight }
    /// The cited span's wash (DR-18) and the other spans' (`washSoft`).
    static var wash: Color { accent.opacity(mode == .dark ? 0.18 : 0.10) }
    static var washSoft: Color { accent.opacity(mode == .dark ? 0.08 : 0.07) }
    /// Keyboard focus — 2 pt at 60 % (DR-5 use 1).
    static var focusRing: Color { accent.opacity(0.6) }

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
    /// near-black plate in light mode. Direction D: the base itself, untinted
    /// (the Meadow plate carried a green cast DR-1 retires) — a snippet sits on
    /// a focus card, so `bgBase` is already the step below it in both modes.
    static var codeBackground: Color { mode == .dark ? Dark.codeBackground : Light.codeBackground }

    // MARK: - Text on a fill
    /// Ink ON an accent fill: white in both modes (R-DS5) — the native prominent label. 3.6:1 /
    /// 4.0:1 on the default blue, so it is legal only at ≥ 13 pt medium on the ONE primary
    /// button (DR-6); `PrimaryActionInk` still swaps it for `textPrimary` in a window that is
    /// not key, where the accent plate is gone.
    static var onAccent: Color { .white }
    /// Track I T4 (design §7, D-4) — the ink on the one meadow pill: white on the day meadow
    /// (#37753D, 5.56:1), graphite ink on the night meadow (#7FC98A, 9.49:1).
    static var onMeadow: Color { mode == .dark ? Dark.onMeadow : Light.onMeadow }
    /// The dim behind the intake overlay and the drop veil.
    static var scrim: Color { mode == .dark ? Dark.scrim : Light.scrim }
    /// DR-33 — the lighter dim behind the Settings panel and the palette: the page stays
    /// legible behind a panel you opened on purpose.
    static var scrimPanel: Color { mode == .dark ? Dark.scrimPanel : Light.scrimPanel }

    // MARK: - Elevation (DESIGN_RULES §3.5 — `Theme/Elevation.swift` applies these)
    enum Ring { case resting, strong, floating, input, edge }
    /// Rings are translucent so one value works on every surface (DR-9).
    static func ring(_ ring: Ring) -> Color {
        let dark = mode == .dark
        switch ring {
        case .resting: return dark ? Color.white.opacity(0.07) : Color.black.opacity(0.08)
        case .strong: return dark ? Color.white.opacity(0.12) : Color.black.opacity(0.12)
        case .floating: return dark ? Color.white.opacity(0.10) : Color.black.opacity(0.08)
        case .input: return dark ? Color.white.opacity(0.14) : Color.black.opacity(0.16)
        case .edge: return dark ? Color.white.opacity(0.07) : Color.black.opacity(0.07)
        }
    }
    /// DR-18 — the 2 pt rule a quote block is indented behind.
    static var quoteRule: Color { mode == .dark ? Color.white.opacity(0.16) : Color.black.opacity(0.14) }

    // MARK: - Progress (§3.8 — the Projects band; the one Meadow-derived data hue)
    static var progressFill: Color { mode == .dark ? Dark.progressFill : Light.progressFill }

    // MARK: - Meadow nature tokens (G137, spec R-M2)
    // Ambient ONLY: washes, art, onboarding / empty-state / header bands.
    // NEVER a data encoding — a sunnier meadow must never mean "more
    // memories" (R9 §7, G125's "art encodes state, never quantity"). The four
    // text-safe tokens (sky, meadow, dandelion, bark) clear 4.5:1 on
    // `background` in both modes; the washes, `dandelionFill`, `cloud` and
    // `soil` are fills and imagery, never text.
    static var sky: Color { mode == .dark ? Dark.sky : Light.sky }
    static var skyWash: Color { mode == .dark ? Dark.skyWash : Light.skyWash }
    static var meadow: Color { mode == .dark ? Dark.meadow : Light.meadow }
    static var meadowWash: Color { mode == .dark ? Dark.meadowWash : Light.meadowWash }
    static var dandelion: Color { mode == .dark ? Dark.dandelion : Light.dandelion }
    /// A highlighter behind words, used at 35 % — textPrimary over that wash
    /// is 7.18:1 in dark and 14.1:1 in light (ThemeTokenTests).
    static var dandelionFill: Color { mode == .dark ? Dark.dandelionFill : Light.dandelionFill }
    static var cloud: Color { mode == .dark ? Dark.cloud : Light.cloud }
    static var bark: Color { mode == .dark ? Dark.bark : Light.bark }
    static var soil: Color { mode == .dark ? Dark.soil : Light.soil }

    /// The three procedural skies (R-M2): zero bytes, so night costs nothing.
    /// Mode-INDEPENDENT on purpose — a caller may put a dusk band in a light
    /// window — with `current` as the default that follows the theme.
    enum SkyPhase: CaseIterable {
        case day, dusk, night

        /// Day in a light window, night in a dark one. Read in a `body`, this
        /// subscribes the view to the theme like every other token.
        static var current: SkyPhase { CicadaTheme.mode == .dark ? .night : .day }
    }

    /// Top-to-bottom stops. Text contrast on the extreme stops (measured):
    /// light ink on day's top 11.2:1, moonlit ink on dusk's horizon 4.78:1,
    /// on night ≥ 13:1.
    static func skyGradient(_ phase: SkyPhase) -> [Color] {
        switch phase {
        case .day: [Color(hex: 0xB9D7F0), Color(hex: 0xE9F2F6)]
        case .dusk: [Color(hex: 0x1C2344), Color(hex: 0x3A3A6A), Color(hex: 0x7A5E7E)]
        case .night: [Color(hex: 0x0A0F1E), Color(hex: 0x172538)]
        }
    }

    /// Track Z Z10 — the Sleep page's optional sky band, at this strength over
    /// the page in both modes. `SkyBandTests` holds it to a tint (≤ 1.35:1
    /// against the page) that keeps text ≥ 7:1 over it, for every sky.
    static let skyBandOpacity: Double = 0.12

    /// The window's AppKit background for `mode` — the one place `NSWindow`
    /// gets a theme colour (R-M10). Takes the mode explicitly because
    /// `syncWindowChrome` runs for the mode being switched TO.
    static func windowBackground(for mode: AppColorScheme) -> NSColor {
        NSColor(mode == .dark ? Dark.bgBase : Light.bgBase)
    }

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
    // canvas agree on hue per type (GraphPaletteTwinTests holds the dark
    // values). Light mode reuses the same hue family, deepened into the
    // Tailwind ~600 band; which of those clear 4.5:1 as text and which are
    // non-text only is measured in the Light palette's comment (G137).
    static func entityColor(for type: EntityType) -> Color {
        mode == .dark ? Dark.entityColor(for: type) : Light.entityColor(for: type)
    }

    // MARK: - Graph-specific accents
    static var mediaPink: Color { mode == .dark ? Dark.mediaPink : Light.mediaPink }
    static var hubGold: Color { mode == .dark ? Dark.hubGold : Light.hubGold }
    static var pendingPulse: Color { mode == .dark ? Dark.pendingPulse : Light.pendingPulse }
    /// Text drawn ON an identity-hue fill (a Sleep book spine, Track Z Z-P19).
    /// Mode-independent on purpose: the fill is an origin's own colour, not a
    /// theme surface, so the text on it does not flip with the theme.
    static var onFill: Color { .white }

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
    /// R-DS6 — a data ramp, so it keeps the retired indigo when the chrome's
    /// accent moves (DR-8): the Mac's accent is chrome, and a heatmap that
    /// turned orange because someone picked orange in System Settings would
    /// be encoding their preference, not their usage.
    static func heatRamp(level: Int) -> Color {
        switch max(0, min(4, level)) {
        case 0: surfaceElevated
        case 1: dataIndigo.opacity(0.30)
        case 2: dataIndigo.opacity(0.55)
        case 3: dataIndigo.opacity(0.80)
        default: dataIndigo
        }
    }
    /// R-DS6 — the pre-D accent, frozen as a data hue ("active" status, the heat ramp).
    private static var dataIndigo: Color { mode == .dark ? Dark.dataIndigo : Light.dataIndigo }

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

    // MARK: - The type ladder (DESIGN_RULES §4, DR-16). SF only (DR-15).
    static var titleFont: Font { font(size: 20, weight: .semibold) }
    /// Error-card titles and panel headings: 17 semibold (DR-16; was 16 medium).
    static var headingFont: Font { font(size: 17, weight: .semibold) }
    /// 13 regular — body off detail surfaces, and the command bar's placeholder. R-DS9: a global
    /// 14 would resize 136 bodies on list pages, where the ladder wants 13.
    static var bodyFont: Font { font(size: 13) }
    /// 14 regular — body on a detail surface (the focus card, the Reader), adopted by DS-2.
    static var detailBodyFont: Font { font(size: 14) }
    /// A row's title, a list question: 13 medium.
    static var rowFont: Font { font(size: 13, weight: .medium) }
    /// Meta, the eyebrow, source lines: 12 regular; links and the eyebrow's medium: 12 medium.
    static var metaFont: Font { font(size: 12) }
    static var metaMediumFont: Font { font(size: 12, weight: .medium) }
    static var captionFont: Font { font(size: 11) }
    /// DR-19 — only for what a person would copy (MonospaceLintTests holds the list).
    static var monoFont: Font { font(size: 12, design: .monospaced) }
    /// DR-20 — the one section label: 11 medium, sentence case, never mono, never tracked.
    /// `SectionLabel` is its one reader (SectionLabelLintTests).
    static var labelFont: Font { font(size: 11, weight: .medium) }
    /// The rail's pending numeral: 10 semibold, tabular at the call site (DR-16, DR-22).
    static var badgeFont: Font { font(size: 10, weight: .semibold) }

    // MARK: - Display + quote (DR-15, DR-18)
    /// Display is a role, not a face: page titles, the question H1, onboarding headlines,
    /// empty-state titles — never a number, never body text. Floor 20 (DR-15; was 22): the
    /// Reader title and an empty state's title are 20.
    static let displayMinimumSize: CGFloat = 20

    /// SF Pro Display — the system face at display sizes (macOS picks the Display cut itself
    /// above 20 pt): semibold for a title, regular italic for a headline's quieter second line.
    /// Instrument Serif and New York are retired (owner, 2026-09-23; DESIGN_RULES §9).
    static func displayFont(size: CGFloat, italic: Bool = false) -> Font {
        let resolved = scaled(max(size, displayMinimumSize))
        return italic
            ? Font.system(size: resolved, weight: .regular, design: .default).italic()
            : Font.system(size: resolved, weight: .semibold, design: .default)
    }

    /// DR-15 — −0.3 at 20 pt, −0.4 at 22 pt and above, scaled with the face (uiScale). `Font`
    /// cannot carry tracking, so each roman call site pairs `.font(displayFont(size: n))` with
    /// `.tracking(displayTracking(size: n))`; FontLiteralLintTests counts the pairs.
    static func displayTracking(size: CGFloat) -> CGFloat {
        (max(size, displayMinimumSize) >= 22 ? -0.4 : -0.3) * scale
    }

    /// DR-18 — the person's own words and an agent's: SF 15 regular — not italic, not serif.
    /// The cited span is washed and underlined (`CitedSpan`); inside a quote there is no bold
    /// and no italic.
    static var quoteFont: Font { quoteFont(size: 15) }
    static func quoteFont(size: CGFloat) -> Font { font(size: size) }
    /// A quote's line is 25 pt (DR-16): SF 15's natural line is 18 pt, so 7 pt of spacing.
    static var quoteLineSpacing: CGFloat { scaled(7) }

    // MARK: - Icons (DR-53)
    enum IconRole {
        case rail, railFoot, titlebar, sidebar, list, commandBar, inline, badge
        var points: CGFloat {
            switch self {
            case .rail: 18
            case .railFoot: 17
            case .titlebar, .sidebar: 16
            case .list: 14
            case .commandBar: 13
            case .inline: 12
            case .badge: 10
            }
        }
    }
    static func icon(_ role: IconRole) -> Font { font(size: role.points) }
    static func iconPoints(_ role: IconRole) -> CGFloat { scaled(role.points) }

    // MARK: - Spacing (G130: derived from `uiScale` — the 551 call sites are untouched, R2)
    static var spacingXS: CGFloat { scaled(4) }
    static var spacingSM: CGFloat { scaled(8) }
    static var spacingMD: CGFloat { scaled(12) }
    static var spacingLG: CGFloat { scaled(16) }
    static var spacingXL: CGFloat { scaled(24) }
    static var spacingXXL: CGFloat { scaled(32) }
    /// DR-12 table — the focus card's padding, and the list/detail gutter.
    static var spacingCard: CGFloat { scaled(28) }
    static var spacingGutter: CGFloat { scaled(40) }

    // MARK: - Corner Radius (DR-12)
    static let cornerRadius: CGFloat = 10          // the command bar, menus, popovers, the palette, grouped blocks
    static let cornerRadiusSmall: CGFloat = 8      // rows, option rows, buttons, rail cells, tabs, fields
    static let radiusXS: CGFloat = 4               // keycaps, the span wash
    static let radiusLarge: CGFloat = 16           // the focus card, the Settings panel, error and empty cards

    /// DR-12 — every rounded rectangle is continuous. New code draws through this; the
    /// app-wide sweep of bare `RoundedRectangle(cornerRadius:` is a page-track job (R-DS8).
    static func shape(_ radius: CGFloat) -> RoundedRectangle {
        RoundedRectangle(cornerRadius: radius, style: .continuous)
    }
    /// DR-12 — a nested pair's outer radius. Padding scales with uiScale and radii do not, so
    /// the pair is derived rather than spelled twice.
    static func concentric(inner: CGFloat, padding: CGFloat) -> CGFloat { inner + padding }

    // MARK: - Inbox Kind Colors
    // Leading-icon hue per inbox card kind. Decay amber, conflict red,
    // clarification indigo, merge yellow. Used by `KindGlyph`, the one
    // place an inbox kind shows its hue.
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
// Direction D graphite (DESIGN_RULES §3.1): the Meadow "night meadow" ink
// (#0D1216) retired as a base — its blue-green cast was hue spent on chrome
// (DR-1). One near-black base with small lightness steps, chroma ≤ 4. Entity,
// state, context, status and inbox hues are DATA and did not move (DR-8);
// graph.js mirrors them (GraphPaletteTwinTests). Nature tokens stay, for art
// and reward moments only (DR-13).

private extension CicadaTheme {
    enum Dark {
        static let bgRail = Color(hex: 0x0C0D0E)
        static let bgBase = Color(hex: 0x111213)
        static let bgPane = Color(hex: 0x141517)
        static let bgHover = Color(hex: 0x1B1C1E)
        static let bgFocus = Color(hex: 0x18191B)
        static let bgOption = Color(hex: 0x1D1E21)
        static let bgButton = Color(hex: 0x232427)
        static let bgButtonHover = Color(hex: 0x2C2D30)
        static let bgSelected = Color(hex: 0x222326)
        static let bgMenu = Color(hex: 0x1B1C1E)
        static let bgKey = Color(hex: 0x26272A)
        static let keyGlyph = Color(hex: 0x9A9CA1)
        static let bgBadge = Color(hex: 0x3A3B3F)
        static let border = Color(hex: 0x222324)        // white 7 % over bgBase (R-DS2)
        static let borderLight = Color(hex: 0x323334)   // white 14 % over bgBase

        // Measured on #111213: primary 17.2:1, secondary 12.3:1, tertiary 5.8:1, quaternary
        // 3.6:1 (disabled only). ThemeContrastTests holds every surface.
        static let textPrimary = Color(hex: 0xF5F5F6)
        static let textSecondary = Color(hex: 0xD0D1D4)
        static let textTertiary = Color(hex: 0x8D8F94)
        static let textQuaternary = Color(hex: 0x6A6C71)

        /// R-DS6 — the pre-D accent, frozen as the "active" status hue and the heat ramp.
        static let dataIndigo = Color(hex: 0x8C9CFF)
        static let onMeadow = bgBase
        static let scrim = Color.black.opacity(0.55)
        static let scrimPanel = Color.black.opacity(0.24)
        static let codeBackground = bgBase
        static let progressFill = Color(hex: 0x6FB57B)

        // State hues, Tailwind ~500 band — same brightness register as the
        // entity hues above so they read as one system on the near-black base.
        static let success = Color(hex: 0x22C55E)
        static let warning = Color(hex: 0xF59E0B)
        static let danger = Color(hex: 0xEF4444)
        static let info = Color(hex: 0x4A9EFF)

        // Nature (R-M2) — ambient only, never data.
        static let sky = Color(hex: 0x8EC3F0)
        static let skyWash = Color(hex: 0x1A2B3D)
        static let meadow = Color(hex: 0x7FC98A)
        static let meadowWash = Color(hex: 0x1B2B22)
        static let dandelion = Color(hex: 0xF6CF5A)
        static let dandelionFill = Color(hex: 0xD9A92E)
        static let cloud = Color(hex: 0xC9D3DE)
        static let bark = Color(hex: 0xB89C86)
        static let soil = Color(hex: 0x2A221E)

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
            case .active: dataIndigo
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
            // G141 PJ-6: a follow-up is a question the person answers —
            // clarification's hue, no new colour in the palette.
            case .followup: Color(hex: 0x8896FF)
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
// Direction D graphite (DESIGN_RULES §3.1): a warm near-white base (#F7F7F5)
// with white focus surfaces and graphite ink; the Meadow "day meadow" paper
// (#F4F6F1) and its green-black ink retired as a base (DR-1, DR-13). The
// deepened entity/status hues are data and did not move (DR-8).
//
// Measured, not assumed (WCAG 2.x, on #F7F7F5): person 4.89, project 5.04,
// directory 4.98 and location 4.55 clear 4.5:1 and may be used as text
// (location was 4.49 on the Meadow paper and crossed the bar with the new
// base). media 4.08, deadline 3.89, hub 3.82, tool 3.49, concept 3.38 and
// company 3.37 clear only the 3:1 non-text bar — dots, rings and fills, not
// body text. skill (#B48A00) is 2.98 and clears neither: never text, never an
// indicator without a label.
// `ThemeTokenTests.testLightEntityHueContrastIsWhatTheThemeCommentSays`
// holds it to the numbers. Deepening them is a separate data-colour decision
// graph.js must match.

private extension CicadaTheme {
    enum Light {
        static let bgRail = Color(hex: 0xEFEFEC)
        static let bgBase = Color(hex: 0xF7F7F5)
        static let bgPane = Color(hex: 0xFBFBFA)
        static let bgHover = Color(hex: 0xEFEFEC)
        static let bgFocus = Color(hex: 0xFFFFFF)
        static let bgOption = Color(hex: 0xF7F7F5)
        static let bgButton = Color(hex: 0xF2F2F0)
        static let bgButtonHover = Color(hex: 0xE3E3E0)
        static let bgSelected = Color(hex: 0xE8E8E5)
        static let bgMenu = Color(hex: 0xFFFFFF)
        static let bgKey = Color(hex: 0xEAEAE7)
        static let keyGlyph = Color(hex: 0x5A5B60)
        static let bgBadge = Color(hex: 0xD9D9D6)
        static let border = Color(hex: 0xE3E3E1)        // black 8 % over bgBase (R-DS2)
        static let borderLight = Color(hex: 0xCFCFCE)   // black 16 % over bgBase

        // Measured on #F7F7F5: primary 17.2:1, secondary 10.8:1, tertiary 5.0:1 (4.33:1 on
        // bgSelected — hence textTertiaryOnFill, 5.2:1), quaternary 3.2:1 (disabled only).
        static let textPrimary = Color(hex: 0x141415)
        static let textSecondary = Color(hex: 0x38393C)
        static let textTertiary = Color(hex: 0x6A6B70)
        static let textTertiaryOnFill = Color(hex: 0x5E5F64)
        static let textQuaternary = Color(hex: 0x8A8B90)

        static let dataIndigo = Color(hex: 0x4A5BD6)
        static let onMeadow = Color(hex: 0xFFFFFF)
        static let scrim = Color.black.opacity(0.35)
        static let scrimPanel = Color.black.opacity(0.12)
        static let codeBackground = bgBase
        static let progressFill = Color(hex: 0x37753D)

        // Same families, deepened into the Tailwind ~700 band so each clears
        // ~4.5:1 on the near-white surface instead of the ~1.8:1 the dark
        // values give.
        static let success = Color(hex: 0x15803D)
        static let warning = Color(hex: 0xB45309)
        static let danger = Color(hex: 0xB91C1C)
        static let info = Color(hex: 0x1D4ED8)

        // Nature (R-M2) — ambient only, never data.
        static let sky = Color(hex: 0x3571B0)
        static let skyWash = Color(hex: 0xD7E8F5)
        static let meadow = Color(hex: 0x37753D)
        static let meadowWash = Color(hex: 0xDCEBD6)
        static let dandelion = Color(hex: 0x8A6400)
        static let dandelionFill = Color(hex: 0xF5C542)
        static let cloud = Color(hex: 0xFFFFFF)
        static let bark = Color(hex: 0x6B5344)
        static let soil = Color(hex: 0x3B2F2A)

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
            case .active: dataIndigo
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
            case .followup: Color(hex: 0x5A62E0)
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
// Direction D (R-DS7; DR-9, DR-10, DR-14): a content card is the focus surface with a resting
// ring — no material, no border stroke, no shadow. The name survives so the 37 `.glassCard()`
// sites follow without a rename; Liquid Glass lives in `Theme/LiquidGlass.swift`, chrome only.
struct GlassCard: ViewModifier {
    var cornerRadius: CGFloat = CicadaTheme.cornerRadius

    func body(content: Content) -> some View {
        content
            .background(CicadaTheme.shape(cornerRadius).fill(CicadaTheme.surface))
            .clipShape(CicadaTheme.shape(cornerRadius))
            .ringed(.resting, in: CicadaTheme.shape(cornerRadius))
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

    /// G137 R-M4: the press dip is motion, so Reduce Motion drops it to the
    /// end state; the scale/opacity change itself still reads.
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .contentShape(Rectangle())
            .scaleEffect(configuration.isPressed ? Self.pressedScale : 1.0)
            .opacity(configuration.isPressed ? Self.pressedOpacity : 1.0)
            .animation(CicadaMotion.press(reduceMotion: reduceMotion), value: configuration.isPressed)
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

    /// G137 R-M4 — same switch as `CicadaPlainButtonStyle`.
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .contentShape(Rectangle())
            .modifier(GlassCard(cornerRadius: cornerRadius))
            .scaleEffect(configuration.isPressed ? CicadaPlainButtonStyle.pressedScale : 1.0)
            .opacity(configuration.isPressed ? CicadaPlainButtonStyle.pressedOpacity : 1.0)
            .animation(CicadaMotion.press(reduceMotion: reduceMotion), value: configuration.isPressed)
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
