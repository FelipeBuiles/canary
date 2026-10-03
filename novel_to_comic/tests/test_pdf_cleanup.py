"""PDF cleanup is applied before immutable source text and chapter grouping."""

from novel_to_comic.chapter_detection import detect_chapters
from novel_to_comic.pdf_cleanup import clean_pdf_text


def test_watermarks_controls_and_small_caps_are_removed_without_joining_words():
    text = 'OceanofPDF.com\n\n[ 1 ]\nT HE  TRANSFORMATION\nI SAID A HOUSE.\nDonut agrees. D ONUT replies.\nA ND she waits.\x00\x08\n'
    cleaned = clean_pdf_text(text)
    assert 'OceanofPDF' not in cleaned
    assert 'THE  TRANSFORMATION' in cleaned
    assert 'I SAID A HOUSE.' in cleaned
    assert 'DONUT replies.' in cleaned
    assert 'AND she waits.' in cleaned
    assert '\x00' not in cleaned and '\x08' not in cleaned


def test_wrapped_compounds_keep_their_hyphens_and_known_word_wraps_join():
    text = 'A red-\nsequined gown.\nAn inter\u00ad\nnational meeting.\nRefilled once, re-\nfilled twice.'
    assert clean_pdf_text(text) == 'A red-sequined gown.\nAn international meeting.\nRefilled once, refilled twice.'


def test_author_back_matter_is_trimmed_but_a_contents_entry_is_preserved():
    body = '[ 1 ]\n' + 'The tide turned. ' * 50
    text = 'Contents\nABOUT THE AUTHOR\n\n' + body + '\n\nABOUT THE AUTHOR\nBiography and recommendations.'
    cleaned = clean_pdf_text(text)
    assert cleaned.startswith('Contents\nABOUT THE AUTHOR')
    assert cleaned.endswith('The tide turned.\n')
    assert 'Biography' not in cleaned
    assert clean_pdf_text('Contents\nABOUT THE AUTHOR\n\n' + body).endswith(body)


def test_cleanup_preserves_chapter_divisions_and_is_idempotent():
    body = 'The lighthouse kept its light. ' * 12
    text = f'OceanofPDF.com\n\n[ 1 ]\n{body}\nOceanofPDF.com\n\n[ 2 ]\n{body}'
    cleaned = clean_pdf_text(text)
    assert [chapter.title for chapter in detect_chapters(cleaned)] == ['[ 1 ]', '[ 2 ]']
    assert clean_pdf_text(cleaned) == cleaned
