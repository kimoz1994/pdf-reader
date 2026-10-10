"""Shared flashcard answer rendering (#56/#58).

One U+FFFC walk for card-owned image blobs: used by the Make-flashcard
dialog preview (#56) and the FSRS review session (#58), so both render
snapshots identically — text with inline images, undecodable blobs
falling back to a literal placeholder.
"""
from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QImage, QTextDocument, QTextImageFormat

from services.extract_store import IMG_PLACEHOLDER

# Preview cap for answer images: a huge capture is scaled down to this
# width; aspect kept.
FC_PREVIEW_W = 480


def fill_answer(text_edit, answer_text, image_blobs):
    """Write the snapshot into `text_edit`: plain text, with each U+FFFC
    replaced by its blob (#56). Blobs are consumed in order; a
    placeholder with no blob left (or an undecodable one) stays a
    literal U+FFFC — same pairing rule as the snapshot seam."""
    cursor = text_edit.textCursor()
    blob_iter = iter(image_blobs)
    for part in answer_text.split(IMG_PLACEHOLDER):
        if part:
            cursor.insertText(part)
        blob = next(blob_iter, None)
        if blob is not None:
            image = QImage.fromData(blob)
            if not image.isNull():
                url = f"fcpreview://{id(blob):x}"
                text_edit.document().addResource(
                    QTextDocument.ResourceType.ImageResource,
                    QUrl(url),
                    image,
                )
                fmt = QTextImageFormat()
                fmt.setName(url)
                if image.width() > FC_PREVIEW_W:
                    fmt.setWidth(FC_PREVIEW_W)
                    fmt.setHeight(
                        round(image.height() * FC_PREVIEW_W / image.width())
                    )
                cursor.insertImage(fmt)
            else:
                cursor.insertText(IMG_PLACEHOLDER)
    # answer_text ends with a placeholder -> the split's last chunk
    # is "" and the loop above already consumed every blob; nothing
    # further to append.
