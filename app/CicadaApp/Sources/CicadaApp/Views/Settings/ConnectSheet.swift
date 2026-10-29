import SwiftUI

/// The connect sheets' one shape (owner 2026-10-29, on the Telegram sheet: *"This is super ugly by the way. Make it
/// more modern and minimal, with the country codes and such."*; DESIGN_RULES §9, 2026-10-29). Every sheet that signs a
/// source in — Telegram, a token or app-key connector — draws its steps from these pieces, inside `SettingsSheet`:
///
/// - **One action per step.** `ConnectSheetActions`: one primary (`PrimaryActionButton`, DR-40, ⏎) and Cancel as a
///   quiet `TextButton`; a step that waits on the person elsewhere (a QR to scan, a browser to finish) has no primary.
///   "Done" exists only once something is connected.
/// - **What it reads, in one line.** `ConnectFactsLine`: the one sentence the rails need before connecting, in caption
///   ink, then "What Cicada reads" — a `TextButton` that swaps the sheet's body for the full words
///   (`ConnectFactsPage`, Back returns). A page swap, never a fold (DR-81) and never a popover (R-HS16).
/// - **Phone numbers by country.** `PhoneNumberEntry`: a country button (flag + dial code) and the national number in
///   its own native field (DR-76: setup sheets keep the native field), grouped as typed; the country list is a page of
///   the same sheet (`CountryList`), searchable, defaulting to the Mac's region (`PhoneCountry`).
/// - **One-time codes as cells.** `OneTimeCodeField`: one real field (`.oneTimeCode`, paste and autofill work) drawn
///   as five cells; the next empty cell carries the focus ring (DR-5, use 1), and the last digit submits.

// MARK: - Actions

struct ConnectSheetActions: View {
    var leading: AnyView? = nil
    let primary: String?
    var primaryDisabled = false
    var onPrimary: () -> Void = {}
    var cancel: String = Copy.Connect.cancel
    let onCancel: () -> Void

    var body: some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            if let leading { leading }
            Spacer(minLength: CicadaTheme.spacingSM)
            TextButton(title: cancel, action: onCancel)
            if let primary {
                PrimaryActionButton(title: primary, action: onPrimary)
                    .keyboardShortcut(.defaultAction)
                    .disabled(primaryDisabled)
            }
        }
    }
}

// MARK: - What it reads

/// The rails' one sentence before connecting, then the link to the full words.
struct ConnectFactsLine: View {
    let text: String
    let onMore: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text(text)
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
            TextButton(title: Copy.Connect.whatItReads, inline: true, flushLeading: true, action: onMore)
        }
    }
}

/// The full words, as the sheet's whole body until Back.
struct ConnectFactsPage: View {
    let paragraphs: [String]
    let onBack: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            ForEach(paragraphs.filter { !$0.isEmpty }, id: \.self) { paragraph in
                Text(paragraph)
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            ConnectSheetActions(primary: nil, cancel: Copy.Connect.back, onCancel: onBack)
        }
    }
}

// MARK: - Phone number

struct PhoneNumberEntry: View {
    @Binding var country: PhoneCountry
    @Binding var national: String
    let onPickCountry: () -> Void
    var onSubmit: () -> Void = {}
    @FocusState private var focused: Bool

    var body: some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            NeutralButton(title: "\(country.flag)  \(country.dialLabel)", trailingSystemImage: "chevron.up.chevron.down",
                          help: Copy.Connect.countryHelp(country.name()), action: onPickCountry)
                .accessibilityLabel(Copy.Connect.countryAccessibility(country.name(), country.dialLabel))
            TextField(Copy.Connect.phonePrompt, text: $national)
                .textFieldStyle(.roundedBorder)
                .controlSize(.large)
                .monospacedDigit()
                .textContentType(.telephoneNumber)
                .focused($focused)
                .onSubmit(onSubmit)
                // Grouped as typed; formatting in the binding's setter does not reach a field being edited.
                .onChange(of: national) { _, typed in
                    let grouped = PhoneCountry.formatNational(typed)
                    if grouped != typed { national = grouped }
                }
        }
        .onAppear { focused = true }
    }
}

/// The country list, as the sheet's body: a search field, then every country — flag, name, dial code.
struct CountryList: View {
    let selected: PhoneCountry
    let onPick: (PhoneCountry) -> Void
    let onBack: () -> Void
    @State private var query = ""
    @FocusState private var focused: Bool
    private let all = PhoneCountry.all()

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            TextField(Copy.Connect.countrySearch, text: $query)
                .textFieldStyle(.roundedBorder)
                .focused($focused)
                .onSubmit { if let first = PhoneCountry.search(query, in: all).first { onPick(first) } }
            ScrollViewReader { proxy in
                ScrollView {
                    VStack(spacing: 0) {   // not lazy: ~240 rows, and the chosen one must exist to scroll to
                        ForEach(PhoneCountry.search(query, in: all)) { country in
                            CountryRow(country: country, selected: country == selected) { onPick(country) }
                                .id(country.id)
                        }
                    }
                }
                .frame(height: CicadaTheme.scaled(300))
                .task { proxy.scrollTo(selected.id, anchor: .center) }
            }
            ConnectSheetActions(primary: nil, cancel: Copy.Connect.back, onCancel: onBack)
        }
        .onAppear { focused = true }
    }
}

private struct CountryRow: View {
    let country: PhoneCountry
    let selected: Bool
    let action: () -> Void
    @State private var hovering = false

    var body: some View {
        Button(action: action) {
            HStack(spacing: CicadaTheme.spacingSM) {
                Text(country.flag).font(CicadaTheme.bodyFont)
                Text(country.name()).font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textPrimary).lineLimit(1)
                Spacer(minLength: CicadaTheme.spacingSM)
                Text(country.dialLabel).font(CicadaTheme.bodyFont).monospacedDigit()
                    .foregroundStyle(CicadaTheme.textSecondary)
                if selected {
                    Image(systemName: "checkmark").font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
                }
            }
            .padding(.horizontal, CicadaTheme.spacingSM)
            .frame(height: CicadaTheme.scaled(28))
            .contentShape(Rectangle())
            .background(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall)
                .fill(hovering || selected ? CicadaTheme.bgSelected : Color.clear))
        }
        .buttonStyle(.cicadaPlain)
        .onHover { hovering = $0 }
        .accessibilityLabel("\(country.name()), \(country.dialLabel)")
        .accessibilityAddTraits(selected ? .isSelected : [])
    }
}

// MARK: - One-time code

/// One field drawn as `length` cells. Typing, pasting or autofill fill the cells left to right; a backspace steps
/// back; the last digit calls `onComplete`.
struct OneTimeCodeField: View {
    /// Telegram's login codes are five digits.
    static let telegramLength = 5

    @Binding var code: String
    var length = telegramLength
    let onComplete: (String) -> Void
    @FocusState private var focused: Bool

    static func accept(_ text: String, length: Int) -> String { String(text.filter(\.isNumber).prefix(length)) }

    var body: some View {
        ZStack {
            TextField("", text: Binding(get: { code }, set: { new in
                let digits = Self.accept(new, length: length)
                code = digits
                if digits.count == length { onComplete(digits) }
            }))
            .textFieldStyle(.plain)
            .textContentType(.oneTimeCode)
            .focused($focused)
            .foregroundStyle(.clear)
            .tint(.clear)
            .accessibilityLabel(Copy.Connect.codeAccessibility(length))
            HStack(spacing: CicadaTheme.spacingSM) {
                ForEach(0..<length, id: \.self) { i in cell(i) }
            }
            .allowsHitTesting(false)
            .accessibilityHidden(true)
        }
        .contentShape(Rectangle())
        .onTapGesture { focused = true }
        .onAppear { focused = true }
    }

    private func cell(_ i: Int) -> some View {
        let chars = Array(code)
        let active = focused && i == min(chars.count, length - 1)
        return Text(i < chars.count ? String(chars[i]) : "")
            .font(CicadaTheme.font(size: 22, weight: .medium))
            .monospacedDigit()
            .foregroundStyle(CicadaTheme.textPrimary)
            .frame(width: CicadaTheme.scaled(44), height: CicadaTheme.scaled(52))
            .background(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall).fill(CicadaTheme.bgBase))
            .overlay(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall)
                .strokeBorder(CicadaField.ring(focused: active), lineWidth: active ? 1.5 : 1))
    }
}
