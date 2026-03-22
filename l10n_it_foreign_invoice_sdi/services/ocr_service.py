import base64
import io
import logging
import subprocess
import tempfile

_logger = logging.getLogger(__name__)


class OcrService:
    """Estrae testo grezzo da PDF: pdfplumber (digitali) + Tesseract (scansioni)."""

    MIN_TEXT_LENGTH = 50

    def extract_text(
        self, attachment: 'ir.attachment', languages: str = 'ita+eng+deu+fra+spa'
    ) -> str:
        """Estrae testo dal PDF allegato.

        Primo tentativo con pdfplumber (PDF digitali).
        Fallback Tesseract OCR se il testo estratto è < 50 caratteri.
        """
        pdf_content = base64.b64decode(attachment.datas)

        text = self._extract_with_pdfplumber(pdf_content)
        if len(text.strip()) >= self.MIN_TEXT_LENGTH:
            _logger.info(
                'pdfplumber: estratti %d caratteri da %s',
                len(text), attachment.name,
            )
            return text

        _logger.info(
            'pdfplumber insufficiente (%d car.), fallback Tesseract per %s',
            len(text.strip()), attachment.name,
        )
        return self._extract_with_tesseract(pdf_content, languages)

    def _extract_with_pdfplumber(self, pdf_content: bytes) -> str:
        """Estrae testo con pdfplumber (PDF digitali nativi)."""
        try:
            import pdfplumber
        except ImportError:
            _logger.warning('pdfplumber non installato, skip.')
            return ''

        try:
            pages_text = []
            with pdfplumber.open(io.BytesIO(pdf_content)) as pdf:
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        pages_text.append(page_text)
            return '\n'.join(pages_text)
        except Exception:
            _logger.exception('Errore pdfplumber')
            return ''

    def _extract_with_tesseract(
        self, pdf_content: bytes, languages: str
    ) -> str:
        """Estrae testo con Tesseract OCR (PDF scansionati)."""
        try:
            import pytesseract
            from pdf2image import convert_from_bytes
        except ImportError:
            _logger.warning(
                'pytesseract o pdf2image non installati. '
                'Installare: pip install pytesseract pdf2image'
            )
            return ''

        try:
            images = convert_from_bytes(pdf_content)
            pages_text = []
            for img in images:
                text = pytesseract.image_to_string(img, lang=languages)
                if text:
                    pages_text.append(text)
            result = '\n'.join(pages_text)
            _logger.info('Tesseract: estratti %d caratteri', len(result))
            return result
        except Exception:
            _logger.exception('Errore Tesseract OCR')
            return ''
