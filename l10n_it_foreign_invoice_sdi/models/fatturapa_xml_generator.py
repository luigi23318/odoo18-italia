import base64
import logging
import os

from lxml import etree

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

NAMESPACE_FPA = 'http://ivaservizi.agenziaentrate.gov.it/docs/xsd/fatture/v1.2'
NAMESPACE_DS = 'http://www.w3.org/2000/09/xmldsig#'
NAMESPACE_XSI = 'http://www.w3.org/2001/XMLSchema-instance'

SCHEMA_LOCATION = (
    'http://ivaservizi.agenziaentrate.gov.it/docs/xsd/fatture/v1.2 '
    'http://www.fatturapa.gov.it/export/documenti/fatturapa/v1.2.2/'
    'Schema_del_file_xml_FatturaPA_v1.2.2.xsd'
)


class FatturaPAXmlGenerator(models.AbstractModel):
    _name = 'fatturapa.xml.generator'
    _description = 'Generatore XML FatturaPA per Fatture Estere'

    def generate(self, invoice):
        """Genera XML FatturaPA v1.2 per una fattura estera.

        :param invoice: record foreign.invoice.import
        :returns: tuple (xml_bytes, filename)
        """
        company = invoice.company_id
        progressive = self._get_progressive(company)
        invoice.progressive_number = progressive

        nsmap = {
            'p': NAMESPACE_FPA,
            'ds': NAMESPACE_DS,
            'xsi': NAMESPACE_XSI,
        }
        root = etree.Element(
            '{%s}FatturaElettronica' % NAMESPACE_FPA,
            nsmap=nsmap,
            attrib={
                '{%s}schemaLocation' % NAMESPACE_XSI: SCHEMA_LOCATION,
                'versione': 'FPR12',
            },
        )

        # FatturaElettronicaHeader
        header = etree.SubElement(root, '{%s}FatturaElettronicaHeader' % NAMESPACE_FPA)
        self._build_dati_trasmissione(header, company, invoice, progressive)
        self._build_cedente_prestatore(header, invoice)
        self._build_cessionario_committente(header, company)

        # FatturaElettronicaBody
        body = etree.SubElement(root, '{%s}FatturaElettronicaBody' % NAMESPACE_FPA)
        self._build_dati_generali(body, invoice)
        self._build_dati_beni_servizi(body, invoice)

        xml_bytes = etree.tostring(
            root, xml_declaration=True, encoding='UTF-8', pretty_print=True
        )

        country_code = company.country_id.code or 'IT'
        vat_number = (company.vat or '').replace(country_code, '')
        filename = f'{country_code}{vat_number}_{progressive}.xml'

        return xml_bytes, filename

    def validate_xsd(self, invoice):
        """Valida XML contro schema XSD.

        :param invoice: record foreign.invoice.import con xml_file
        :returns: list of error strings, empty if valid
        """
        if not invoice.xml_file:
            return [_('Nessun file XML da validare.')]

        xml_content = base64.b64decode(invoice.xml_file)
        errors = []

        try:
            xsd_path = os.path.join(
                os.path.dirname(__file__), '..', 'data',
                'Schema_del_file_xml_FatturaPA_v1.2.2.xsd'
            )
            if os.path.exists(xsd_path):
                with open(xsd_path, 'rb') as f:
                    schema_doc = etree.parse(f)
                schema = etree.XMLSchema(schema_doc)
                doc = etree.fromstring(xml_content)
                if not schema.validate(doc):
                    for error in schema.error_log:
                        errors.append(str(error))
            else:
                # Validazione strutturale di base se XSD non disponibile
                etree.fromstring(xml_content)
                _logger.info('Schema XSD non trovato, eseguita solo validazione strutturale.')
        except etree.XMLSyntaxError as e:
            errors.append(_('Errore di sintassi XML: %s') % str(e))

        return errors

    # -------------------------------------------------------------------------
    # PRIVATE BUILDER METHODS
    # -------------------------------------------------------------------------

    def _get_progressive(self, company):
        """Genera progressivo univoco invio."""
        seq = self.env['ir.sequence'].next_by_code('foreign.invoice.progressive')
        return seq or '00001'

    def _build_dati_trasmissione(self, header, company, invoice, progressive):
        ns = NAMESPACE_FPA
        dt = etree.SubElement(header, '{%s}DatiTrasmissione' % ns)

        id_trasm = etree.SubElement(dt, '{%s}IdTrasmittente' % ns)
        etree.SubElement(id_trasm, '{%s}IdPaese' % ns).text = company.country_id.code or 'IT'
        vat = (company.vat or '').replace(company.country_id.code or 'IT', '')
        etree.SubElement(id_trasm, '{%s}IdCodice' % ns).text = vat

        etree.SubElement(dt, '{%s}ProgressivoInvio' % ns).text = progressive
        etree.SubElement(dt, '{%s}FormatoTrasmissione' % ns).text = 'FPR12'
        etree.SubElement(dt, '{%s}CodiceDestinatario' % ns).text = '0000000'

    def _build_cedente_prestatore(self, header, invoice):
        ns = NAMESPACE_FPA
        cp = etree.SubElement(header, '{%s}CedentePrestatore' % ns)
        dati_anag = etree.SubElement(cp, '{%s}DatiAnagrafici' % ns)

        # IdFiscaleIVA
        id_fiscale = etree.SubElement(dati_anag, '{%s}IdFiscaleIVA' % ns)
        country_code = invoice.supplier_country_id.code if invoice.supplier_country_id else 'XX'
        etree.SubElement(id_fiscale, '{%s}IdPaese' % ns).text = country_code
        vat = (invoice.supplier_vat or '').replace(country_code, '')
        etree.SubElement(id_fiscale, '{%s}IdCodice' % ns).text = vat

        if invoice.supplier_tax_code:
            etree.SubElement(dati_anag, '{%s}CodiceFiscale' % ns).text = invoice.supplier_tax_code

        anagrafica = etree.SubElement(dati_anag, '{%s}Anagrafica' % ns)
        etree.SubElement(anagrafica, '{%s}Denominazione' % ns).text = (
            invoice.supplier_denomination or invoice.supplier_partner_id.name or 'N/A'
        )

        # Sede
        sede = etree.SubElement(cp, '{%s}Sede' % ns)
        etree.SubElement(sede, '{%s}Indirizzo' % ns).text = invoice.supplier_address_street or 'N/A'
        etree.SubElement(sede, '{%s}CAP' % ns).text = invoice.supplier_address_zip or '00000'
        etree.SubElement(sede, '{%s}Comune' % ns).text = invoice.supplier_address_city or 'N/A'
        if invoice.supplier_address_province:
            etree.SubElement(sede, '{%s}Provincia' % ns).text = invoice.supplier_address_province
        etree.SubElement(sede, '{%s}Nazione' % ns).text = country_code

    def _build_cessionario_committente(self, header, company):
        ns = NAMESPACE_FPA
        cc = etree.SubElement(header, '{%s}CessionarioCommittente' % ns)
        dati_anag = etree.SubElement(cc, '{%s}DatiAnagrafici' % ns)

        id_fiscale = etree.SubElement(dati_anag, '{%s}IdFiscaleIVA' % ns)
        etree.SubElement(id_fiscale, '{%s}IdPaese' % ns).text = 'IT'
        vat = (company.vat or '').replace('IT', '')
        etree.SubElement(id_fiscale, '{%s}IdCodice' % ns).text = vat

        if company.l10n_it_codice_fiscale:
            etree.SubElement(dati_anag, '{%s}CodiceFiscale' % ns).text = (
                company.l10n_it_codice_fiscale
            )

        anagrafica = etree.SubElement(dati_anag, '{%s}Anagrafica' % ns)
        etree.SubElement(anagrafica, '{%s}Denominazione' % ns).text = company.name

        # Sede
        sede = etree.SubElement(cc, '{%s}Sede' % ns)
        etree.SubElement(sede, '{%s}Indirizzo' % ns).text = company.street or 'N/A'
        etree.SubElement(sede, '{%s}CAP' % ns).text = company.zip or '00000'
        etree.SubElement(sede, '{%s}Comune' % ns).text = company.city or 'N/A'
        if company.state_id:
            etree.SubElement(sede, '{%s}Provincia' % ns).text = company.state_id.code
        etree.SubElement(sede, '{%s}Nazione' % ns).text = 'IT'

    def _build_dati_generali(self, body, invoice):
        ns = NAMESPACE_FPA
        dg = etree.SubElement(body, '{%s}DatiGenerali' % ns)
        dgd = etree.SubElement(dg, '{%s}DatiGeneraliDocumento' % ns)

        etree.SubElement(dgd, '{%s}TipoDocumento' % ns).text = invoice.document_type
        etree.SubElement(dgd, '{%s}Divisa' % ns).text = invoice.currency_id.name or 'EUR'
        etree.SubElement(dgd, '{%s}Data' % ns).text = (
            invoice.invoice_date.isoformat() if invoice.invoice_date else ''
        )
        etree.SubElement(dgd, '{%s}Numero' % ns).text = invoice.invoice_number or 'N/A'
        etree.SubElement(dgd, '{%s}ImportoTotaleDocumento' % ns).text = (
            f'{invoice.total_amount:.2f}'
        )

    def _build_dati_beni_servizi(self, body, invoice):
        ns = NAMESPACE_FPA
        dbs = etree.SubElement(body, '{%s}DatiBeniServizi' % ns)

        for idx, line in enumerate(invoice.line_ids, start=1):
            dl = etree.SubElement(dbs, '{%s}DettaglioLinee' % ns)
            etree.SubElement(dl, '{%s}NumeroLinea' % ns).text = str(idx)
            etree.SubElement(dl, '{%s}Descrizione' % ns).text = line.description or 'N/A'
            etree.SubElement(dl, '{%s}Quantita' % ns).text = f'{line.quantity:.2f}'
            if line.uom:
                etree.SubElement(dl, '{%s}UnitaMisura' % ns).text = line.uom
            etree.SubElement(dl, '{%s}PrezzoUnitario' % ns).text = f'{line.unit_price:.2f}'
            if line.discount:
                sc = etree.SubElement(dl, '{%s}ScontoMaggiorazione' % ns)
                etree.SubElement(sc, '{%s}Tipo' % ns).text = 'SC'
                etree.SubElement(sc, '{%s}Percentuale' % ns).text = f'{line.discount:.2f}'
            etree.SubElement(dl, '{%s}PrezzoTotale' % ns).text = f'{line.price_subtotal:.2f}'
            etree.SubElement(dl, '{%s}AliquotaIVA' % ns).text = f'{line.tax_rate:.2f}'
            if line.natura:
                etree.SubElement(dl, '{%s}Natura' % ns).text = line.natura

        # DatiRiepilogo
        tax_groups = {}
        for line in invoice.line_ids:
            key = (line.tax_rate, line.natura or '')
            if key not in tax_groups:
                tax_groups[key] = {'imponibile': 0.0, 'imposta': 0.0}
            tax_groups[key]['imponibile'] += line.price_subtotal
            tax_groups[key]['imposta'] += line.tax_amount

        for (aliquota, natura), vals in tax_groups.items():
            dr = etree.SubElement(dbs, '{%s}DatiRiepilogo' % ns)
            etree.SubElement(dr, '{%s}AliquotaIVA' % ns).text = f'{aliquota:.2f}'
            if natura:
                etree.SubElement(dr, '{%s}Natura' % ns).text = natura
            etree.SubElement(dr, '{%s}ImponibileImporto' % ns).text = (
                f'{vals["imponibile"]:.2f}'
            )
            etree.SubElement(dr, '{%s}Imposta' % ns).text = f'{vals["imposta"]:.2f}'
            etree.SubElement(dr, '{%s}EsigibilitaIVA' % ns).text = 'I'
