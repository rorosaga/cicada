import Foundation

/// Settings v3 and recommended skills (G139, G138). An extension so this
/// track's strings stay out of `Copy.swift`'s busy tail (R-O30); the two
/// `Copy` rules still hold — pointers are built from their parts, subtitles
/// are one sentence of at most 60 characters that never repeat their title.
extension Copy {
    // MARK: Groups (spec decision 17)
    static let groupCicada = "Cicada"
    static let groupCustomize = "Customize"
    static let groupEnginesAndKeys = "Engines & keys"

    // MARK: General
    static let appearance = "Appearance"
    static let appearanceSystem = "System"
    static let appearanceLight = "Light"
    static let appearanceDark = "Dark"
    static let textSize = "Text size"
    static let textSizeDetail = "⌘+ and ⌘− do the same from any page."
    static let actualSize = "Actual size"
    static let setup = "Setup"
    static let runSetupAgain = "Run setup again"
    static let runSetupDetail = "Walk through the first steps for this memory again."
}
