import logging
import re
from datetime import date

from lxml import etree

from odoo import api, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

FATTURAPA_NS = 'http://ivaservizi.agenziaentrate.gov.it/docs/xsd/fatture/v1.2'
DS_NS = 'http://www.w3.org/2000/09/xmldsig#'

NSMAP = {
    'p': FATTURAPA_NS,
    'ds': DS_NS,
}


class FatturaPAXmlGenerator(models.AbstractModel):
    _name = 'fatturapa.xml.generator'
    _description = 'Generatore XML FatturaPA v1.2.3'

    @api.model
    def generate_xml(self, invoice: 'foreign.invoice.import') -> tuple[str, str]:
        """Genera XML FatturaPA conforme allo schema v1.2.3.

        Returns:
            tuple: (xml_string, filename)
        """
        company = self.env.company
        root = self._build_xml(invoice, company)
        self._validate_xsd(root)

        xml_string = etree.tostring(
            root,
            xml_declaration=True,
            encoding='UTF-8',
            pretty_print=True,
        ).decode('utf-8')

        filename = self._generate_filename(company, invoice)
        _logger.info(
            'XML FatturaPA generato: %s per %s', filename, invoice.name,
        )
        return xml_string, filename

    def _build_xml(
        self, invoice: 'foreign.invoice.import', company: 'res.company',
    ) -> etree._Element:
        """Costruisce l'albero XML FatturaPA."""
        root = etree.Element(
            '{%s}FatturaElettronica' % FATTURAPA_NS,
            nsmap=NSMAP,
            attrib={'versione': 'FPR12'},
        )
        self._add_header(root, invoice, company)
        self._add_body(root, invoice, company)
        return root

    def _add_header(
        self, root, invoice: 'foreign.invoice.import', company: 'res.company',
    ) -> None:
        """FatturaElettronicaHeader."""
        header = etree.SubElement(
            root, '{%s}FatturaElettronicaHeader' % FATTURAPA_NS,
        )

        # DatiTrasmissione
        dt = etree.SubElement(header, '{%s}DatiTrasmissione' % FATTURAPA_NS)
        id_trasm = etree.SubElement(dt, '{%s}IdTrasmittente' % FATTURAPA_NS)
        etree.SubElement(
            id_trasm, '{%s}IdPaese' % FATTURAPA_NS,
        ).text = 'IT'
        etree.SubElement(
            id_trasm, '{%s}IdCodice' % FATTURAPA_NS,
        ).text = re.sub(r'[^A-Za-z0-9]', '', company.vat or '')[:28]

        etree.SubElement(
            dt, '{%s}ProgressivoInvio' % FATTURAPA_NS,
        ).text = (invoice.name or '').replace('/', '')[:10]

        etree.SubElement(
            dt, '{%s}FormatoTrasmissione' % FATTURAPA_NS,
        ).text = 'FPR12'

        ICP = self.env['ir.config_parameter'].sudo()
        codice_dest = ICP.get_param(
            'foreign_invoice.codice_destinatario', 'XXXXXXX',
        )
        etree.SubElement(
            dt, '{%s}CodiceDestinatario' % FATTURAPA_NS,
        ).text = codice_dest

        # CedentePrestatore (fornitore estero)
        cp = etree.SubElement(header, '{%s}CedentePrestatore' % FATTURAPA_NS)
        cp_dati = etree.SubElement(cp, '{%s}DatiAnagrafici' % FATTURAPA_NS)

        if invoice.supplier_vat:
            id_fiscale = etree.SubElement(
                cp_dati, '{%s}IdFiscaleIVA' % FATTURAPA_NS,
            )
            country_code = (
                invoice.supplier_country_id.code
                if invoice.supplier_country_id else 'OO'
            )
            etree.SubElement(
                id_fiscale, '{%s}IdPaese' % FATTURAPA_NS,
            ).text = country_code

            vat_code = invoice.supplier_vat
            if vat_code.upper().startswith(country_code):
                vat_code = vat_code[len(country_code):]
            etree.SubElement(
                id_fiscale, '{%s}IdCodice' % FATTURAPA_NS,
            ).text = vat_code[:28]

        anag = etree.SubElement(cp_dati, '{%s}Anagrafica' % FATTURAPA_NS)
        etree.SubElement(
            anag, '{%s}Denominazione' % FATTURAPA_NS,
        ).text = (invoice.supplier_name or 'N/A')[:80]

        # Sede CedentePrestatore
        sede_cp = etree.SubElement(cp, '{%s}Sede' % FATTURAPA_NS)
        partner = invoice.partner_id
        etree.SubElement(
            sede_cp, '{%s}Indirizzo' % FATTURAPA_NS,
        ).text = (
            partner.street if partner and partner.street else 'Estero'
        )[:60]
        etree.SubElement(
            sede_cp, '{%s}CAP' % FATTURAPA_NS,
        ).text = '00000'
        etree.SubElement(
            sede_cp, '{%s}Comune' % FATTURAPA_NS,
        ).text = (
            partner.city if partner and partner.city else 'Estero'
        )[:60]
        etree.SubElement(
            sede_cp, '{%s}Nazione' % FATTURAPA_NS,
        ).text = (
            invoice.supplier_country_id.code
            if invoice.supplier_country_id else 'OO'
        )

        # CessionarioCommittente (azienda italiana)
        cc = etree.SubElement(
            header, '{%s}CessionarioCommittente' % FATTURAPA_NS,
        )
        cc_dati = etree.SubElement(cc, '{%s}DatiAnagrafici' % FATTURAPA_NS)

        if company.vat:
            id_fiscale_cc = etree.SubElement(
                cc_dati, '{%s}IdFiscaleIVA' % FATTURAPA_NS,
            )
            etree.SubElement(
                id_fiscale_cc, '{%s}IdPaese' % FATTURAPA_NS,
            ).text = 'IT'
            company_vat = company.vat
            if company_vat.upper().startswith('IT'):
                company_vat = company_vat[2:]
            etree.SubElement(
                id_fiscale_cc, '{%s}IdCodice' % FATTURAPA_NS,
            ).text = company_vat[:28]

        if company.l10n_it_codice_fiscale:
            etree.SubElement(
                cc_dati, '{%s}CodiceFiscale' % FATTURAPA_NS,
            ).text = company.l10n_it_codice_fiscale[:16]

        anag_cc = etree.SubElement(cc_dati, '{%s}Anagrafica' % FATTURAPA_NS)
        etree.SubElement(
            anag_cc, '{%s}Denominazione' % FATTURAPA_NS,
        ).text = (company.name or 'N/A')[:80]

        # Sede CessionarioCommittente
        sede_cc = etree.SubElement(cc, '{%s}Sede' % FATTURAPA_NS)
        etree.SubElement(
            sede_cc, '{%s}Indirizzo' % FATTURAPA_NS,
        ).text = (company.street or 'Via')[:60]
        etree.SubElement(
            sede_cc, '{%s}CAP' % FATTURAPA_NS,
        ).text = (company.zip or '00000')[:5]
        etree.SubElement(
            sede_cc, '{%s}Comune' % FATTURAPA_NS,
        ).text = (company.city or 'Città')[:60]
        if company.state_id:
            etree.SubElement(
                sede_cc, '{%s}Provincia' % FATTURAPA_NS,
            ).text = company.state_id.code[:2]
        etree.SubElement(
            sede_cc, '{%s}Nazione' % FATTURAPA_NS,
        ).text = 'IT'

        # SoggettoEmittente
        etree.SubElement(
            header, '{%s}SoggettoEmittente' % FATTURAPA_NS,
        ).text = 'CC'

    def _add_body(
        self, root, invoice: 'foreign.invoice.import', company: 'res.company',
    ) -> None:
        """FatturaElettronicaBody."""
        body = etree.SubElement(
            root, '{%s}FatturaElettronicaBody' % FATTURAPA_NS,
        )

        # DatiGenerali
        dg = etree.SubElement(body, '{%s}DatiGenerali' % FATTURAPA_NS)
        dgd = etree.SubElement(dg, '{%s}DatiGeneraliDocumento' % FATTURAPA_NS)

        etree.SubElement(
            dgd, '{%s}TipoDocumento' % FATTURAPA_NS,
        ).text = invoice.tipo_documento

        etree.SubElement(
            dgd, '{%s}Divisa' % FATTURAPA_NS,
        ).text = invoice.currency_id.name or 'EUR'

        doc_date = invoice.reception_date or invoice.invoice_date or date.today()
        etree.SubElement(
            dgd, '{%s}Data' % FATTURAPA_NS,
        ).text = doc_date.strftime('%Y-%m-%d')

        etree.SubElement(
            dgd, '{%s}Numero' % FATTURAPA_NS,
        ).text = invoice.name or '0'

        etree.SubElement(
            dgd, '{%s}ImportoTotaleDocumento' % FATTURAPA_NS,
        ).text = '%.2f' % (invoice.amount_total or invoice.amount_untaxed or 0)

        # DatiFattureCollegate
        if invoice.invoice_number:
            dfc = etree.SubElement(
                dg, '{%s}DatiFattureCollegate' % FATTURAPA_NS,
            )
            etree.SubElement(
                dfc, '{%s}IdDocumento' % FATTURAPA_NS,
            ).text = invoice.invoice_number[:20]
            if invoice.invoice_date:
                etree.SubElement(
                    dfc, '{%s}Data' % FATTURAPA_NS,
                ).text = invoice.invoice_date.strftime('%Y-%m-%d')

        # DatiBeniServizi
        dbs = etree.SubElement(body, '{%s}DatiBeniServizi' % FATTURAPA_NS)

        if invoice.line_ids:
            for idx, line in enumerate(invoice.line_ids, 1):
                self._add_dettaglio_linea(
                    dbs, idx,
                    line.description or invoice.description_type or '/',
                    line.quantity or 1, line.unit_price or 0,
                    line.line_total or 0, invoice,
                )
        else:
            self._add_dettaglio_linea(
                dbs, 1,
                invoice.description_type or 'Servizi',
                1, invoice.amount_untaxed or invoice.amount_total or 0,
                invoice.amount_untaxed or invoice.amount_total or 0,
                invoice,
            )

        # DatiRiepilogo
        dr = etree.SubElement(dbs, '{%s}DatiRiepilogo' % FATTURAPA_NS)
        tax_rate = 0.0
        if invoice.it_tax_id and invoice.it_tax_id.amount:
            tax_rate = invoice.it_tax_id.amount
        etree.SubElement(
            dr, '{%s}AliquotaIVA' % FATTURAPA_NS,
        ).text = '%.2f' % tax_rate

        if invoice.natura_code:
            etree.SubElement(
                dr, '{%s}Natura' % FATTURAPA_NS,
            ).text = invoice.natura_code

        etree.SubElement(
            dr, '{%s}ImponibileImporto' % FATTURAPA_NS,
        ).text = '%.2f' % (invoice.amount_untaxed or invoice.amount_total or 0)

        imposta = (invoice.amount_untaxed or 0) * tax_rate / 100
        etree.SubElement(
            dr, '{%s}Imposta' % FATTURAPA_NS,
        ).text = '%.2f' % imposta

        etree.SubElement(
            dr, '{%s}EsigibilitaIVA' % FATTURAPA_NS,
        ).text = 'I'

    def _add_dettaglio_linea(
        self, parent, num: int, description: str,
        quantity: float, price: float, total: float,
        invoice: 'foreign.invoice.import',
    ) -> None:
        """Aggiunge un DettaglioLinee."""
        dl = etree.SubElement(parent, '{%s}DettaglioLinee' % FATTURAPA_NS)
        etree.SubElement(
            dl, '{%s}NumeroLinea' % FATTURAPA_NS,
        ).text = str(num)
        etree.SubElement(
            dl, '{%s}Descrizione' % FATTURAPA_NS,
        ).text = (description or '/')[:1000]
        etree.SubElement(
            dl, '{%s}Quantita' % FATTURAPA_NS,
        ).text = '%.2f' % quantity
        etree.SubElement(
            dl, '{%s}PrezzoUnitario' % FATTURAPA_NS,
        ).text = '%.2f' % price
        etree.SubElement(
            dl, '{%s}PrezzoTotale' % FATTURAPA_NS,
        ).text = '%.2f' % total

        tax_rate = 0.0
        if invoice.it_tax_id and invoice.it_tax_id.amount:
            tax_rate = invoice.it_tax_id.amount
        etree.SubElement(
            dl, '{%s}AliquotaIVA' % FATTURAPA_NS,
        ).text = '%.2f' % tax_rate

        if invoice.natura_code:
            etree.SubElement(
                dl, '{%s}Natura' % FATTURAPA_NS,
            ).text = invoice.natura_code

    def _validate_xsd(self, root: etree._Element) -> None:
        """Valida l'XML contro lo schema XSD FatturaPA."""
        import os
        xsd_path = os.path.join(
            os.path.dirname(__file__), '..', 'data',
            'Schema_del_file_xml_FatturaPA_v1.2.2.xsd',
        )
        if not os.path.isfile(xsd_path):
            _logger.warning(
                'File XSD non trovato in %s. '
                'Validazione XSD saltata. Scaricare lo schema da '
                'fatturapa.gov.it e posizionarlo nella directory data/',
                xsd_path,
            )
            return

        try:
            schema_doc = etree.parse(xsd_path)
            schema = etree.XMLSchema(schema_doc)
            if not schema.validate(root):
                errors = '\n'.join(str(e) for e in schema.error_log)
                _logger.error('Errori validazione XSD:\n%s', errors)
                raise UserError(
                    _('Errori validazione XSD:\n%s') % errors
                )
            _logger.info('Validazione XSD superata.')
        except etree.XMLSchemaParseError as e:
            _logger.warning('Errore parsing XSD: %s', e)

    def _generate_filename(
        self, company: 'res.company', invoice: 'foreign.invoice.import',
    ) -> str:
        """Genera il nome file secondo le specifiche SDI.

        Formato: IT<partita_iva>_<progressivo>.xml
        """
        vat = re.sub(r'[^A-Za-z0-9]', '', company.vat or '00000000000')
        if vat.upper().startswith('IT'):
            vat = vat[2:]
        progressive = re.sub(r'[^A-Za-z0-9]', '', invoice.name or '00001')
        return f'IT{vat}_{progressive}.xml'
