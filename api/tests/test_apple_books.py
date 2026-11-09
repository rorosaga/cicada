"""app-fixes-1109: Apple Books file-name titles and placeholder authors. Synthetic placeholders only."""


def test_a_file_name_title_is_cleaned_and_a_placeholder_author_is_no_author():
    """app-fixes-1109: a file the person added to Apple Books has a cut file name for a title and `UnknownAuthor`."""
    from api.services import apple_books

    assert apple_books.clean_title("Batman-Year-One-The-Deluxe-Editi") == "Batman Year One The Deluxe"   # 32 chars: cut
    assert apple_books.clean_title("Caped_Lantern_Year_One.epub") == "Caped Lantern Year One"           # no cut, no extension
    assert apple_books.clean_title("The Lantern Orchard") == "The Lantern Orchard"                      # a real title
    assert apple_books.clean_title("Spider-Man") == "Spider-Man"                                        # one dash is a name
    assert apple_books.clean_author("UnknownAuthor") == "" and apple_books.clean_author("Unknown Author") == ""
    assert apple_books.clean_author("Ada Example") == "Ada Example"
